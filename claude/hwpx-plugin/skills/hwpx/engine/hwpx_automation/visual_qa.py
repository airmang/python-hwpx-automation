# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral, fixture-only full-page visual QA contracts.

This module deliberately keeps fixture evidence in a receipt type that cannot be
promoted to real-Hancom evidence.  Production adapters may implement
``VisionAdapter`` later, while deterministic fixtures keep tests and evaluations
reproducible today.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .document_state import document_revision


FIXTURE_RECEIPT_SCHEMA = "hwpx.visual-review.fixture.v1"
FIXTURE_MANIFEST_SCHEMA = "hwpx.visual-fixture-manifest/v1"
UNVERIFIED_STATUS = "structurally_verified_render_unverified"
SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_SAFE_REPAIR_TYPES = frozenset({"replace_text"})


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


class FixtureVisualReviewReceipt(BaseModel):
    """Evidence for deterministic fixtures, never evidence of a real render."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: str = Field(default=FIXTURE_RECEIPT_SCHEMA, alias="schemaVersion")
    receipt_kind: str = Field(default="deterministic_fixture", alias="receiptKind")
    manifest_hash: str = Field(alias="manifestHash")
    fixture_set_id: str = Field(alias="fixtureSetId")
    taxonomy_version: str = Field(alias="taxonomyVersion")
    reviewed_at: str = Field(alias="reviewedAt")
    expected_pages: int = Field(alias="expectedPages", ge=1)
    reviewed_pages: tuple[int, ...] = Field(alias="reviewedPages")
    coverage_complete: bool = Field(alias="coverageComplete")
    adapter_ids: tuple[str, ...] = Field(alias="adapterIds")
    render_checked: bool = Field(default=False, alias="renderChecked")
    real_hancom_verified: bool = Field(default=False, alias="realHancomVerified")
    verification_status: str = Field(default=UNVERIFIED_STATUS, alias="verificationStatus")

    @field_validator("render_checked", "real_hancom_verified")
    @classmethod
    def fixture_cannot_claim_real_render(cls, value: bool) -> bool:
        if value:
            raise ValueError("a fixture receipt can never claim real-Hancom verification")
        return False

    @field_validator("verification_status")
    @classmethod
    def fixture_status_is_always_unverified(cls, value: str) -> str:
        if value != UNVERIFIED_STATUS:
            raise ValueError("fixture verification status cannot be promoted")
        return value


@dataclass(frozen=True, slots=True)
class AdapterPageResult:
    adapter_id: str
    page: int
    findings: tuple[dict[str, Any], ...]
    error: str | None = None


class VisionAdapter(Protocol):
    """Provider-neutral boundary: adapters return normalized findings per page."""

    adapter_id: str

    def inspect_page(self, page: Mapping[str, Any]) -> AdapterPageResult: ...


class DeterministicFixtureAdapter:
    """Read one adapter's frozen findings from a versioned fixture manifest."""

    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id

    def inspect_page(self, page: Mapping[str, Any]) -> AdapterPageResult:
        page_number = int(page["page"])
        by_adapter = page.get("findingsByAdapter", {})
        if not isinstance(by_adapter, Mapping):
            return AdapterPageResult(self.adapter_id, page_number, (), "findingsByAdapter must be an object")
        raw = by_adapter.get(self.adapter_id)
        if raw is None:
            return AdapterPageResult(self.adapter_id, page_number, (), "adapter coverage is missing")
        if not isinstance(raw, list):
            return AdapterPageResult(self.adapter_id, page_number, (), "adapter findings must be an array")
        return AdapterPageResult(
            self.adapter_id,
            page_number,
            tuple(_normalize_finding(item, page_number, self.adapter_id) for item in raw),
        )


class CoreDeterministicAdapter:
    """Run the automation-owned full-page detectors behind the adapter boundary."""

    adapter_id = "python-hwpx-deterministic"

    def inspect_page(self, page: Mapping[str, Any]) -> AdapterPageResult:
        number = int(page["page"])
        try:
            from .office.rendering.page_qa import inspect_page_png

            verdict = inspect_page_png(str(page["absolutePath"]), page=number)
            raw_findings = verdict.to_dict().get("findings", [])
            normalized = []
            for raw in raw_findings:
                evidence = raw.get("evidence", {})
                provenance = raw.get("provenance", {})
                item = _normalize_finding(
                        {
                            "findingId": raw.get("finding_id"),
                            "bbox": list(raw["bbox"].values()) if isinstance(raw.get("bbox"), Mapping) else raw["bbox"],
                            "category": raw["category"],
                            "severity": raw["severity"],
                            "confidence": raw["confidence"],
                            "evidenceHash": "sha256:" + evidence.get("crop_sha256", evidence.get("cropSha256", "")),
                            "evidenceCrop": evidence.get("crop_bbox", evidence.get("cropBbox")),
                            "target": raw.get("target"),
                        },
                        number,
                        self.adapter_id,
                    )
                item["provenance"][0].update(
                    {
                        "detectorId": provenance.get("detector_id", provenance.get("detectorId")),
                        "detectorVersion": provenance.get("detector_version", provenance.get("detectorVersion")),
                        "kind": provenance.get("kind", "deterministic"),
                        "model": provenance.get("model"),
                        "details": provenance.get("details", {}),
                    }
                )
                normalized.append(item)
            return AdapterPageResult(self.adapter_id, number, tuple(normalized))
        except Exception as exc:
            return AdapterPageResult(self.adapter_id, number, (), f"deterministic detector failed: {exc}")


def _normalized_bbox(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("finding bbox must be [x0,y0,x1,y1]")
    bbox = tuple(float(part) for part in value)
    if any(part < 0.0 or part > 1.0 for part in bbox) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("finding bbox must be normalized and non-empty")
    return bbox  # type: ignore[return-value]


def _normalize_finding(raw: Any, page: int, adapter_id: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("finding must be an object")
    severity = str(raw.get("severity", "warning")).lower()
    if severity not in SEVERITY_ORDER:
        raise ValueError(f"unsupported finding severity: {severity}")
    confidence = float(raw.get("confidence", 1.0))
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError("finding confidence must be between 0 and 1")
    bbox = _normalized_bbox(raw.get("bbox"))
    category = str(raw.get("category", "")).strip()
    if not category:
        raise ValueError("finding category is required")
    evidence_hash = str(raw.get("evidenceHash", "")).strip()
    if not evidence_hash.startswith("sha256:"):
        raise ValueError("finding evidenceHash must be a sha256 digest")
    finding_id = str(raw.get("findingId") or _canonical_hash([page, category, bbox, evidence_hash])[:31])
    result = {
        "findingId": finding_id,
        "page": page,
        "bbox": list(bbox),
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "evidenceHash": evidence_hash,
        "evidenceCrop": raw.get("evidenceCrop"),
        "target": raw.get("target"),
        "repair": raw.get("repair"),
        "provenance": [{"adapterId": adapter_id, "sourceFindingId": finding_id}],
    }
    return result


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _map_target(finding: dict[str, Any], page: Mapping[str, Any]) -> dict[str, Any] | None:
    if isinstance(finding.get("target"), Mapping):
        return dict(finding["target"])
    candidates = []
    for target in page.get("targetMap", []):
        if not isinstance(target, Mapping) or "bbox" not in target:
            continue
        overlap = _iou(finding["bbox"], _normalized_bbox(target["bbox"]))
        if overlap >= 0.25:
            candidates.append((overlap, target))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return None
    # Ambiguous mappings remain unmapped instead of guessing.
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 0.05:
        return None
    return {key: value for key, value in candidates[0][1].items() if key != "bbox"}


def _fuse(results: Sequence[AdapterPageResult], pages: Mapping[int, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    adapter_ids = sorted({result.adapter_id for result in results})
    for result in results:
        for finding in result.findings:
            match = next(
                (
                    group
                    for group in groups
                    if group[0]["page"] == finding["page"]
                    and group[0]["category"] == finding["category"]
                    and _iou(group[0]["bbox"], finding["bbox"]) >= 0.5
                ),
                None,
            )
            (match if match is not None else groups.append([finding]))
            if match is not None:
                match.append(finding)

    fused: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for group in groups:
        chosen = max(group, key=lambda item: (SEVERITY_ORDER[item["severity"]], item["confidence"]))
        supporters = sorted(item["provenance"][0]["adapterId"] for item in group)
        item = dict(chosen)
        item["provenance"] = [entry for member in group for entry in member["provenance"]]
        item["supportingAdapters"] = supporters
        item["target"] = _map_target(item, pages[item["page"]])
        item["agreement"] = len(supporters) == len(adapter_ids)
        fused.append(item)
        if not item["agreement"]:
            disagreements.append(
                {
                    "findingId": item["findingId"],
                    "page": item["page"],
                    "category": item["category"],
                    "supportingAdapters": supporters,
                    "nonSupportingAdapters": sorted(set(adapter_ids) - set(supporters)),
                }
            )
    fused.sort(key=lambda item: (item["page"], -SEVERITY_ORDER[item["severity"]], item["findingId"]))
    return fused, disagreements


def load_fixture_manifest(manifest_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(manifest_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != FIXTURE_MANIFEST_SCHEMA:
        raise ValueError(f"unsupported visual fixture schema: {data.get('schema')!r}")
    if data.get("assurance") != "fixture":
        raise ValueError("fixture manifest assurance must be exactly 'fixture'")
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("fixture manifest must contain at least one case")
    for case in data["cases"]:
        if not isinstance(case, Mapping) or not isinstance(case.get("pages"), list) or not case["pages"]:
            raise ValueError("every fixture case must contain pages")
        for page in case["pages"]:
            page_path = (path.parent / str(page["path"])).resolve()
            if not page_path.is_relative_to(path.parent) or page_path.suffix.lower() != ".png":
                raise ValueError("fixture pages must be PNG files inside the corpus root")
            actual = hashlib.sha256(page_path.read_bytes()).hexdigest()
            if actual != str(page.get("sha256")):
                raise ValueError(f"fixture page hash mismatch: {page_path.name}")
    return path, data


def _select_case(manifest: Mapping[str, Any], case_id: str | None) -> tuple[dict[str, Any], str]:
    cases = [item for item in manifest["cases"] if isinstance(item, Mapping)]
    if case_id is None:
        if len(cases) != 1:
            raise ValueError("case_id is required when a fixture manifest contains multiple cases")
        selected = cases[0]
    else:
        selected = next((item for item in cases if str(item.get("id")) == case_id), None)
        if selected is None:
            raise ValueError(f"fixture case not found: {case_id}")
    return dict(selected), str(selected["id"])


def _case_rounds(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"pages": case.get("pages", []), "annotations": case.get("annotations", [])}]


def review_fixture(
    manifest_path: str | Path,
    *,
    case_id: str | None = None,
    round_index: int = 0,
    strict: bool = True,
    runtime_round: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    path, manifest = load_fixture_manifest(manifest_path)
    case, selected_case_id = _select_case(manifest, case_id)
    rounds = [dict(runtime_round)] if runtime_round is not None else _case_rounds(case)
    if round_index < 0 or round_index >= len(rounds):
        raise ValueError(f"fixture round {round_index} is unavailable")
    round_data = rounds[round_index]
    pages_raw = round_data.get("pages", []) if isinstance(round_data, Mapping) else []
    if not isinstance(pages_raw, list):
        raise ValueError("fixture round pages must be an array")
    pages: dict[int, Mapping[str, Any]] = {}
    duplicate_pages: list[int] = []
    for page in pages_raw:
        number = int(page["page"])
        if number in pages:
            duplicate_pages.append(number)
        pages[number] = page
    expected_pages = int(round_data.get("expectedPageCount", case.get("expectedPageCount", len(pages))))
    expected_numbers = set(range(0, expected_pages))
    missing_pages = sorted(expected_numbers - set(pages))
    unexpected_pages = sorted(set(pages) - expected_numbers)
    annotations = round_data.get("annotations", case.get("annotations", []))
    annotations_by_page: dict[int, list[dict[str, Any]]] = {}
    for annotation in annotations if isinstance(annotations, list) else []:
        item = dict(annotation)
        item.setdefault("confidence", 1.0)
        item.setdefault("evidenceHash", "sha256:" + pages[int(item["page"])]["sha256"])
        annotations_by_page.setdefault(int(item["page"]), []).append(item)
    adapter_ids = tuple(str(item) for item in round_data.get("adapters", ()))
    adapter_ids = ("python-hwpx-deterministic", *adapter_ids)
    provider_findings = round_data.get("findingsByAdapter", case.get("findingsByAdapter", {}))
    for number, page in list(pages.items()):
        enriched = dict(page)
        page_path = Path(str(enriched["path"]))
        if not page_path.is_absolute():
            page_path = path.parent / page_path
        page_path = page_path.resolve()
        if not page_path.is_relative_to(path.parent) or page_path.suffix.lower() != ".png":
            raise ValueError("runtime fixture pages must remain PNG files inside the corpus root")
        actual_hash = hashlib.sha256(page_path.read_bytes()).hexdigest()
        if actual_hash != str(enriched.get("sha256")):
            raise ValueError(f"runtime fixture page hash mismatch: {page_path.name}")
        enriched["absolutePath"] = str(page_path)
        enriched["findingsByAdapter"] = {
            adapter_id: (
                provider_findings.get(adapter_id, {}).get(str(number), provider_findings.get(adapter_id, {}).get(number, []))
                if isinstance(provider_findings, Mapping) and adapter_id != "frozen-annotation"
                else annotations_by_page.get(number, [])
            )
            for adapter_id in adapter_ids
        }
        pages[number] = enriched
    adapters: list[VisionAdapter] = [CoreDeterministicAdapter()]
    adapters.extend(DeterministicFixtureAdapter(item) for item in adapter_ids[1:])
    results = [adapter.inspect_page(page) for page in pages.values() for adapter in adapters]
    adapter_errors = [
        {"adapterId": result.adapter_id, "page": result.page, "error": result.error}
        for result in results
        if result.error
    ]
    findings, disagreements = _fuse(results, pages)
    critical = [item for item in findings if item["severity"] == "critical"]
    unmapped_critical = [item["findingId"] for item in critical if item.get("target") is None]
    coverage_complete = not (missing_pages or unexpected_pages or duplicate_pages or adapter_errors)
    fail_reasons: list[str] = []
    if not coverage_complete:
        fail_reasons.append("incomplete_page_or_adapter_coverage")
    if critical:
        fail_reasons.append("critical_findings_present")
    if unmapped_critical:
        fail_reasons.append("unmapped_critical_findings")
    if strict and disagreements:
        fail_reasons.append("adapter_disagreements_require_review")
    receipt = FixtureVisualReviewReceipt(
        manifestHash=_canonical_hash(manifest),
        fixtureSetId=selected_case_id,
        taxonomyVersion=str(manifest.get("taxonomyVersion", "unknown")),
        reviewedAt=datetime.now(timezone.utc).isoformat(),
        expectedPages=expected_pages,
        reviewedPages=tuple(sorted(pages)),
        coverageComplete=coverage_complete,
        adapterIds=adapter_ids,
    ).model_dump(by_alias=True)
    needs_review = bool(fail_reasons)
    return {
        "ok": not needs_review,
        "verdict": "needs_review" if needs_review else "pass",
        "handoffStatus": "needs_review" if needs_review else "ready",
        "verificationStatus": UNVERIFIED_STATUS,
        "renderChecked": False,
        "realHancomVerified": False,
        "visualReviewReceipt": receipt,
        "coverage": {
            "expectedPages": expected_pages,
            "reviewedPages": sorted(pages),
            "missingPages": missing_pages,
            "unexpectedPages": unexpected_pages,
            "duplicatePages": sorted(set(duplicate_pages)),
            "adapterErrors": adapter_errors,
            "complete": coverage_complete,
        },
        "findings": findings,
        "disagreements": disagreements,
        "criticalFindingCount": len(critical),
        "unmappedCriticalFindingIds": unmapped_critical,
        "failReasons": fail_reasons,
        "fixtureRound": round_index,
        "caseId": selected_case_id,
    }


def write_review_artifact(review: Mapping[str, Any], output_dir: str | Path | None) -> str | None:
    if output_dir is None:
        return None
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "visual-review-fixture.json"
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(output)


def review_fixture_evidence(
    manifest_path: str | Path,
    *,
    case_id: str | None,
    adapter_evidence_path: str | Path | None,
    strict: bool,
) -> dict[str, Any]:
    if adapter_evidence_path is None:
        return review_fixture(manifest_path, case_id=case_id, strict=strict)
    manifest_file, manifest = load_fixture_manifest(manifest_path)
    _case, selected_case_id = _select_case(manifest, case_id)
    evidence_file = Path(adapter_evidence_path).expanduser().resolve()
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if evidence.get("schema") != "hwpx.visual-adapter-evidence/v1":
        raise ValueError("unsupported visual adapter evidence schema")
    if str(evidence.get("caseId")) != selected_case_id:
        raise ValueError("adapter evidence caseId does not match selected fixture case")
    if evidence.get("manifestHash") != _canonical_hash(manifest):
        raise ValueError("adapter evidence manifestHash does not match the immutable corpus")
    runtime_round = evidence.get("result")
    if not isinstance(runtime_round, Mapping):
        raise ValueError("adapter evidence result is required")
    return review_fixture(
        manifest_file,
        case_id=selected_case_id,
        strict=strict,
        runtime_round=runtime_round,
    )


def repair_fixture(
    *,
    filename: str | Path,
    manifest_path: str | Path,
    repair_plan_path: str | Path,
    case_id: str | None,
    output_path: str | Path,
    expected_revision: str,
    idempotency_key: str,
    max_rounds: int,
    apply_repair: Callable[[Path, Mapping[str, Any], str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Run a guarded, allow-listed fixture repair loop with regression rollback."""

    source = Path(filename).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    actual_revision = document_revision(source)
    if actual_revision != expected_revision:
        return {
            "ok": False,
            "verdict": "blocked",
            "handoffStatus": "blocked",
            "reason": "document revision mismatch",
            "expectedRevision": expected_revision,
            "documentRevision": actual_revision,
            "verificationStatus": UNVERIFIED_STATUS,
            "renderChecked": False,
            "realHancomVerified": False,
            "ledger": [],
        }
    if not idempotency_key or len(idempotency_key) < 8:
        raise ValueError("idempotency_key must contain at least 8 characters")
    if max_rounds < 0 or max_rounds > 3:
        raise ValueError("max_rounds must be between 0 and the hard cap of 3")
    if source == output:
        raise ValueError("fixture repair preserves the source; output_path must differ")
    manifest_file, manifest = load_fixture_manifest(manifest_path)
    case, selected_case_id = _select_case(manifest, case_id)
    plan_file = Path(repair_plan_path).expanduser().resolve()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("schema") != "hwpx.visual-repair-plan/v1":
        raise ValueError("unsupported visual repair plan schema")
    if str(plan.get("caseId")) != selected_case_id:
        raise ValueError("repair plan caseId does not match selected fixture case")
    if plan.get("manifestHash") != _canonical_hash(manifest):
        raise ValueError("repair plan manifestHash does not match the immutable corpus")
    plan_rounds = plan.get("rounds", [])
    if not isinstance(plan_rounds, list):
        raise ValueError("repair plan rounds must be an array")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    initial_review = plan.get("initialReview")
    current = review_fixture(
        manifest_path,
        case_id=selected_case_id,
        round_index=0,
        strict=True,
        runtime_round=initial_review if isinstance(initial_review, Mapping) else None,
    )
    ledger: list[dict[str, Any]] = []
    rolled_back = False
    applied_keys: set[str] = set()
    available_rounds = len(plan_rounds) + 1

    for round_number in range(1, min(max_rounds, available_rounds - 1) + 1):
        planned_round = plan_rounds[round_number - 1]
        planned_repairs = planned_round.get("repairs", []) if isinstance(planned_round, Mapping) else []
        by_finding = {
            str(item.get("findingId")): dict(item)
            for item in planned_repairs
            if isinstance(item, Mapping)
        }
        candidates = []
        for finding in current["findings"]:
            repair = by_finding.get(finding["findingId"])
            if repair and finding["severity"] != "critical" and finding.get("target") is not None:
                item = dict(finding)
                item["repair"] = repair
                candidates.append(item)
        if not candidates:
            break
        before_bytes = output.read_bytes()
        round_start_revision = document_revision(output)
        before_revision = round_start_revision
        actions: list[dict[str, Any]] = []
        for index, finding in enumerate(candidates):
            repair = dict(finding["repair"])
            repair_type = str(repair.get("type", ""))
            if repair_type not in _SAFE_REPAIR_TYPES:
                continue
            action_key = _canonical_hash([idempotency_key, finding["findingId"], repair])
            if action_key in applied_keys:
                continue
            result = apply_repair(output, repair, before_revision, f"{idempotency_key}:r{round_number}:{index}")
            if result.get("ok") is False or int(result.get("replaced_count", 0)) < 1:
                actions.append({"findingId": finding["findingId"], "action": repair_type, "applied": False})
                continue
            applied_keys.add(action_key)
            before_revision = document_revision(output)
            actions.append({"findingId": finding["findingId"], "action": repair_type, "applied": True})
        if not any(action["applied"] for action in actions):
            ledger.append(
                {
                    "round": round_number,
                    "status": "no_effect",
                    "beforeRevision": round_start_revision,
                    "afterRevision": document_revision(output),
                    "actions": actions,
                }
            )
            break
        rerender = planned_round.get("rerender") if isinstance(planned_round, Mapping) else None
        if not isinstance(rerender, Mapping):
            raise ValueError("every repair round requires deterministic fixture rerender evidence")
        candidate_review = review_fixture(
            manifest_file,
            case_id=selected_case_id,
            round_index=0,
            strict=True,
            runtime_round=rerender,
        )
        old_keys = {
            (item["findingId"], item["page"], item["category"], item["severity"])
            for item in current["findings"]
        }
        new_findings = [
            item
            for item in candidate_review["findings"]
            if (item["findingId"], item["page"], item["category"], item["severity"]) not in old_keys
        ]
        regression = bool(new_findings) or candidate_review["criticalFindingCount"] > current["criticalFindingCount"]
        if regression:
            attempted_revision = document_revision(output)
            output.write_bytes(before_bytes)
            rolled_back = True
            ledger.append(
                {
                    "round": round_number,
                    "status": "rolled_back",
                    "beforeRevision": round_start_revision,
                    "attemptedRevision": attempted_revision,
                    "afterRevision": document_revision(output),
                    "actions": actions,
                    "regressionFindingIds": [item["findingId"] for item in new_findings],
                }
            )
            break
        after_revision = document_revision(output)
        ledger.append(
            {
                "round": round_number,
                "status": "accepted",
                "beforeRevision": round_start_revision,
                "afterRevision": after_revision,
                "actions": actions,
                    "fixtureRound": round_number,
                    "repairPlanHash": _canonical_hash(plan),
                }
        )
        current = candidate_review

    current = dict(current)
    current.update(
        {
            "ledger": ledger,
            "repairLedger": {
                "schema": "hwpx.visual-repair-ledger/v1",
                "manifestSchema": FIXTURE_MANIFEST_SCHEMA,
                "manifestHash": _canonical_hash(manifest),
                "caseId": selected_case_id,
                "pageHashes": [page.get("sha256") for page in case.get("pages", [])],
                "entries": ledger,
            },
            "rolledBack": rolled_back,
            "outputPath": str(output),
            "originalRevision": actual_revision,
            "documentRevision": document_revision(output),
            "repairRounds": len(ledger),
            "renderChecked": False,
            "realHancomVerified": False,
            "verificationStatus": UNVERIFIED_STATUS,
        }
    )
    # Any remaining finding must be reviewed.  Fixture evidence is never a visual pass
    # suitable for real-Hancom completion even when the deterministic set is clean.
    if current["findings"]:
        current["ok"] = False
        current["verdict"] = "needs_review"
        current["handoffStatus"] = "needs_review"
    return current


__all__ = [
    "DeterministicFixtureAdapter",
    "FixtureVisualReviewReceipt",
    "VisionAdapter",
    "repair_fixture",
    "review_fixture",
    "review_fixture_evidence",
    "write_review_artifact",
]
