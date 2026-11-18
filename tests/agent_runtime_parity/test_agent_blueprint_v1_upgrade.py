# SPDX-License-Identifier: Apache-2.0
"""A v1 blueprint (hwpx-automation 7, objects and fields placed by runs) is read as v2 and replays
to what the v1 replay wrote: the same paragraph text, objects at the same offsets, the field around
the same value. ``fixtures/blueprint_v1/block-v1.hwpxbp`` was dumped by the v1 code (made-up text)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from hwpx import HwpxDocument

from hwpx_automation.office.agent import HwpxAgentDocument
from hwpx_automation.office.agent.blueprint import replay_document_blueprint

BUNDLE = Path(__file__).parents[1] / "fixtures" / "blueprint_v1" / "block-v1.hwpxbp"
BLUEPRINT_HASH = "sha256:2a3535c7dd597f5b2cdcf9ff8794a62ff1e1730c9dc1746a281f06e7f012482d"
# What the v1 replay of this bundle wrote (measured with the v1 code, 8.0 19차).
V1_TEXT = "소풍 준비물 안내 연락 가람 끝"
V1_ITEMS = [("shape", 9), ("footnote", 9), ("picture", 9), ("table", 13), ("form-field", None)]


def test_v1_blueprint_is_read_as_v2_and_replays_as_v1_did(tmp_path: Path) -> None:
    target, output = tmp_path / "target.hwpx", tmp_path / "output.hwpx"
    with HwpxDocument.new() as document:
        document.sections[0].paragraphs[0].text = "받는 문서"
        document.save(target)
    result = replay_document_blueprint({
        "schemaVersion": "hwpx.agent-blueprint-replay/v1",
        "bundle": {"filename": str(BUNDLE), "blueprintHash": BLUEPRINT_HASH},
        "target": {"input": str(target), "output": str(output), "overwrite": False},
        "targetParent": "/section[1]",
        "position": {"mode": "append"},
        "mode": "portable",
        "mappingPolicy": {"strict": True},
        "expectedRevision": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        "idempotencyKey": None,
        "dryRun": False,
        "quality": "transparent",
        "verificationRequirements": ["package", "reopen", "openSafety", "semanticDiff", "bytePreservation"],
    })
    assert result.ok, result.to_dict()
    assert result.verification_report["upgradedFrom"] == "hwpx.agent-blueprint/v1"
    with HwpxAgentDocument.open(output) as agent:
        paragraph = agent.resolve_record(str(result.root_path))
        children = [agent.resolve_record(child) for child in paragraph.child_paths]
        items = [(child.kind, (child.place or {}).get("offset")) for child in children if child.kind != "run"]
        fields = [(r.summary.get("name"), r.summary.get("value")) for r in children if r.kind == "form-field"]
        assert paragraph.native.text == V1_TEXT
    assert items == V1_ITEMS
    assert fields == [("담당", "가람")]
