import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import hwpx_automation.ops_services.transactions as transactions_module
import hwpx_automation.server as server_module
import hwpx_automation.workspace as workspace_module
import hwpx.patch as hwpx_patch_module
from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.server import (
    add_heading,
    add_memo,
    add_page_break,
    add_paragraph,
    add_table,
    byte_preserving_patch,
    copy_document,
    create_document,
    delete_paragraph,
    fill_by_path,
    find_cell_by_label,
    find_text,
    format_table,
    get_document_outline,
    get_document_text,
    get_paragraph_text,
    get_paragraphs_text,
    get_table_map,
    get_table_text,
    insert_paragraph,
    insert_picture,
    list_available_documents,
    remove_memo,
    replace_picture,
    replace_by_anchor,
    replace_in_paragraph,
    set_table_cell_text,
)
from hwpx_automation.utils.helpers import resolve_path
from hwpx_automation.workspace import WorkspacePathError

_FORM_ROWS = [["성명:", ""], ["소속", ""], ["합계", "100"]]
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"

PNG_1X1_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axwAqkAAAAASUVORK5CYII="
PNG_1X1_ALT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/l8EydgAAAABJRU5ErkJggg=="


def _recovery_files(base: Path, marker: str) -> list[Path]:
    return list(
        base.parent.glob(f".{base.name}.{marker}.*.recovery")
    )


def _create_form_document(target: Path) -> None:
    create_document(str(target))
    add_paragraph(str(target), "기본정보")
    add_table(str(target), len(_FORM_ROWS), len(_FORM_ROWS[0]), _FORM_ROWS)


def _create_ambiguous_form_document(target: Path) -> None:
    _create_form_document(target)
    add_paragraph(str(target), "추가정보")
    add_table(str(target), 1, 2, [["성명", ""]])


def _replace_zip_part(path: Path, part_name: str, payload: bytes) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path, "r") as source:
        with zipfile.ZipFile(tmp_path, "w") as target:
            for info in source.infolist():
                data = (
                    payload
                    if info.filename == part_name
                    else source.read(info.filename)
                )
                target.writestr(info, data)
    path.write_bytes(tmp_path.read_bytes())
    tmp_path.unlink()


def test_add_paragraph(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    result = add_paragraph(str(target), "안녕하세요")
    text_result = get_document_text(str(target))

    assert "안녕하세요" in text_result["text"]
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["filePath"] == str(target)


def test_insert_and_replace_picture_tools_preserve_safe_asset_graph(tmp_path: Path):
    target = tmp_path / "picture-tools.hwpx"
    create_document(str(target))

    inserted = insert_picture(
        str(target),
        PNG_1X1_B64,
        image_format="png",
        width=11111,
        height=22222,
    )

    assert inserted["openSafety"]["ok"] is True
    assert inserted["verificationReport"]["openSafety"]["ok"] is True
    assert inserted["idIntegrity"]["ok"] is True
    assert inserted["picture"]["binaryItemIDRef"] == "BIN0001"

    document = open_doc(str(target))
    assert document.package.has_part("BinData/BIN0001.png")
    assert any(
        item.get("id") == "BIN0001" for item in document.package._manifest_items()
    )

    replaced = replace_picture(str(target), PNG_1X1_ALT_B64, image_format="png")

    assert replaced["openSafety"]["ok"] is True
    assert replaced["verificationReport"]["openSafety"]["ok"] is True
    assert replaced["idIntegrity"]["ok"] is True
    assert replaced["replacement"]["geometryPreserved"] is True
    assert replaced["replacement"]["old_binaryItemIDRef"] == "BIN0001"
    assert replaced["replacement"]["new_binaryItemIDRef"] == "BIN0002"
    assert replaced["replacement"]["removedOldImage"] is True

    refreshed = open_doc(str(target))
    assert not refreshed.package.has_part("BinData/BIN0001.png")
    assert refreshed.package.has_part("BinData/BIN0002.png")
    assert refreshed.media.picture_references()[0].binary_item_id_ref == "BIN0002"


def test_replace_picture_accepts_workspace_image_file(tmp_path: Path):
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    valid_png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )

    target = tmp_path / "picture-file.hwpx"
    image = tmp_path / "replacement.png"
    image.write_bytes(valid_png)
    create_document(str(target))
    insert_picture(str(target), PNG_1X1_B64, image_format="png", width=11111, height=22222)

    result = replace_picture(str(target), image_filename=str(image), image_format="png")
    assert result["openSafety"]["ok"] is True
    assert result["replacement"]["geometryPreserved"] is True
    with open_doc(str(target)) as document:
        ref = document.media.picture_references()[0]
        assert (ref.width, ref.height) == (11111, 22222)

    with pytest.raises(ValueError, match="exactly one"):
        replace_picture(str(target), PNG_1X1_B64, image_filename=str(image))
    with pytest.raises(ValueError, match="exactly one"):
        replace_picture(str(target))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(ValueError, match="does not match"):
        replace_picture(str(target), image_filename=str(bad))
    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="incomplete"):
        replace_picture(str(target), image_filename=str(truncated))
    oversized = tmp_path / "oversized.png"
    with oversized.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        stream.truncate(20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="20 MiB"):
        replace_picture(str(target), image_filename=str(oversized))


def test_replace_picture_file_obeys_workspace_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import base64
    import json

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(base64.b64decode(PNG_1X1_ALT_B64))
    target = workspace / "picture.hwpx"
    create_document(str(target))
    insert_picture(str(target), PNG_1X1_B64)
    link = workspace / "linked.png"
    link.symlink_to(outside)
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(workspace)]))

    with pytest.raises(WorkspacePathError):
        replace_picture("picture.hwpx", image_filename=str(outside))
    with pytest.raises(WorkspacePathError):
        replace_picture("picture.hwpx", image_filename="linked.png")


def test_byte_preserving_patch_updates_paragraph_with_open_safety(tmp_path: Path):
    target = tmp_path / "patch.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    before = target.read_bytes()

    result = byte_preserving_patch(
        str(target),
        [
            {
                "sectionPath": "Contents/section0.xml",
                "paragraphIndex": added["paragraph_index"],
                "text": "패치본문",
            }
        ],
    )

    assert result["skipped"] == []
    assert result["changedParts"] == ["Contents/section0.xml"]
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["openSafety"]["ok"] is True
    assert result["verificationReport"]["filePath"] == str(target)
    backup = target.with_suffix(target.suffix + ".bak")
    assert result["verificationReport"]["backup"]["created"] is True
    assert result["verificationReport"]["backup"]["path"] == str(backup)
    assert backup.read_bytes() == before
    assert result["verificationReport"]["semanticDiff"]["changed"] is True
    assert "패치본문" in get_document_text(str(target))["text"]

    undo = server_module.undo_last_edit(str(target))
    assert undo["restored"] is True
    assert target.read_bytes() == before


def test_byte_preserving_patch_skips_unsupported_without_mutating(tmp_path: Path):
    target = tmp_path / "patch-skip.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    before = target.read_bytes()
    backups_before = {
        item.name: item.read_bytes()
        for item in tmp_path.glob("patch-skip.hwpx.bak*")
    }

    result = byte_preserving_patch(
        str(target),
        [
            {
                "sectionPath": "Contents/section0.xml",
                "paragraphIndex": added["paragraph_index"],
                "text": "첫 줄\n둘째 줄",
            }
        ],
    )

    assert result["skipped"][0]["reason"] == "line break insertion is unsupported"
    assert target.read_bytes() == before
    assert result["verificationReport"]["ok"] is False
    assert {
        item.name: item.read_bytes()
        for item in tmp_path.glob("patch-skip.hwpx.bak*")
    } == backups_before


def test_byte_preserving_patch_skip_does_not_create_missing_output_parent(
    tmp_path: Path,
) -> None:
    target = tmp_path / "patch-skip-missing-parent.hwpx"
    output = tmp_path / "missing" / "nested" / "patched.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")

    result = byte_preserving_patch(
        str(target),
        [
            {
                "sectionPath": "Contents/section0.xml",
                "paragraphIndex": added["paragraph_index"],
                "text": "첫 줄\n둘째 줄",
            }
        ],
        output=str(output),
    )

    assert result["skipped"][0]["reason"] == "line break insertion is unsupported"
    assert not output.parent.exists()


def test_byte_preserving_patch_failure_does_not_create_missing_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-fail-missing-parent.hwpx"
    output = tmp_path / "missing-failure" / "nested" / "patched.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    original_report = transactions_module.build_hwpx_verification_report

    def reject_candidate(source, *args, **kwargs):
        if isinstance(source, bytes) and kwargs.get("file_path") == output:
            return {
                "openSafety": {
                    "ok": False,
                    "summary": "forced candidate verification failure",
                }
            }
        return original_report(source, *args, **kwargs)

    monkeypatch.setattr(
        transactions_module,
        "build_hwpx_verification_report",
        reject_candidate,
    )

    with pytest.raises(RuntimeError, match="failed open-safety"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "검증 실패",
                }
            ],
            output=str(output),
        )

    assert not output.parent.exists()


def test_byte_preserving_patch_postpublication_failure_cleans_owned_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-clean-parent.hwpx"
    output = tmp_path / "owned-parent" / "nested" / "patched.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    original_read = storage.read_guarded_bytes
    output_publication = None

    def record_publication(guard, data, **kwargs):
        nonlocal output_publication
        publication = original_publish(guard, data, **kwargs)
        if publication.path == output:
            output_publication = publication
        return publication

    def fail_final_claim(guard):
        if guard is output_publication:
            raise RuntimeError("forced post-publication failure")
        return original_read(guard)

    monkeypatch.setattr(storage, "atomic_publish_bytes", record_publication)
    monkeypatch.setattr(storage, "read_guarded_bytes", fail_final_claim)

    with pytest.raises(RuntimeError, match="post-publication"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시 후 실패",
                }
            ],
            output=str(output),
        )

    assert output_publication is not None
    assert not output.exists()
    assert not output.parent.exists()


def test_specialized_failure_does_not_create_missing_output_parent(
    tmp_path: Path,
) -> None:
    target = tmp_path / "table-op-source.hwpx"
    output = tmp_path / "specialized-missing" / "nested" / "output.hwpx"
    _create_form_document(target)

    result = server_module.apply_table_ops(
        str(target),
        [{"op": "delete_row", "table_index": 9999, "row": 0}],
        output=str(output),
    )

    assert result["ok"] is False
    assert result["skipped"]
    assert not output.parent.exists()


def test_byte_preserving_patch_rejects_parent_swap_without_leaking_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    documents = workspace / "documents"
    documents.mkdir(parents=True)
    target = documents / "source.hwpx"
    output = documents / "patched.hwpx"
    outside = workspace / "outside"
    outside.mkdir()
    create_document(str(target))
    added = add_paragraph(str(target), "원문")

    storage = server_module._OPS.storage
    original_atomic_publish = storage.atomic_publish_bytes
    created_temps: list[Path] = []
    original_mkstemp = transactions_module.tempfile.mkstemp

    def tracked_mkstemp(*args, **kwargs):
        descriptor, name = original_mkstemp(*args, **kwargs)
        created_temps.append(Path(name))
        return descriptor, name

    def swap_parent_then_publish(guard, data, **kwargs):
        moved_documents = workspace / "moved-documents"
        documents.rename(moved_documents)
        documents.symlink_to(outside, target_is_directory=True)
        return original_atomic_publish(guard, data, **kwargs)

    monkeypatch.setattr(transactions_module.tempfile, "mkstemp", tracked_mkstemp)
    monkeypatch.setattr(storage, "atomic_publish_bytes", swap_parent_then_publish)

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "외부로 나가면 안 됨",
                }
            ],
            output=str(output),
        )

    moved_documents = workspace / "moved-documents"
    assert "원문" in get_document_text(str(moved_documents / target.name))["text"]
    assert not (outside / output.name).exists()
    assert list(outside.glob(f".{output.stem}.*")) == []
    assert list(moved_documents.glob(f".{output.stem}.*")) == []
    assert created_temps == []


def test_byte_preserving_patch_rejects_same_bytes_prepublication_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-race.hwpx"
    replacement = tmp_path / "external.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    before = target.read_bytes()
    original_inode = target.stat().st_ino
    original_patch = hwpx_patch_module.paragraph_patch

    def replace_after_patch(*args, **kwargs):
        result = original_patch(*args, **kwargs)
        replacement.write_bytes(before)
        replacement.chmod(target.stat().st_mode & 0o777)
        os.replace(replacement, target)
        return result

    monkeypatch.setattr(hwpx_patch_module, "paragraph_patch", replace_after_patch)

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "패치되면 안 됨",
                }
            ],
        )

    assert target.stat().st_ino != original_inode
    assert target.read_bytes() == before
    assert "패치되면 안 됨" not in get_document_text(str(target))["text"]


def test_byte_preserving_patch_never_claims_replaced_published_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-post-race.hwpx"
    replacement = tmp_path / "external.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    backup = target.with_suffix(target.suffix + ".bak")
    backup_before = backup.read_bytes()
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    original_read = storage.read_guarded_bytes
    target_publication = None
    replaced = False

    def record_target_publication(guard, data, **kwargs):
        nonlocal target_publication
        publication = original_publish(guard, data, **kwargs)
        if publication.path == target:
            target_publication = publication
        return publication

    def replace_before_final_claim(guard):
        nonlocal replaced
        if guard is target_publication and not replaced:
            replacement.write_bytes(target.read_bytes())
            replacement.chmod(target.stat().st_mode & 0o777)
            os.replace(replacement, target)
            replaced = True
        return original_read(guard)

    monkeypatch.setattr(storage, "atomic_publish_bytes", record_target_publication)
    monkeypatch.setattr(storage, "read_guarded_bytes", replace_before_final_claim)

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "외부 소유 후보",
                }
            ],
        )

    assert replaced is True
    assert "외부 소유 후보" in get_document_text(str(target))["text"]
    assert backup.read_bytes() == backup_before
    target_recovery = _recovery_files(target, "rollback-recovery")
    assert len(target_recovery) == 1
    assert target_recovery[0].read_bytes() == target_before


@pytest.mark.skipif(os.name == "nt", reason="symlink setup requires POSIX")
def test_byte_preserving_patch_rejects_backup_symlink_before_publication(
    tmp_path: Path,
) -> None:
    target = tmp_path / "patch-backup-symlink.hwpx"
    outside_staging = tmp_path / "outside.hwpx"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-patch.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    create_document(str(outside_staging))
    add_paragraph(str(outside_staging), "외부 백업")
    os.replace(outside_staging, outside)
    target_before = target.read_bytes()
    outside_before = outside.read_bytes()
    backup = target.with_suffix(target.suffix + ".bak")
    backup.unlink()
    backup.symlink_to(outside)

    try:
        with pytest.raises(WorkspacePathError):
            byte_preserving_patch(
                str(target),
                [
                    {
                        "sectionPath": "Contents/section0.xml",
                        "paragraphIndex": added["paragraph_index"],
                        "text": "게시되면 안 됨",
                    }
                ],
            )

        assert target.read_bytes() == target_before
        assert outside.read_bytes() == outside_before
        assert backup.is_symlink()
    finally:
        outside.unlink(missing_ok=True)


def test_byte_preserving_patch_never_claims_replaced_backup_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-backup-race.hwpx"
    replacement = tmp_path / "external-backup.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    original_diff = server_module._OPS._services.save._semantic_diff_bytes
    replaced = False

    def replace_backup_after_diff(before: bytes, after: bytes) -> dict:
        nonlocal replaced
        report = original_diff(before, after)
        backup = target.with_suffix(target.suffix + ".bak")
        replacement.write_bytes(backup.read_bytes())
        replacement.chmod(backup.stat().st_mode & 0o777)
        os.replace(replacement, backup)
        replaced = True
        return report

    monkeypatch.setattr(
        server_module._OPS._services.save,
        "_semantic_diff_bytes",
        replace_backup_after_diff,
    )

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "성공으로 보고되면 안 됨",
                }
            ],
        )

    assert replaced is True
    assert target.read_bytes() == target_before
    assert "성공으로 보고되면 안 됨" not in get_document_text(str(target))["text"]


def test_byte_preserving_patch_rolls_back_owned_sidecars_and_preserves_external(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-sidecar-rollback.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()

    def document_bytes(name: str, text: str) -> bytes:
        staging = tmp_path / name
        create_document(str(staging))
        add_paragraph(str(staging), text)
        payload = staging.read_bytes()
        staging.unlink()
        for backup in tmp_path.glob(f"{name}.bak*"):
            backup.unlink()
        return payload

    sidecars = [
        target.with_suffix(target.suffix + ".bak"),
        target.with_suffix(target.suffix + ".bak.1"),
        target.with_suffix(target.suffix + ".bak.2"),
        target.with_suffix(target.suffix + ".bak.3"),
        target.with_suffix(target.suffix + ".bak.4"),
        target.with_suffix(target.suffix + ".bak.5"),
    ]
    initial_payloads = {
        sidecars[0]: document_bytes("sidecar-0.hwpx", "backup zero"),
        sidecars[1]: document_bytes("sidecar-1.hwpx", "backup one"),
        sidecars[3]: document_bytes("sidecar-3.hwpx", "backup three"),
        sidecars[5]: document_bytes("sidecar-5.hwpx", "backup five"),
    }
    for sidecar in sidecars:
        sidecar.unlink(missing_ok=True)
    for sidecar, payload in initial_payloads.items():
        sidecar.write_bytes(payload)
    external_payload = document_bytes("external-sidecar.hwpx", "external owner")
    external_staging = tmp_path / "external-sidecar-replacement.hwpx"
    original_diff = server_module._OPS._services.save._semantic_diff_bytes
    replaced = False

    def replace_rotated_sidecar(before: bytes, after: bytes) -> dict:
        nonlocal replaced
        report = original_diff(before, after)
        external_staging.write_bytes(external_payload)
        external_staging.chmod(sidecars[2].stat().st_mode & 0o777)
        os.replace(external_staging, sidecars[2])
        replaced = True
        return report

    monkeypatch.setattr(
        server_module._OPS._services.save,
        "_semantic_diff_bytes",
        replace_rotated_sidecar,
    )

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "성공하면 안 됨",
                }
            ],
        )

    assert replaced is True
    assert target.read_bytes() == target_before
    assert sidecars[2].read_bytes() == external_payload
    for sidecar in (sidecars[0], sidecars[1], sidecars[3], sidecars[5]):
        assert sidecar.read_bytes() == initial_payloads[sidecar]
    assert not sidecars[4].exists()


def test_byte_preserving_patch_partial_rotation_restores_owned_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-partial-rotation.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    backup = target.with_suffix(target.suffix + ".bak")
    backup_one = target.with_suffix(target.suffix + ".bak.1")
    backup_two = target.with_suffix(target.suffix + ".bak.2")
    backup_before = backup.read_bytes()
    backup_one.write_bytes(backup_before)
    backup_one_before = backup_one.read_bytes()
    backup_two.unlink(missing_ok=True)
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes

    def fail_second_sidecar(guard, data, **kwargs):
        if guard.path == backup_one:
            raise RuntimeError("forced partial rotation failure")
        return original_publish(guard, data, **kwargs)

    monkeypatch.setattr(storage, "atomic_publish_bytes", fail_second_sidecar)

    with pytest.raises(RuntimeError, match="partial rotation"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    assert target.read_bytes() == target_before
    assert backup.read_bytes() == backup_before
    assert backup_one.read_bytes() == backup_one_before
    assert not backup_two.exists()


def test_byte_preserving_patch_rotates_gap_chain_exactly(
    tmp_path: Path,
) -> None:
    target = tmp_path / "patch-gap-chain.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    sidecars = [
        target.with_suffix(target.suffix + ".bak"),
        target.with_suffix(target.suffix + ".bak.1"),
        target.with_suffix(target.suffix + ".bak.2"),
        target.with_suffix(target.suffix + ".bak.3"),
        target.with_suffix(target.suffix + ".bak.4"),
        target.with_suffix(target.suffix + ".bak.5"),
    ]
    initial = {
        sidecars[0]: b"b0",
        sidecars[1]: b"b1",
        sidecars[3]: b"b3",
        sidecars[5]: b"b5",
    }
    for sidecar in sidecars:
        sidecar.unlink(missing_ok=True)
    for sidecar, data in initial.items():
        sidecar.write_bytes(data)

    result = byte_preserving_patch(
        str(target),
        [
            {
                "sectionPath": "Contents/section0.xml",
                "paragraphIndex": added["paragraph_index"],
                "text": "수정문",
            }
        ],
    )

    assert sidecars[0].read_bytes() == target_before
    assert sidecars[1].read_bytes() == b"b0"
    assert sidecars[2].read_bytes() == b"b1"
    assert not sidecars[3].exists()
    assert sidecars[4].read_bytes() == b"b3"
    assert not sidecars[5].exists()
    assert result["verificationReport"]["backup"]["rotatedPaths"] == [
        str(sidecars[4]),
        str(sidecars[2]),
        str(sidecars[1]),
    ]
    assert not list(
        tmp_path.glob(".*.rollback-recovery.*.recovery")
    )


def test_gap_rotation_failure_restores_deletions_and_preserves_external_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-gap-chain-race.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    sidecars = [
        target.with_suffix(target.suffix + ".bak"),
        target.with_suffix(target.suffix + ".bak.1"),
        target.with_suffix(target.suffix + ".bak.2"),
        target.with_suffix(target.suffix + ".bak.3"),
        target.with_suffix(target.suffix + ".bak.4"),
        target.with_suffix(target.suffix + ".bak.5"),
    ]
    initial = {
        sidecars[0]: b"b0",
        sidecars[1]: b"b1",
        sidecars[3]: b"b3",
        sidecars[5]: b"b5",
    }
    for sidecar in sidecars:
        sidecar.unlink(missing_ok=True)
    for sidecar, data in initial.items():
        sidecar.write_bytes(data)
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    external = b"external sidecar owner"
    raced = False

    def fail_after_gap_deletions(guard, data, **kwargs):
        nonlocal raced
        if guard.path == sidecars[2]:
            assert not sidecars[3].exists()
            sidecars[3].write_bytes(external)
            raced = True
            raise RuntimeError("forced gap rotation failure")
        return original_publish(guard, data, **kwargs)

    monkeypatch.setattr(
        storage,
        "atomic_publish_bytes",
        fail_after_gap_deletions,
    )

    with pytest.raises(RuntimeError, match="gap rotation"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(sidecars[3], "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == target_before
    assert sidecars[0].read_bytes() == b"b0"
    assert sidecars[1].read_bytes() == b"b1"
    assert not sidecars[2].exists()
    assert sidecars[3].read_bytes() == external
    assert not sidecars[4].exists()
    assert sidecars[5].read_bytes() == b"b5"
    assert len(recovery) == 1
    assert recovery[0].read_bytes() == b"b3"


@pytest.mark.skipif(os.name == "nt", reason="descriptor deletion race is POSIX-only")
def test_gap_rotation_deletion_claim_loss_preserves_oldest_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-gap-delete-claim-loss.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    sidecars = [
        target.with_suffix(target.suffix + ".bak"),
        target.with_suffix(target.suffix + ".bak.1"),
        target.with_suffix(target.suffix + ".bak.2"),
        target.with_suffix(target.suffix + ".bak.3"),
        target.with_suffix(target.suffix + ".bak.4"),
        target.with_suffix(target.suffix + ".bak.5"),
    ]
    initial = {
        sidecars[0]: b"b0",
        sidecars[1]: b"b1",
        sidecars[3]: b"b3",
        sidecars[5]: b"b5",
    }
    for sidecar in sidecars:
        sidecar.unlink(missing_ok=True)
    for sidecar, data in initial.items():
        sidecar.write_bytes(data)
    original_rmdir = workspace_module.os.rmdir
    external = b"external oldest owner"
    raced = False

    def replace_after_sentinel_rmdir(path, *, dir_fd=None):
        nonlocal raced
        original_rmdir(path, dir_fd=dir_fd)
        if not raced and path == sidecars[5].name and dir_fd is not None:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(descriptor, external)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raced = True

    monkeypatch.setattr(workspace_module.os, "rmdir", replace_after_sentinel_rmdir)

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(sidecars[5], "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == target_before
    assert sidecars[5].read_bytes() == external
    assert any(path.read_bytes() == b"b5" for path in recovery)


def test_rotation_publish_then_claim_loss_preserves_overwritten_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-rotation-publish-claim-loss.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    backup_four = target.with_suffix(target.suffix + ".bak.4")
    backup_five = target.with_suffix(target.suffix + ".bak.5")
    backup_four.write_bytes(b"b4")
    backup_five.write_bytes(b"b5")
    external_staging = tmp_path / "rotation-external.staging"
    external = b"external rotation owner"
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    raced = False

    def publish_then_replace(guard, data, **kwargs):
        nonlocal raced
        publication = original_publish(guard, data, **kwargs)
        if not raced and guard.path == backup_five and data == b"b4":
            external_staging.write_bytes(external)
            os.replace(external_staging, backup_five)
            raced = True
            raise WorkspacePathError(
                "forced rotation publish claim loss",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return publication

    monkeypatch.setattr(storage, "atomic_publish_bytes", publish_then_replace)

    with pytest.raises(WorkspacePathError, match="claim loss"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(backup_five, "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == target_before
    assert backup_five.read_bytes() == external
    assert any(path.read_bytes() == b"b5" for path in recovery)


def test_byte_patch_target_publish_then_claim_loss_preserves_target_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-target-publish-claim-loss.hwpx"
    external = tmp_path / "patch-target-external.hwpx"
    external_staging = tmp_path / "patch-target-external.staging.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    create_document(str(external_staging))
    add_paragraph(str(external_staging), "external target owner")
    os.replace(external_staging, external)
    target_before = target.read_bytes()
    external_before = external.read_bytes()
    backup = target.with_suffix(target.suffix + ".bak")
    backup_before = backup.read_bytes()
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    raced = False

    def publish_then_replace(guard, data, **kwargs):
        nonlocal raced
        publication = original_publish(guard, data, **kwargs)
        if not raced and guard.path == target and data != target_before:
            os.replace(external, target)
            raced = True
            raise WorkspacePathError(
                "forced target publish claim loss",
                code="WORKSPACE_PATH_CHANGED",
                reason="output_target_changed",
            )
        return publication

    monkeypatch.setattr(storage, "atomic_publish_bytes", publish_then_replace)

    with pytest.raises(WorkspacePathError, match="claim loss"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(target, "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == external_before
    assert backup.read_bytes() == backup_before
    assert any(path.read_bytes() == target_before for path in recovery)


def test_byte_patch_restore_claim_loss_keeps_target_preimage_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-target-restore-claim-loss.hwpx"
    external = tmp_path / "patch-restore-external.hwpx"
    external_staging = tmp_path / "patch-restore-external.staging.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    create_document(str(external_staging))
    add_paragraph(str(external_staging), "external restore owner")
    os.replace(external_staging, external)
    target_before = target.read_bytes()
    external_before = external.read_bytes()
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    original_read = storage.read_guarded_bytes
    target_publication = None
    raced = False

    def replace_after_target_restore(guard, data, **kwargs):
        nonlocal raced, target_publication
        publication = original_publish(guard, data, **kwargs)
        if guard.path == target:
            if data == target_before:
                if not raced:
                    os.replace(external, target)
                    raced = True
            else:
                target_publication = publication
        return publication

    def fail_final_target_claim(guard):
        if guard is target_publication:
            raise RuntimeError("forced byte patch evidence failure")
        return original_read(guard)

    monkeypatch.setattr(
        storage,
        "atomic_publish_bytes",
        replace_after_target_restore,
    )
    monkeypatch.setattr(
        storage,
        "read_guarded_bytes",
        fail_final_target_claim,
    )

    with pytest.raises(RuntimeError, match="patch evidence"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(target, "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == external_before
    assert any(path.read_bytes() == target_before for path in recovery)


def test_backup_chain_restore_claim_loss_keeps_all_preimages_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-backup-chain-restore-race.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    target_before = target.read_bytes()
    backup = target.with_suffix(target.suffix + ".bak")
    backup_one = target.with_suffix(target.suffix + ".bak.1")
    backup.write_bytes(b"A")
    backup_one.write_bytes(b"B")
    storage = server_module._OPS.storage
    original_publish = storage.atomic_publish_bytes
    original_read = storage.read_guarded_bytes
    target_publication = None
    external = b"external backup owner"
    raced = False

    def replace_after_first_backup_restore(guard, data, **kwargs):
        nonlocal raced, target_publication
        publication = original_publish(guard, data, **kwargs)
        if guard.path == target:
            target_publication = publication
        if not raced and guard.path == backup and data == b"A":
            guard.path.write_bytes(external)
            raced = True
        return publication

    def fail_final_target_claim(guard):
        if guard is target_publication:
            raise RuntimeError("forced byte patch evidence failure")
        return original_read(guard)

    monkeypatch.setattr(
        storage,
        "atomic_publish_bytes",
        replace_after_first_backup_restore,
    )
    monkeypatch.setattr(
        storage,
        "read_guarded_bytes",
        fail_final_target_claim,
    )

    with pytest.raises(RuntimeError, match="patch evidence"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(backup, "rollback-recovery")
    assert raced is True
    assert target.read_bytes() == target_before
    assert backup.read_bytes() == external
    assert backup_one.read_bytes() == b"B"
    assert any(path.read_bytes() == b"A" for path in recovery)


def test_byte_patch_recovery_preflight_failure_does_not_mutate_target_or_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-recovery-preflight-failure.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    backup = target.with_suffix(target.suffix + ".bak")
    target_before = target.read_bytes()
    backup_before = backup.read_bytes()

    def fail_recovery(*args, **kwargs):
        raise RuntimeError("forced recovery storage failure")

    monkeypatch.setattr(
        server_module._OPS._services.save,
        "_publish_exact_recovery",
        fail_recovery,
    )

    with pytest.raises(RuntimeError, match="could not be preserved"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "게시되면 안 됨",
                }
            ],
        )

    assert target.read_bytes() == target_before
    assert backup.read_bytes() == backup_before


def test_byte_patch_post_cleanup_claim_loss_republishes_preimages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "patch-post-cleanup-claim-loss.hwpx"
    external = tmp_path / "patch-post-cleanup-external.hwpx"
    external_staging = tmp_path / "patch-post-cleanup-staging.hwpx"
    create_document(str(target))
    added = add_paragraph(str(target), "원문")
    create_document(str(external_staging))
    add_paragraph(str(external_staging), "external cleanup owner")
    os.replace(external_staging, external)
    target_before = target.read_bytes()
    external_before = external.read_bytes()
    storage = server_module._OPS.storage
    original_remove = storage.remove_guarded_output
    replaced = False

    def replace_target_after_first_cleanup(guard) -> None:
        nonlocal replaced
        original_remove(guard)
        if not replaced and ".rollback-recovery." in guard.path.name:
            os.replace(external, target)
            replaced = True

    monkeypatch.setattr(
        storage,
        "remove_guarded_output",
        replace_target_after_first_cleanup,
    )

    with pytest.raises(WorkspacePathError, match="changed"):
        byte_preserving_patch(
            str(target),
            [
                {
                    "sectionPath": "Contents/section0.xml",
                    "paragraphIndex": added["paragraph_index"],
                    "text": "성공으로 보고되면 안 됨",
                }
            ],
        )

    recovery = _recovery_files(target, "rollback-recovery")
    assert replaced is True
    assert target.read_bytes() == external_before
    assert any(
        path.read_bytes() == target_before
        for path in recovery
    )


def test_add_heading(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_heading(str(target), "1장 서론", level=1)
    outline = get_document_outline(str(target))["outline"]

    assert any(item["level"] == 1 and "1장 서론" in item["text"] for item in outline)


def test_insert_paragraph(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_paragraph(str(target), "첫 문단")
    add_paragraph(str(target), "둘 문단")
    add_paragraph(str(target), "셋 문단")

    insert_paragraph(str(target), 1, "삽입 문단")
    rows = get_paragraphs_text(str(target), 0, 6)["paragraphs"]
    texts = [entry["text"] for entry in rows]

    assert texts.index("삽입 문단") < texts.index("둘 문단")


def test_delete_paragraph(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_paragraph(str(target), "삭제 대상")
    before = len(get_paragraphs_text(str(target))["paragraphs"])
    result = delete_paragraph(str(target), 1)
    after = len(get_paragraphs_text(str(target))["paragraphs"])

    assert result["remaining_paragraphs"] == after
    assert after == before - 1
    texts = [entry["text"] for entry in get_paragraphs_text(str(target))["paragraphs"]]
    assert "삭제 대상" not in texts


def test_delete_only_paragraph_clears_layout_cache(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))
    doc = open_doc(str(target))
    paragraph = doc.paragraphs[0]
    paragraph.runs[0].text = "삭제 대상"
    ET.SubElement(paragraph.element, f"{HP}lineSegArray")
    save_doc(doc, str(target))

    result = delete_paragraph(str(target), 0)
    doc = open_doc(str(target))

    assert result["remaining_paragraphs"] == 1
    assert doc.paragraphs[0].text == ""
    assert doc.paragraphs[0].element.find(f"{HP}lineSegArray") is None


def test_add_table(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_table(str(target), 2, 3, [["A", "B", "C"], ["1", "2", "3"]])
    table = get_table_text(str(target), table_index=0)

    assert table["data"][0] == ["A", "B", "C"]


def test_add_table_after_heading_uses_a_neutral_anchor(tmp_path: Path):
    target = tmp_path / "heading-then-table.hwpx"
    create_document(str(target))
    add_heading(str(target), "번호 제목", level=1)

    result = add_table(str(target), 1, 1, [["표 내용"]])
    reopened = open_doc(str(target))
    table_anchor = next(
        paragraph for paragraph in reopened.paragraphs if paragraph.tables
    )

    assert table_anchor.para_pr_id_ref == "0"
    assert table_anchor.style_id_ref == "0"
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["openSafety"]["ok"] is True


def test_set_table_cell_text(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_table(str(target), 1, 1, [["초기값"]])
    set_table_cell_text(str(target), 0, 0, 0, "변경값")
    table = get_table_text(str(target), 0)

    assert table["data"][0][0] == "변경값"


def test_set_table_cell_text_preserves_char_pr_and_can_split_paragraphs(tmp_path: Path):
    target = tmp_path / "code.hwpx"
    create_document(str(target))
    add_table(str(target), 1, 1, [["old code"]])

    doc = open_doc(str(target))
    cell = doc.paragraphs[1].tables[0].cell(0, 0)
    paragraph = cell.paragraphs[0]
    paragraph.runs[0].char_pr_id_ref = "13"
    paragraph.add_run(" tail", char_pr_id_ref="21")
    server_module.save_doc(doc, str(target))

    set_table_cell_text(str(target), 0, 0, 0, "new code")
    refreshed = open_doc(str(target))
    refreshed_cell = refreshed.paragraphs[1].tables[0].cell(0, 0)
    refreshed_paragraph = refreshed_cell.paragraphs[0]

    assert refreshed_paragraph.runs[0].char_pr_id_ref == "13"
    assert refreshed_paragraph.runs[0].text == "new code"
    assert refreshed_paragraph.runs[1].char_pr_id_ref == "21"
    assert refreshed_paragraph.runs[1].text == ""

    set_table_cell_text(
        str(target), 0, 0, 0, "line one\nline two", split_paragraphs=True
    )
    split_cell = open_doc(str(target)).paragraphs[1].tables[0].cell(0, 0)
    assert [paragraph.text for paragraph in split_cell.paragraphs] == [
        "line one",
        "line two",
    ]
    assert [
        paragraph.runs[0].char_pr_id_ref for paragraph in split_cell.paragraphs
    ] == ["13", "13"]


def test_get_table_map_returns_stable_json_shape(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    result = get_table_map(str(target))

    assert {"tables", "count", "document_revision", "documentWarnings"}.issubset(result)
    assert result["count"] == 1
    assert result["document_revision"].startswith("sha256:")
    assert result["documentWarnings"] == []
    entry = result["tables"][0]
    assert set(entry) == {
        "table_index",
        "paragraph_index",
        "location",
        "rows",
        "cols",
        "caption_text",
        "preceding_paragraph_text",
        "header_text",
        "first_row_preview",
        "cells",
        "is_empty",
    }
    assert entry["table_index"] == 0
    assert entry["location"] == {
        "kind": "body_paragraph",
        "paragraph_index": entry["paragraph_index"],
    }
    assert entry["rows"] == 3
    assert entry["cols"] == 2
    assert entry["first_row_preview"] == ["성명:", ""]
    assert entry["caption_text"] == ""
    assert entry["preceding_paragraph_text"] == "기본정보"
    assert entry["header_text"] == "기본정보"
    assert entry["cells"][0]["paragraphs"][0]["location"] == {
        "kind": "table_cell_paragraph",
        "table_index": 0,
        "row": 0,
        "col": 0,
        "cell_paragraph_index": 0,
    }


def test_table_map_location_can_drive_text_lookup_and_memo(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    cell_location = get_table_map(str(target))["tables"][0]["cells"][0]["paragraphs"][
        0
    ]["location"]
    text_result = get_paragraph_text(str(target), location=cell_location)
    memo_result = add_memo(str(target), text="라벨 확인", location=cell_location)

    assert text_result["text"] == "성명:"
    assert text_result["location"] == cell_location
    assert memo_result["memo_added"] is True
    assert memo_result["location"] == cell_location
    assert len(open_doc(str(target)).notes.memos) == 1


def test_replace_in_paragraph_uses_location_and_preserves_run_char_pr(tmp_path: Path):
    target = tmp_path / "code-cell.hwpx"
    create_document(str(target))
    add_table(str(target), 1, 1, [["REQUIRED_DATA_FILES = []"]])

    cell_location = get_table_map(str(target))["tables"][0]["cells"][0]["paragraphs"][
        0
    ]["location"]
    doc = open_doc(str(target))
    run = doc.paragraphs[1].tables[0].cell(0, 0).paragraphs[0].runs[0]
    run.char_pr_id_ref = "31"
    server_module.save_doc(doc, str(target))

    result = replace_in_paragraph(
        str(target),
        "[]",
        "['인천항_물동량.csv']",
        location=cell_location,
    )
    refreshed = open_doc(str(target))
    refreshed_run = refreshed.paragraphs[1].tables[0].cell(0, 0).paragraphs[0].runs[0]

    assert result["replaced_count"] == 1
    assert result["location"] == cell_location
    assert refreshed_run.char_pr_id_ref == "31"
    assert refreshed_run.text == "REQUIRED_DATA_FILES = ['인천항_물동량.csv']"


def test_replace_by_anchor_targets_exact_match_position(tmp_path: Path):
    target = tmp_path / "repeated-code.hwpx"
    create_document(str(target))
    add_paragraph(str(target), "TOKEN = 1; TOKEN = 2")

    doc = open_doc(str(target))
    paragraph = doc.paragraphs[1]
    paragraph.runs[0].char_pr_id_ref = "41"
    server_module.save_doc(doc, str(target))

    matches = find_text(str(target), "TOKEN")
    result = replace_by_anchor(
        str(target), matches["matches"][1]["anchor"], "TOKEN", "VALUE"
    )
    refreshed = open_doc(str(target))

    assert result["replaced_count"] == 1
    assert refreshed.paragraphs[1].text == "TOKEN = 1; VALUE = 2"
    assert refreshed.paragraphs[1].runs[0].char_pr_id_ref == "41"


def test_find_cell_by_label_handles_label_normalization(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    plain = find_cell_by_label(str(target), "성명")
    normalized = find_cell_by_label(str(target), "성명:")

    assert plain["count"] == 1
    assert normalized["count"] == 1
    assert plain["matches"] == normalized["matches"]
    assert plain["matches"][0]["label_cell"]["text"] == "성명:"
    assert plain["matches"][0]["target_cell"] == {"row": 0, "col": 1, "text": ""}


def test_find_cell_by_label_rejects_unsupported_direction(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    with pytest.raises(ValueError, match="direction must be one of: right, down"):
        find_cell_by_label(str(target), "성명", direction="left")


def test_resolve_path_allows_absolute_paths_inside_sandbox_and_guides_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
    inside = sandbox / "doc.hwpx"
    outside = tmp_path / "outside.hwpx"
    monkeypatch.delenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", raising=False)
    monkeypatch.delenv("HWPX_MCP_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HWPX_MCP_SANDBOX_ROOT", str(sandbox))

    assert resolve_path(str(inside)) == str(inside)
    with pytest.raises(PermissionError, match="outside the authorized"):
        resolve_path(str(outside))


def test_copy_document_rejects_unsafe_hwpx_source_and_preserves_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe-source.hwpx"
    destination = tmp_path / "safe-destination.hwpx"
    create_document(str(source))
    create_document(str(destination))
    original_destination = destination.read_bytes()
    stale_section = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' "
        "xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'>"
        "<hp:p id='1' paraPrIDRef='0' styleIDRef='0' pageBreak='0' columnBreak='0' merged='0'>"
        "<hp:run charPrIDRef='0'><hp:t>Short</hp:t></hp:run>"
        "<hp:linesegarray><hp:lineseg textpos='40'/></hp:linesegarray>"
        "</hp:p></hs:sec>"
    ).encode("utf-8")
    _replace_zip_part(source, "Contents/section0.xml", stale_section)

    with pytest.raises(ValueError, match="source HWPX failed open-safety verification"):
        copy_document(str(source), str(destination))

    assert destination.read_bytes() == original_destination


def test_fill_by_path_applies_multiple_mappings_correctly(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    result = fill_by_path(
        str(target),
        {
            "성명 > right": "홍길동",
            "소속 > right": "AI연구소",
        },
    )

    assert result["applied_count"] == 2
    assert result["failed_count"] == 0

    table = get_table_text(str(target), 0)
    assert table["data"][0][1] == "홍길동"
    assert table["data"][1][1] == "AI연구소"


def test_fill_by_path_reports_ambiguous_label_as_failed_entry(tmp_path: Path):
    target = tmp_path / "ambiguous_form.hwpx"
    _create_ambiguous_form_document(target)

    result = fill_by_path(str(target), {"성명 > right": "홍길동"})

    assert result["applied"] == []
    assert result["applied_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed"] == [{"path": "성명 > right", "reason": "ambiguous label"}]


def test_fill_by_path_reports_out_of_bounds_path_as_failed_entry(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    result = fill_by_path(str(target), {"합계 > down > right": "초과"})

    assert result["applied"] == []
    assert result["applied_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed"] == [
        {"path": "합계 > down > right", "reason": "navigation out of bounds"}
    ]


def test_fill_by_path_saves_after_successful_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "saved_form.hwpx"
    _create_form_document(target)

    save_calls: list[str] = []
    from hwpx_automation.handlers import _shared as handler_shared

    original_save = handler_shared.save_doc

    def _tracking_save(doc, path: str, **kwargs) -> None:
        save_calls.append(path)
        original_save(doc, path, **kwargs)

    monkeypatch.setattr(handler_shared, "save_doc", _tracking_save)

    result = fill_by_path(str(target), {"성명 > right": "홍길동"})

    assert len(save_calls) == 1
    assert Path(save_calls[0]).resolve() == target.resolve()
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["filePath"] == str(target)
    assert get_table_text(str(target), 0)["data"][0][1] == "홍길동"


def test_fill_by_path_rejects_empty_mappings(tmp_path: Path):
    target = tmp_path / "form.hwpx"
    _create_form_document(target)

    with pytest.raises(ValueError, match="mappings must not be empty"):
        fill_by_path(str(target), {})


def test_add_and_remove_memo(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    add_paragraph(str(target), "메모 대상")
    original_text = open_doc(str(target)).paragraphs[1].text
    added = add_memo(str(target), 1, "검토 필요")
    assert len(open_doc(str(target)).notes.memos) == 1

    removed = remove_memo(str(target), 1)
    refreshed = open_doc(str(target))
    assert len(refreshed.notes.memos) == 0
    assert refreshed.paragraphs[1].text == original_text

    assert added["memo_added"] is True
    assert removed["memo_removed"] is True


def test_format_table_border_and_shading(tmp_path: Path):
    target = tmp_path / "table_fmt.hwpx"
    create_document(str(target))
    add_table(str(target), 2, 2, [["h1", "h2"], ["a", "b"]])

    whole = format_table(
        str(target), 0,
        border_type="DASH", border_color="#0000FF", border_width="0.4 mm",
    )
    assert whole["formatted"] is True
    assert whole["border_fill_id"]

    one_cell = format_table(str(target), 0, fill_color="#FFFF00", row=1, col=1)
    assert one_cell["border_fill_id"] != whole["border_fill_id"]

    doc = open_doc(str(target))
    HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
    cells = list(doc.sections[0].element.iter(f"{HP}tc"))
    ids = [c.get("borderFillIDRef") for c in cells]
    assert ids[:3] == [whole["border_fill_id"]] * 3
    assert ids[3] == one_cell["border_fill_id"]
    fills = {bf.get("id"): bf for header in doc.parts.headers for bf in header.element.iter(f"{HH}borderFill")}
    dash = fills[whole["border_fill_id"]]
    assert any(child.get("type") == "DASH" for child in dash)


def test_format_table_typed_refusals(tmp_path: Path):
    target = tmp_path / "table_fmt2.hwpx"
    create_document(str(target))
    add_table(str(target), 1, 1, [["x"]])

    with pytest.raises(ValueError):
        format_table(str(target), 0, border_type="ZIGZAG")
    with pytest.raises(ValueError):
        format_table(str(target), 0, border_type="DASH", row=0)


def test_add_page_break(tmp_path: Path):
    target = tmp_path / "test.hwpx"
    create_document(str(target))

    result = add_page_break(str(target))

    assert result["success"] is True


def test_list_available_documents(tmp_path: Path):
    create_document(str(tmp_path / "test1.hwpx"))
    create_document(str(tmp_path / "test2.hwpx"))

    result = list_available_documents(str(tmp_path))

    assert result["count"] == 2
    names = {entry["filename"] for entry in result["documents"]}
    assert {"test1.hwpx", "test2.hwpx"}.issubset(names)
