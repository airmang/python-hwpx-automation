# SPDX-License-Identifier: Apache-2.0
"""Audit EFF-17: one projection per text-only batch, one style lookup per id.

``apply_document_commands`` used to rebuild the whole semantic projection after
every command (N commands -> N+1 projections, about a second each on a
mid-size form). Reuse is limited to text-only ``set`` batches on existing
paragraphs, runs and cells; its results must equal the re-projecting path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from hwpx import HwpxDocument

from hwpx_automation.office.agent import HwpxAgentDocument, apply_document_commands
from hwpx_automation.office.agent import commands as commands_module


def _fixture(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.paragraphs[0].runs[0].text = "제목"
    doc.add_paragraph("본문 하나")
    doc.add_paragraph("본문 둘")
    holder = doc.add_paragraph("")
    table = holder.add_table(3, 3)
    for row in range(3):
        for col in range(3):
            table.set_cell_text(row, col, f"칸 {row}-{col}")
    table.merge_cells(0, 0, 0, 1)
    doc.add_paragraph("끝")
    doc.save_to_path(str(path))
    doc.close()


def _batch(source: Path, output: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.agent-batch/v1",
        "input": {"filename": str(source)},
        "output": {"filename": str(output), "overwrite": True},
        "commands": commands,
        "expectedRevision": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "idempotencyKey": None,
        "dryRun": False,
        "quality": "transparent",
        "verificationRequirements": ["package", "reopen", "openSafety", "semanticDiff"],
    }


def _records(path: Path, kind: str) -> list[Any]:
    with HwpxAgentDocument.open(path) as agent:
        return [record for record in agent.records if record.kind == kind]


def _count_projections(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counter = {"n": 0}
    original = HwpxAgentDocument.__init__

    def counting(self, *args: Any, **kwargs: Any) -> None:
        counter["n"] += 1
        original(self, *args, **kwargs)

    monkeypatch.setattr(HwpxAgentDocument, "__init__", counting)
    return counter


def _text_commands(source: Path) -> list[dict[str, Any]]:
    cells = _records(source, "cell")
    paragraphs = [r for r in _records(source, "paragraph") if "본문" in (r.summary.get("text") or "")]
    commands = [
        {"commandId": f"c{i}", "op": "set", "path": cell.path, "properties": {"text": f"값 {i}"}}
        for i, cell in enumerate(cells)
    ]
    commands.append(
        {"commandId": "p0", "op": "set", "path": paragraphs[0].path, "properties": {"text": "고친 본문"}}
    )
    # The same cell again, addressed through an earlier command's alias.
    commands.append(
        {"commandId": "again", "op": "set", "path": "$c0.path", "properties": {"text": "다시 쓴 값"}}
    )
    return commands


def _essentials(result: Any) -> list[tuple[Any, ...]]:
    return [
        (r["commandId"], r["op"], r["ok"], r["path"], r["parentPath"], tuple(r["changedProperties"]))
        for r in result.command_results
    ]


def test_text_only_batch_projects_once_and_matches_reprojection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.hwpx"
    _fixture(source)
    commands = _text_commands(source)
    assert len(commands) >= 9

    counter = _count_projections(monkeypatch)
    reused_out = tmp_path / "reused.hwpx"
    reused = apply_document_commands(_batch(source, reused_out, commands))
    assert reused.ok, reused.to_dict()
    assert counter["n"] == 1

    counter["n"] = 0
    monkeypatch.setattr(commands_module, "_text_only_batch_keeps_projection", lambda _scope: False)
    fresh_out = tmp_path / "fresh.hwpx"
    fresh = apply_document_commands(_batch(source, fresh_out, commands))
    assert fresh.ok, fresh.to_dict()
    assert counter["n"] == len(commands) + 1

    assert _essentials(reused) == _essentials(fresh)
    assert reused.document_revision == fresh.document_revision
    assert reused_out.read_bytes() == fresh_out.read_bytes()

    doc = HwpxDocument.open(str(reused_out))
    try:
        table = doc.tables.all[0]
        assert table.cell(0, 0).text == "다시 쓴 값"
        assert doc.paragraphs[1].text == "고친 본문"
    finally:
        doc.close()


def test_structural_batch_still_reprojects_after_every_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.hwpx"
    _fixture(source)
    section = _records(source, "section")[0]
    paragraph = next(r for r in _records(source, "paragraph") if "본문 하나" in (r.summary.get("text") or ""))
    commands = [
        {"commandId": "copy", "op": "copy", "path": paragraph.path, "parent": section.path,
         "position": {"mode": "append"}},
        {"commandId": "text", "op": "set", "path": "$copy.path", "properties": {"text": "복사본 글"}},
    ]
    counter = _count_projections(monkeypatch)

    result = apply_document_commands(_batch(source, tmp_path / "out.hwpx", commands))

    assert result.ok, result.to_dict()
    assert counter["n"] >= len(commands) + 1


def test_projection_looks_each_style_up_once_and_keeps_summaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "in.hwpx"
    _fixture(source)
    doc = HwpxDocument.open(str(source))
    try:
        revision = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        calls = {"style": 0, "para": 0}
        namespace = type(doc.styles)
        real_get, real_para = namespace.get, namespace.paragraph_property

        def counted_get(self: Any, ref: Any) -> Any:
            calls["style"] += 1
            return real_get(self, ref)

        def counted_para(self: Any, ref: Any) -> Any:
            calls["para"] += 1
            return real_para(self, ref)

        monkeypatch.setattr(namespace, "get", counted_get)
        monkeypatch.setattr(namespace, "paragraph_property", counted_para)

        view = HwpxAgentDocument.from_document(doc, revision=revision)

        paragraphs = [r for r in view.records if r.kind == "paragraph"]
        distinct_styles = {r.native.element.get("styleIDRef") for r in paragraphs}
        distinct_para_prs = {r.native.element.get("paraPrIDRef") for r in paragraphs}
        assert len(paragraphs) > len(distinct_styles)
        assert calls["style"] == len(distinct_styles)
        assert calls["para"] == len(distinct_para_prs)

        for record in paragraphs:
            style = real_get(doc.styles, record.native.element.get("styleIDRef"))
            para_pr = real_para(doc.styles, record.native.element.get("paraPrIDRef"))
            expected_name = style.name if style is not None and style.name else record.native.element.get("styleIDRef")
            assert record.summary["style"] == expected_name
            if para_pr is not None and para_pr.align is not None:
                assert record.summary["alignment"] == para_pr.align.horizontal
        # Summaries are per-record objects: editing one never leaks into another.
        paragraphs[0].summary["alignment"] = "CHANGED"
        assert all(r.summary.get("alignment") != "CHANGED" for r in paragraphs[1:])
    finally:
        doc.close()
