"""Continuity gates on the pre-existing external edit-fidelity corpus."""

from __future__ import annotations
import hashlib
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
import pytest
from hwpx import HwpxDocument
from hwpx.quality import SavePipeline
from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands

FIXTURE = Path(__file__).parent / "fixtures/edit-fidelity/table.hwpx"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def request(tmp_path):
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    data = FIXTURE.read_bytes()
    source.write_bytes(data)
    output.write_bytes(data)
    with HwpxAgentDocument.open(source) as doc:
        target = next(
            r
            for r in doc.records
            if r.kind == "paragraph" and r.summary.get("text") == "국어"
        )
    return (
        source,
        output,
        {
            "schemaVersion": "hwpx.agent-batch/v1",
            "input": {"filename": str(source)},
            "output": {"filename": str(output), "overwrite": True},
            "expectedRevision": "sha256:" + hashlib.sha256(data).hexdigest(),
            "dryRun": False,
            "idempotencyKey": None,
            "quality": "transparent",
            "verificationRequirements": [
                "package",
                "reopen",
                "openSafety",
                "semanticDiff",
                "bytePreservation",
            ],
            "commands": [
                {
                    "commandId": "edit",
                    "op": "set",
                    "path": target.path,
                    "properties": {"text": "국어 (검토)"},
                }
            ],
        },
    )


def successor(data):
    with HwpxDocument.open(data) as doc:
        doc.add_paragraph("Concurrent saved revision")
        return doc.to_bytes()


@pytest.mark.parametrize("changed", ["source", "output"])
@pytest.mark.parametrize("seam", ["before_save", "during_quality"])
def test_late_user_save_is_preserved(changed, seam, tmp_path):
    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    latest = successor(before)

    def save():
        (source if changed == "source" else output).write_bytes(latest)

    def fault(stage, index):
        if seam == "before_save" and stage == "before_save":
            save()

    class RacingQuality(SavePipeline):
        def _check_well_formed(self, data, errors):
            if seam == "during_quality":
                save()
            return super()._check_well_formed(data, errors)

    result = apply_document_commands(
        batch, fault_injector=fault, save_pipeline=RacingQuality()
    )
    assert not result.ok, result.to_dict()
    assert source.read_bytes() == (latest if changed == "source" else before)
    assert output.read_bytes() == (latest if changed == "output" else before)


def corrupt(data, kind):
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buffer, "w") as dst:
        for item in src.infolist():
            value = src.read(item)
            if item.filename == (
                "Contents/header.xml"
                if kind == "shared_style"
                else "Contents/section0.xml"
            ):
                tree = ET.fromstring(value)
                if kind == "shared_style":
                    tree.find(".//{*}charPr").set("height", "3200")
                else:
                    target = next(
                        p
                        for p in tree.iter(HP + "p")
                        if "".join(
                            t.text or ""
                            for t in p.findall("./" + HP + "run/" + HP + "t")
                        )
                        == "이름"
                    )
                    if kind == "other_text":
                        target.find("./" + HP + "run/" + HP + "t").text = "Unexpected"
                    else:
                        target.set(
                            "paraPrIDRef",
                            "0" if target.get("paraPrIDRef") != "0" else "1",
                        )
                value = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
            dst.writestr(item, value)
    return buffer.getvalue()


@pytest.mark.parametrize("kind", ["other_text", "other_format", "shared_style"])
def test_non_target_serialization_damage_is_withheld(kind, tmp_path, monkeypatch):
    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    serialize = HwpxDocument.to_bytes

    def damaged(doc, *args, **kwargs):
        return corrupt(serialize(doc, *args, **kwargs), kind)

    monkeypatch.setattr(HwpxDocument, "to_bytes", damaged)
    result = apply_document_commands(batch)
    assert not result.ok, result.to_dict()
    assert source.read_bytes() == before and output.read_bytes() == before


def test_ordinary_edit_and_replay_keep_preconditions(tmp_path):
    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    batch["idempotencyKey"] = "same-request"
    store = {}
    result = apply_document_commands(batch, idempotency_store=store)
    assert result.ok, result.to_dict()
    committed = output.read_bytes()
    replay = apply_document_commands(batch, idempotency_store=store)
    assert replay.ok and replay.verification_report["idempotency"]["replayed"]
    assert source.read_bytes() == before and output.read_bytes() == committed


@pytest.mark.parametrize("change", ["source", "output"])
def test_post_publication_change_only_rolls_back_owned_candidate(
    change, tmp_path, monkeypatch
):
    from hwpx_automation.workspace import WorkspaceResolver

    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    latest = successor(before)
    publish = WorkspaceResolver.atomic_publish_bytes
    fired = False

    def race(self, guard, data, **kwargs):
        nonlocal fired
        token = publish(self, guard, data, **kwargs)
        if guard.path == output.resolve() and not fired:
            fired = True
            (source if change == "source" else output).write_bytes(latest)
        return token

    monkeypatch.setattr(WorkspaceResolver, "atomic_publish_bytes", race)
    result = apply_document_commands(batch)
    assert fired and not result.ok, result.to_dict()
    assert source.read_bytes() == (latest if change == "source" else before)
    assert output.read_bytes() == (latest if change == "output" else before)
    assert result.rolled_back is (change == "source")


@pytest.mark.parametrize(
    "case", ["dry_run", "in_place", "new_output", "missing_parent", "output_appears"]
)
def test_existing_output_modes_remain_bounded(case, tmp_path):
    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    if case == "dry_run":
        batch["dryRun"] = True
    if case == "in_place":
        output = source
        batch["output"]["filename"] = str(source)
    if case in ["new_output", "output_appears"]:
        output.unlink()
        batch["output"]["overwrite"] = False
    if case == "missing_parent":
        output = tmp_path / "new/deep/result.hwpx"
        batch["output"]["filename"] = str(output)
    latest = successor(before)

    def race(stage, index):
        if stage == "before_save" and case == "output_appears":
            output.write_bytes(latest)

    result = apply_document_commands(batch, fault_injector=race)
    if case == "output_appears":
        assert not result.ok and output.read_bytes() == latest
    else:
        assert result.ok, result.to_dict()
    if case == "dry_run":
        assert output.read_bytes() == before
    elif case != "output_appears":
        with HwpxAgentDocument.open(output) as document:
            assert (
                document.resolve_record(batch["commands"][0]["path"]).summary["text"]
                == "국어 (검토)"
            )
    if case != "in_place":
        assert source.read_bytes() == before


def test_unbound_custom_publisher_is_not_silently_replaced(tmp_path):
    source, output, batch = request(tmp_path)
    before = source.read_bytes()
    class CustomPublisher(SavePipeline):
        def _publish(self, *args, **kwargs):
            raise AssertionError("unbound publisher must not run")
    result = apply_document_commands(batch, save_pipeline=CustomPublisher())
    assert not result.ok and result.error.code == "unsupported_operation"
    assert source.read_bytes() == before and output.read_bytes() == before
