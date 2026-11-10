# SPDX-License-Identifier: Apache-2.0
"""Audit EFF-15: a write validates each distinct content once, backs up once.

One MCP write used to run the automation open-safety check four times (source
when opened, source for the transaction backup, source for the storage backup,
new bytes after save), copy the same ``.bak`` twice and hash the whole tool
contract twice. The checks themselves are unchanged; only repeats on identical
bytes are answered from a content-addressed memo.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from hwpx import HwpxDocument

import hwpx_automation.storage as storage
import hwpx_automation.tool_contract as tool_contract
from hwpx_automation.server import add_paragraph, create_document, get_document_info


@pytest.fixture()
def counted(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts = {"safety": 0, "copy2": 0}
    real_compute = storage._compute_hwpx_open_safety_report
    real_copy2 = shutil.copy2

    def compute(source):
        counts["safety"] += 1
        return real_compute(source)

    def copy2(src, dst, *args, **kwargs):
        counts["copy2"] += 1
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(storage, "_compute_hwpx_open_safety_report", compute)
    monkeypatch.setattr(shutil, "copy2", copy2)
    storage.clear_open_safety_memo()
    return counts


def _document(path: Path, counts: dict[str, int] | None = None) -> None:
    create_document(str(path))
    storage.clear_open_safety_memo()
    if counts is not None:
        counts.update(safety=0, copy2=0)


def test_write_validates_source_once_and_new_bytes_once(tmp_path: Path, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)

    result = add_paragraph(str(target), "점검 문단")

    assert result.get("ok", True) is not False, result
    # 1 = the source as found, 2 = the bytes about to be published.
    assert counted["safety"] == 2
    assert counted["copy2"] == 1
    backup = target.with_suffix(".hwpx.bak")
    assert backup.exists()
    doc = HwpxDocument.open(str(target))
    try:
        assert doc.paragraphs[-1].text == "점검 문단"
    finally:
        doc.close()


def test_next_call_reuses_the_verdict_of_the_bytes_just_written(tmp_path: Path, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)
    add_paragraph(str(target), "하나")
    counted.update(safety=0, copy2=0)

    get_document_info(str(target))  # unchanged since the verified save
    assert counted["safety"] == 0

    add_paragraph(str(target), "둘")
    assert counted["safety"] == 1  # only the new bytes
    assert counted["copy2"] == 1


def test_changed_bytes_are_always_validated_again(tmp_path: Path, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)
    get_document_info(str(target))
    assert counted["safety"] == 1

    doc = HwpxDocument.open(str(target))
    doc.add_paragraph("밖에서 고친 문단")
    doc.save_to_path(str(target))
    doc.close()

    get_document_info(str(target))
    assert counted["safety"] == 2


def test_failing_verdict_is_never_remembered(tmp_path: Path, counted) -> None:
    broken = tmp_path / "broken.hwpx"
    broken.write_bytes(b"not a zip package")

    first = storage.build_hwpx_open_safety_report(broken)
    second = storage.build_hwpx_open_safety_report(broken)

    assert first["ok"] is False and second["ok"] is False
    assert counted["safety"] == 2
    with pytest.raises(RuntimeError, match="open-safety"):
        storage.require_hwpx_editor_open_safe(broken, role="audit")


def test_memo_is_keyed_on_the_validators(tmp_path: Path, monkeypatch, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)
    assert storage.build_hwpx_open_safety_report(target)["ok"] is True
    assert counted["safety"] == 1

    def refusing(_source):
        raise RuntimeError("validator replaced")

    monkeypatch.setattr(storage, "validate_package", refusing)
    report = storage.build_hwpx_open_safety_report(target)

    assert counted["safety"] == 2
    assert report["ok"] is False
    assert "validator replaced" in report["validatePackage"]["errors"][0]


def test_memo_returns_independent_copies(tmp_path: Path, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)
    first = storage.build_hwpx_open_safety_report(target)
    first["validatePackage"]["warnings"].append("mutated by a caller")
    second = storage.build_hwpx_open_safety_report(target)
    assert "mutated by a caller" not in second["validatePackage"]["warnings"]
    assert counted["safety"] == 1


def test_ensure_backup_skips_only_an_identical_backup(tmp_path: Path, counted) -> None:
    target = tmp_path / "doc.hwpx"
    _document(target, counted)
    local = storage.LocalDocumentStorage(base_directory=tmp_path, auto_backup=True)
    backup = target.with_suffix(".hwpx.bak")

    assert local.ensure_backup(target) == backup
    assert counted["copy2"] == 1
    assert local.ensure_backup(target) == backup
    assert counted["copy2"] == 1  # identical content: no second copy

    backup.write_bytes(b"stale backup")
    assert local.ensure_backup(target) == backup
    assert counted["copy2"] == 2
    assert backup.read_bytes() == target.read_bytes()


def test_contract_hash_is_computed_once_per_bound_registry(monkeypatch) -> None:
    import hwpx_automation.server  # noqa: F401 - binds the registry

    calls = {"n": 0}
    real_payload = tool_contract.contract_payload

    def payload():
        calls["n"] += 1
        return real_payload()

    monkeypatch.setattr(tool_contract, "contract_payload", payload)
    monkeypatch.setattr(tool_contract, "_CONTRACT_HASH_MEMO", None)
    first = tool_contract.contract_hash()
    assert [tool_contract.contract_hash() for _ in range(5)] == [first] * 5
    assert calls["n"] == 1

    # A different floor constant is a different contract: recomputed, different hash.
    monkeypatch.setattr(tool_contract, "MIN_SKILL_VERSION", "999.0.0")
    assert tool_contract.contract_hash() != first
    assert calls["n"] == 2
