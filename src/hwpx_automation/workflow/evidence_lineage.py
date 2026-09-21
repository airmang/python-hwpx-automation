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


def render_evidence_manifest(
    *, revision: str, source_hash: str, receipt: RenderReceiptV2
) -> dict[str, Any]:
    """Expose exact artifact addresses for a completed workflow render.

    The manifest is a companion record. It asserts rendering only; findings
    and reviewed status are attached later with :func:`link_finding`.
    """

    if receipt.input_content_hash != source_hash:
        raise ValueError("render receipt belongs to different HWPX bytes")
    if receipt.status is not RenderStatus.SUCCEEDED or not receipt.render_checked:
        raise ValueError("successful checked render receipt required")
    pdf = next(artifact for artifact in receipt.artifacts if artifact.kind is RenderArtifactKind.PDF)
    return {
        "schemaVersion": LINEAGE_SCHEMA,
        "revision": revision,
        "sourceHash": source_hash,
        "renderJobId": receipt.job_id,
        "pdfHash": pdf.content_hash,
        "pages": [
            {"pageNumber": artifact.page_number, "pagePngHash": artifact.content_hash}
            for artifact in receipt.artifacts
            if artifact.kind is RenderArtifactKind.PAGE_PNG
        ],
        "observationStatus": "rendered_unreviewed",
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
) -> dict[str, Any]:
    """Bind a zero-based QA finding to a one-based rendered page.

    A missing or ambiguous target remains unmapped. A named observer and its
    content-addressed review evidence are required for a review claim.
    """

    if receipt.status is not RenderStatus.SUCCEEDED or not receipt.render_checked:
        raise ValueError("successful checked render receipt required")
    if receipt.input_content_hash != source_hash:
        raise ValueError("render receipt belongs to different HWPX bytes")
    if (observer_id is None) != (review_evidence_hash is None):
        raise ValueError("observer and review evidence must be supplied together")
    if review_evidence_hash is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", review_evidence_hash):
        raise ValueError("review evidence must be SHA-256 addressed")
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
    if len(bbox) != 4 or not all(isinstance(value, (int, float)) for value in bbox):
        raise ValueError("bbox must have four normalized coordinates")
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("bbox must use normalized top-left coordinates")
    mapped = target is not None and bool(target.get("path")) and target.get("ambiguous") is not True
    return {
        "schemaVersion": LINEAGE_SCHEMA,
        "revision": revision,
        "sourceHash": source_hash,
        "renderJobId": receipt.job_id,
        "pdfHash": pdf.content_hash,
        "pagePngHash": page.content_hash,
        "pageNumber": page_number,
        "bbox": list(bbox),
        "coordinateSystem": "normalized-top-left",
        "findingId": finding_id,
        "targetStatus": "mapped" if mapped else ("ambiguous" if target and target.get("ambiguous") else "unmapped"),
        "target": dict(target) if mapped and target is not None else None,
        "observationStatus": "real_hancom_review" if observer_id else "rendered_unreviewed",
        "observerId": observer_id,
        "reviewEvidenceHash": review_evidence_hash,
    }
