# SPDX-License-Identifier: Apache-2.0
"""Versioned companion links from a render receipt to page findings.

The v2 render receipt is frozen and extra-forbid. Keep review and target mapping
outside it so older readers continue to validate the original receipt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .render_contracts import RenderArtifactKind, RenderReceiptV2, RenderStatus

LINEAGE_SCHEMA = "hwpx.evidence-lineage/v1"
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _bound_receipt(revision: str, source_hash: str, receipt: RenderReceiptV2) -> None:
    if not _SHA256.fullmatch(revision) or revision != source_hash:
        raise ValueError("revision must identify the exact source bytes")
    if receipt.input_content_hash != source_hash:
        raise ValueError("render receipt belongs to different HWPX bytes")
    if receipt.status is not RenderStatus.SUCCEEDED or not receipt.render_checked:
        raise ValueError("successful checked render receipt required")


def render_evidence_manifest(
    *, revision: str, source_hash: str, receipt: RenderReceiptV2
) -> dict[str, Any]:
    """Expose exact artifact addresses for a completed workflow render.

    The manifest is a companion record. It asserts rendering only; findings
    and reviewed status are attached later with :func:`link_finding`.
    """

    _bound_receipt(revision, source_hash, receipt)
    pdf = next(artifact for artifact in receipt.artifacts if artifact.kind is RenderArtifactKind.PDF)
    return {
        "schemaVersion": LINEAGE_SCHEMA,
        "revision": revision,
        "sourceHash": source_hash,
        "renderJobId": receipt.job_id,
        "backendReported": receipt.backend,
        "hancomBuildReported": receipt.hancom_build,
        "workerVersionReported": receipt.worker_version,
        "pdfHash": pdf.content_hash,
        "pages": [
            {"pageNumber": artifact.page_number, "pagePngHash": artifact.content_hash}
            for artifact in receipt.artifacts
            if artifact.kind is RenderArtifactKind.PAGE_PNG
        ],
        "observationStatus": "render_reported_review_unverified",
    }


def link_finding(
    *,
    revision: str,
    source_hash: str,
    receipt: RenderReceiptV2,
    page_index: int,
    bbox: Sequence[float],
    finding_id: str,
    target: Mapping[str, Any] | None = None,
    observer_id: str | None = None,
    review_evidence_hash: str | None = None,
    review_pdf_hash: str | None = None,
    review_page_png_hash: str | None = None,
) -> dict[str, Any]:
    """Bind a zero-based QA finding to a one-based rendered page.

    A missing or ambiguous target remains unmapped. Review metadata is a link,
    never a visual pass: this function cannot authenticate an observer.
    """

    _bound_receipt(revision, source_hash, receipt)
    if not isinstance(page_index, int) or page_index < 0:
        raise ValueError("page_index must be zero-based")
    page_number = page_index + 1
    page = next(
        (artifact for artifact in receipt.artifacts
         if artifact.kind is RenderArtifactKind.PAGE_PNG and artifact.page_number == page_number),
        None,
    )
    pdf = next(
        (artifact for artifact in receipt.artifacts if artifact.kind is RenderArtifactKind.PDF),
        None,
    )
    if page is None or pdf is None:
        raise ValueError("finding page has no bound render artifact")
    review_values = (observer_id, review_evidence_hash, review_pdf_hash, review_page_png_hash)
    if any(value is not None for value in review_values):
        if not all(isinstance(value, str) and value for value in review_values):
            raise ValueError("observer and review evidence/artifact hashes must be supplied together")
        if not _SHA256.fullmatch(review_evidence_hash or ""):
            raise ValueError("review evidence must be SHA-256 addressed")
        if review_pdf_hash != pdf.content_hash or review_page_png_hash != page.content_hash:
            raise ValueError("review evidence belongs to different render artifacts")
    if len(bbox) != 4 or not all(isinstance(value, (int, float)) for value in bbox):
        raise ValueError("bbox must have four normalized coordinates")
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("bbox must use normalized top-left coordinates")
    mapped = (
        target is not None
        and bool(target.get("path"))
        and target.get("revision") == revision
        and target.get("ambiguous") is not True
    )
    return {
        "schemaVersion": LINEAGE_SCHEMA,
        "revision": revision,
        "sourceHash": source_hash,
        "renderJobId": receipt.job_id,
        "backendReported": receipt.backend,
        "hancomBuildReported": receipt.hancom_build,
        "workerVersionReported": receipt.worker_version,
        "pdfHash": pdf.content_hash,
        "pagePngHash": page.content_hash,
        "pageNumber": page_number,
        "bbox": list(bbox),
        "coordinateSystem": "normalized-top-left",
        "findingId": finding_id,
        "targetStatus": "mapped" if mapped else ("ambiguous" if target and target.get("ambiguous") else "unmapped"),
        "target": dict(target) if mapped and target is not None else None,
        "observationStatus": "observation_link_recorded_unverified" if observer_id else "render_reported_review_unverified",
        "observerId": observer_id,
        "reviewEvidenceHash": review_evidence_hash,
    }
