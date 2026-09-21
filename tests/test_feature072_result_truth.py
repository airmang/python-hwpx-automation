"""Regression cases for render evidence and domain error transport."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest
from test_document_plan_mcp_e2e import _plan
from test_workflow_render_contract_v2 import HASH_A, v2_success

from hwpx_automation import runtime, server
from hwpx_automation.office import rendering
from hwpx_automation.office.authoring import inspect_document_authoring_quality
from hwpx_automation.workflow.evidence_lineage import (
    link_finding,
    render_evidence_manifest,
)


@pytest.mark.parametrize("pdf_kind", ["one_line", "image_only"])
def test_render_does_not_claim_visual_completion(tmp_path: Path, monkeypatch, pdf_kind: str) -> None:
    source = tmp_path / "source.hwpx"
    assert server.create_document_from_plan(str(source), _plan())["created"]

    class Oracle:
        def available(self) -> bool:
            return True

        def render_pdf(self, hwpx_path: str, out_pdf: str) -> str:
            assert Path(hwpx_path).read_bytes() == source.read_bytes()
            pdf = pymupdf.open()
            page = pdf.new_page()
            if pdf_kind == "one_line":
                page.insert_text((50, 50), "Only one surviving line")
            pdf.save(out_pdf)
            pdf.close()
            return out_pdf

    monkeypatch.setattr(rendering, "MacHancomOracle", Oracle)
    report = inspect_document_authoring_quality(source, verify_render=True)
    assert report["render_checked"] is True
    assert report["visual_complete"] == "unverified"
    assert report["visual_review_required"] is True
    assert report["source_content_hash"] == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def test_agent_stale_revision_survives_mcp_mapping() -> None:
    payload = {
        "ok": False,
        "error": {
            "code": "stale_revision",
            "message": "expectedRevision does not match",
            "target": "batch.expectedRevision",
            "recoverability": "retryable",
            "suggestion": "Read the document again and retry.",
        },
    }
    error = runtime._result_failure_error("apply_agent_batch", payload)
    assert error is not None
    assert error.data["errorCode"] == "stale_revision"
    assert error.data["error"]["retryable"] is True
    assert error.data["error"]["details"]["target"] == "batch.expectedRevision"
    assert runtime._failure_code_from_payload({"ok": False, "code": "arbitrary_lowercase"}) == "TOOL_EXECUTION_FAILED"


def test_source_replacement_during_render_invalidates_result(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.hwpx"
    other = tmp_path / "other.hwpx"
    assert server.create_document_from_plan(str(source), _plan())["created"]
    changed_plan = _plan()
    changed_plan["title"] = "A different document"
    assert server.create_document_from_plan(str(other), changed_plan)["created"]
    original = source.read_bytes()

    class Oracle:
        def available(self) -> bool:
            return True

        def render_pdf(self, hwpx_path: str, out_pdf: str) -> str:
            assert Path(hwpx_path).read_bytes() == original
            source.write_bytes(other.read_bytes())
            pdf = pymupdf.open()
            pdf.new_page()
            pdf.save(out_pdf)
            pdf.close()
            return out_pdf

    monkeypatch.setattr(rendering, "MacHancomOracle", Oracle)
    report = inspect_document_authoring_quality(source, verify_render=True)
    assert report["pass"] is False
    assert report["render_checked"] is False
    assert "source changed during inspection" in report["gaps"]


def test_lineage_binds_exact_source_page_and_review() -> None:
    receipt = v2_success()
    link = link_finding(
        revision=HASH_A, source_hash=HASH_A, receipt=receipt,
        page_index=1, bbox=(0.1, 0.2, 0.4, 0.5), finding_id="crop-2",
        target={"path": "/section[1]/table[1]/cell[2]", "revision": HASH_A},
    )
    assert link["pageNumber"] == 2
    assert link["pagePngHash"] == receipt.artifacts[2].content_hash
    assert link["targetStatus"] == "mapped"
    assert link["observationStatus"] == "render_reported_review_unverified"
    assert link["backendReported"] == receipt.backend
    assert "target" not in receipt.model_dump()
    with pytest.raises(ValueError, match="supplied together"):
        link_finding(
            revision=HASH_A, source_hash=HASH_A, receipt=receipt,
            page_index=0, bbox=(0.1, 0.2, 0.4, 0.5), finding_id="review",
            observer_id="operator-1",
        )
    with pytest.raises(ValueError, match="different HWPX"):
        link_finding(
            revision="sha256:" + "0" * 64, source_hash="sha256:" + "0" * 64,
            receipt=receipt, page_index=0, bbox=(0.1, 0.2, 0.4, 0.5),
            finding_id="stale",
        )


def test_lineage_rejects_false_review_and_target_claims() -> None:
    receipt = v2_success()
    args = {
        "revision": HASH_A,
        "source_hash": HASH_A,
        "receipt": receipt,
        "page_index": 0,
        "bbox": (0.1, 0.2, 0.4, 0.5),
        "finding_id": "finding",
    }
    with pytest.raises(ValueError, match="revision"):
        link_finding(**{**args, "revision": "sha256:revision"})
    stale_target = link_finding(**args, target={"path": "/section[1]/table[1]", "revision": "sha256:" + "0" * 64})
    assert stale_target["targetStatus"] == "unmapped"
    ambiguous_target = link_finding(**args, target={"path": "/section[1]/table[1]", "revision": HASH_A, "ambiguous": True})
    assert ambiguous_target["targetStatus"] == "ambiguous"
    for pdf_hash, page_hash in (
        ("sha256:" + "0" * 64, receipt.artifacts[1].content_hash),
        (receipt.artifacts[0].content_hash, "sha256:" + "0" * 64),
    ):
        with pytest.raises(ValueError, match="different render artifacts"):
            link_finding(
                **args, observer_id="operator-1", review_evidence_hash="sha256:" + "1" * 64,
                review_pdf_hash=pdf_hash, review_page_png_hash=page_hash,
            )
    linked = link_finding(
        **args, observer_id="operator-1", review_evidence_hash="sha256:" + "1" * 64,
        review_pdf_hash=receipt.artifacts[0].content_hash,
        review_page_png_hash=receipt.artifacts[1].content_hash,
    )
    assert linked["observationStatus"] == "observation_link_recorded_unverified"
    fixture_receipt = receipt.model_copy(update={"backend": "fixture-backend"})
    manifest = render_evidence_manifest(revision=HASH_A, source_hash=HASH_A, receipt=fixture_receipt)
    assert manifest["backendReported"] == "fixture-backend"
    assert manifest["observationStatus"] == "render_reported_review_unverified"
    fixture_link = link_finding(
        **{**args, "receipt": fixture_receipt},
        observer_id="fixture-adapter", review_evidence_hash="sha256:" + "1" * 64,
        review_pdf_hash=receipt.artifacts[0].content_hash,
        review_page_png_hash=receipt.artifacts[1].content_hash,
    )
    assert fixture_link["backendReported"] == "fixture-backend"
    assert fixture_link["observationStatus"] == "observation_link_recorded_unverified"
