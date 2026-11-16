# SPDX-License-Identifier: Apache-2.0
"""M7 / S-062 P4: native TOC / cross-reference MCP surface.

No live Hancom render in this suite (S-060 discipline) — verify_toc is
exercised on its structural/degrade paths only."""
from __future__ import annotations

from pathlib import Path


from hwpx_automation.office.authoring import _outline_style_refs
from hwpx.document import HwpxDocument
import hwpx_automation.server as server


def _authored(tmp_path: Path, *, headings: int = 2) -> Path:
    doc = HwpxDocument.new()
    refs = _outline_style_refs(doc, 1)
    for i in range(1, headings + 1):
        heading = doc.add_paragraph(f"{i}번째 제목", para_pr_id_ref=refs.get("para_pr_id_ref"))
        heading.style_id_ref = refs.get("style_id_ref")
        doc.add_paragraph("본문 문장. " * 30, para_pr_id_ref=1).style_id_ref = "1"
    doc.add_paragraph("참조 문단: ", para_pr_id_ref=1).style_id_ref = "1"
    target = tmp_path / "native-toc.hwpx"
    doc.save_to_path(str(target))
    return target


def test_add_toc_inserts_native_field(tmp_path: Path) -> None:
    src = _authored(tmp_path)
    result = server.add_toc(str(src))
    assert result["ok"] is True
    assert result["entryCount"] == 2
    assert result["cachedPagesAreEstimates"] is True

    report = server.verify_toc(str(src))
    assert report["structural"]["hasNativeToc"] is True
    assert report["structural"]["entryCount"] == 2
    assert report["structural"]["targetsResolve"] is True
    assert report["render_checked"] is False  # honest degrade without oracle
    assert report["verdict"] == "unverified"
    assert report["ok"] is True


def test_add_toc_requires_outline_headings(tmp_path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("개요 스타일이 아닌 문단")
    src = tmp_path / "plain.hwpx"
    doc.save_to_path(str(src))
    result = server.add_toc(str(src))
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "no_outline_headings"


def test_add_cross_reference_targets_heading_by_text(tmp_path: Path) -> None:
    src = _authored(tmp_path)
    doc = HwpxDocument.open(str(src))
    paras = [p.text or "" for s in doc.sections for p in s.paragraphs]
    idx = next(i for i, t in enumerate(paras) if "참조 문단" in t)

    result = server.add_cross_reference(str(src), idx, "2번째 제목", cached_page=1)
    assert result["ok"] is True
    assert result["targetId"]

    report = server.verify_toc(str(src))
    assert report["structural"]["crossrefCount"] == 1
    assert report["structural"]["targetsResolve"] is True


def test_add_cross_reference_unknown_target(tmp_path: Path) -> None:
    src = _authored(tmp_path)
    result = server.add_cross_reference(str(src), 0, "존재하지 않는 제목")
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "target_not_found"


def test_verify_toc_detects_structural_conflict(tmp_path: Path) -> None:
    """A crossref cache disagreeing with the TOC entry for the same heading is
    the oracle-free staleness signal — the MCP surface must report it."""
    src = _authored(tmp_path)
    server.add_toc(str(src))
    doc = HwpxDocument.open(str(src))
    paras = [p.text or "" for s in doc.sections for p in s.paragraphs]
    idx = next(i for i, t in enumerate(paras) if "참조 문단" in t)
    server.add_cross_reference(str(src), idx, "1번째 제목", cached_page=9)  # conflicts with entry cache 1

    report = server.verify_toc(str(src))
    assert report["structural"]["internally_consistent"] is False
    assert report["verdict"] == "stale_detected_structurally"
    assert report["ok"] is False


def test_toc_tools_reject_non_hwpx(tmp_path: Path) -> None:
    bogus = tmp_path / "doc.hwp"
    bogus.write_bytes(b"not hwpx")
    for call in (
        lambda: server.add_toc(str(bogus)),
        lambda: server.add_cross_reference(str(bogus), 0, "x"),
        lambda: server.verify_toc(str(bogus)),
    ):
        result = call()
        assert result["ok"] is False
        assert result["errors"][0]["code"] == "unsupported_format"
