# SPDX-License-Identifier: Apache-2.0
"""Fixture-only blind benchmark receipts and provenance-safe exports.

The benchmark coordinator is intentionally provider-neutral.  It validates
pre-recorded workflow receipts and fixture judgments; it does not contain a
benchmark-only document creation path.  Fixture receipts are non-promotable
and can never substantiate human, real-agent, or real-Hancom claims.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


FIXTURE_MANIFEST_SCHEMA = "hwpx.blind-benchmark.fixture-manifest/v1"
FIXTURE_RESULT_SCHEMA = "hwpx.blind-benchmark.fixture-result/v1"
FIXTURE_RECEIPT_SCHEMA = "hwpx.blind-benchmark.fixture-receipt/v1"
PUBLIC_EXPORT_SCHEMA = "hwpx.blind-benchmark.fixture-export/v1"
FIXTURE_STATUS = "fixture_evidence_only_real_environment_unverified"
_SHA256_PREFIX = "sha256:"


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def _file_hash(path: Path) -> str:
    return _SHA256_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _require_hash(value: Any, field: str) -> str:
    text = str(value or "")
    if not text.startswith(_SHA256_PREFIX) or len(text) != 71:
        raise ValueError(f"{field} must be a sha256 digest")
    try:
        int(text.removeprefix(_SHA256_PREFIX), 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a sha256 digest") from exc
    return text


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _unique_records(records: list[Any], key: str, field: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in records:
        record = _require_mapping(item, field)
        identity = str(record.get(key, "")).strip()
        if not identity:
            raise ValueError(f"{field}.{key} is required")
        if identity in result:
            raise ValueError(f"duplicate {field}.{key}: {identity}")
        result[identity] = record
    return result


def load_fixture_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != FIXTURE_MANIFEST_SCHEMA:
        raise ValueError("unsupported blind benchmark fixture manifest schema")
    if payload.get("assurance") != "fixture":
        raise ValueError("blind benchmark fixture assurance must be fixture")
    if payload.get("frozen") is not True:
        raise ValueError("blind benchmark fixture manifest must be frozen")
    return manifest_path, payload


def _validate_workflow_receipt(receipt: Any, run_id: str, client_id: str) -> list[str]:
    failures: list[str] = []
    data = _require_mapping(receipt, f"runs[{run_id}].workflowReceipt")
    if not str(data.get("schemaVersion", "")).startswith("hwpx.workflow."):
        failures.append(f"{run_id}:unsupported_workflow_receipt")
    if not data.get("workflowId"):
        failures.append(f"{run_id}:missing_workflow_provenance")
    if not data.get("toolSpecHash"):
        failures.append(f"{run_id}:missing_tool_spec_hash")
    versions = data.get("versions")
    automation_version = (
        versions.get("automation") or versions.get("mcp")
        if isinstance(versions, Mapping)
        else None
    )
    if (
        not isinstance(versions, Mapping)
        or not automation_version
        or not versions.get("pythonHwpx")
    ):
        failures.append(f"{run_id}:missing_stack_versions")
    if data.get("terminal") is not True:
        failures.append(f"{run_id}:workflow_not_terminal")
    if data.get("state") not in {"completed", "needs_review", "failed", "cancelled"}:
        failures.append(f"{run_id}:invalid_terminal_state")
    provenance = data.get("benchmarkProvenance")
    if not isinstance(provenance, Mapping) or provenance.get("clientId") != client_id:
        failures.append(f"{run_id}:client_provenance_mismatch")
    return failures


def _validate_anonymization(run: Mapping[str, Any], run_id: str) -> tuple[str | None, list[str]]:
    failures: list[str] = []
    evidence = run.get("anonymizationEvidence")
    if not isinstance(evidence, Mapping):
        return None, [f"{run_id}:missing_anonymization_evidence"]
    opaque_id = str(evidence.get("opaqueArtifactId", "")).strip()
    if not opaque_id or not opaque_id.startswith("artifact-"):
        failures.append(f"{run_id}:invalid_opaque_artifact_id")
    if evidence.get("metadataScanComplete") is not True:
        failures.append(f"{run_id}:metadata_scan_incomplete")
    if evidence.get("revealingMetadataKeys") != []:
        failures.append(f"{run_id}:revealing_metadata_present")
    if not evidence.get("scannerId") or not evidence.get("scannerVersion"):
        failures.append(f"{run_id}:missing_anonymization_scanner_provenance")
    try:
        _require_hash(evidence.get("evidenceHash"), "anonymizationEvidence.evidenceHash")
    except ValueError:
        failures.append(f"{run_id}:invalid_anonymization_evidence_hash")
    private_tokens = {
        str(run.get("clientId", "")).lower(),
        str(_require_mapping(run.get("workflowReceipt"), "workflowReceipt").get("workflowId", "")).lower(),
    }
    if opaque_id and any(token and token in opaque_id.lower() for token in private_tokens):
        failures.append(f"{run_id}:opaque_id_reveals_provenance")
    return opaque_id or None, failures


def run_fixture_benchmark(
    manifest_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Validate a frozen fixture benchmark and emit a non-promotable receipt."""

    source, manifest = load_fixture_manifest(manifest_path)
    benchmark_id = str(manifest.get("benchmarkId", "")).strip()
    if not benchmark_id:
        raise ValueError("benchmarkId is required")
    work_orders = _unique_records(_require_list(manifest.get("workOrders"), "workOrders"), "workOrderId", "workOrders")
    clients = _unique_records(_require_list(manifest.get("clients"), "clients"), "clientId", "clients")
    runs = _unique_records(_require_list(manifest.get("runs"), "runs"), "runId", "runs")
    judgments = _require_list(manifest.get("judgments"), "judgments")
    failures: list[str] = []

    for work_order_id, work_order in work_orders.items():
        if not work_order.get("family"):
            failures.append(f"{work_order_id}:missing_work_family")
        try:
            declared_brief_hash = _require_hash(work_order.get("taskBriefHash"), "taskBriefHash")
        except ValueError:
            failures.append(f"{work_order_id}:invalid_task_brief_hash")
        else:
            if declared_brief_hash != _canonical_hash(work_order.get("taskBrief")):
                failures.append(f"{work_order_id}:task_brief_hash_mismatch")

    if strict and len(clients) < 3:
        failures.append("fewer_than_three_fixture_client_profiles")
    adapter_families = {str(item.get("adapterFamily", "")).strip() for item in clients.values()}
    if "" in adapter_families:
        failures.append("missing_client_adapter_family")
    if strict and len(adapter_families) < 3:
        failures.append("fixture_client_profiles_not_materially_distinct")

    expected_pairs = {(work_order_id, client_id) for work_order_id in work_orders for client_id in clients}
    observed_pairs: set[tuple[str, str]] = set()
    opaque_ids: list[str] = []
    normalized_runs: list[dict[str, Any]] = []
    for run_id, run in runs.items():
        work_order_id = str(run.get("workOrderId", ""))
        client_id = str(run.get("clientId", ""))
        if work_order_id not in work_orders:
            failures.append(f"{run_id}:unknown_work_order")
        if client_id not in clients:
            failures.append(f"{run_id}:unknown_client")
        pair = (work_order_id, client_id)
        if pair in observed_pairs:
            failures.append(f"{run_id}:duplicate_work_order_client_pair")
        observed_pairs.add(pair)
        failures.extend(_validate_workflow_receipt(run.get("workflowReceipt"), run_id, client_id))
        artifact = _require_mapping(run.get("artifact"), f"runs[{run_id}].artifact")
        artifact_path = (source.parent / str(artifact.get("path", ""))).resolve()
        try:
            expected_hash = _require_hash(artifact.get("contentHash"), "artifact.contentHash")
        except ValueError:
            expected_hash = ""
            failures.append(f"{run_id}:invalid_artifact_hash")
        if not artifact_path.is_file():
            failures.append(f"{run_id}:artifact_missing")
        elif expected_hash and _file_hash(artifact_path) != expected_hash:
            failures.append(f"{run_id}:artifact_hash_mismatch")
        opaque_id, anonymization_failures = _validate_anonymization(run, run_id)
        failures.extend(anonymization_failures)
        if opaque_id:
            opaque_ids.append(opaque_id)
        normalized_runs.append(
            {
                "runId": run_id,
                "workOrderId": work_order_id,
                "clientId": client_id,
                "artifactPath": str(artifact_path),
                "artifactContentHash": expected_hash,
                "opaqueArtifactId": opaque_id,
                "workflowReceipt": run.get("workflowReceipt"),
                "anonymizationEvidence": run.get("anonymizationEvidence"),
            }
        )
    missing_pairs = sorted(expected_pairs - observed_pairs)
    if missing_pairs:
        failures.append("incomplete_work_order_client_coverage")
    if len(set(opaque_ids)) != len(opaque_ids):
        failures.append("duplicate_opaque_artifact_id")

    judgments_by_artifact: dict[str, list[Mapping[str, Any]]] = {item: [] for item in opaque_ids}
    for raw in judgments:
        judgment = _require_mapping(raw, "judgments")
        artifact_id = str(judgment.get("opaqueArtifactId", ""))
        if artifact_id not in judgments_by_artifact:
            failures.append("judgment_for_unknown_artifact")
            continue
        if judgment.get("reviewerType") != "fixture_agent_judge" or judgment.get("humanLabels") is not False:
            failures.append(f"{artifact_id}:judgment_provenance_misrepresented")
        if not judgment.get("reviewerId"):
            failures.append(f"{artifact_id}:missing_reviewer_id")
        if judgment.get("provenanceVisible") is not False:
            failures.append(f"{artifact_id}:judge_was_not_blinded")
        judgments_by_artifact[artifact_id].append(judgment)
    for artifact_id, artifact_judgments in judgments_by_artifact.items():
        reviewers = {str(item.get("reviewerId", "")) for item in artifact_judgments}
        if len(reviewers) < 2:
            failures.append(f"{artifact_id}:fewer_than_two_fixture_judges")

    coverage_complete = not missing_pairs and len(observed_pairs) == len(expected_pairs)
    provenance_complete = not any("provenance" in reason or "stack_versions" in reason or "tool_spec" in reason for reason in failures)
    anonymization_complete = not any("anonym" in reason or "metadata" in reason or "opaque" in reason for reason in failures)
    judgment_coverage_complete = not any("judge" in reason or "judgment" in reason or "reviewer" in reason for reason in failures)
    accepted = sum(
        1
        for values in judgments_by_artifact.values()
        if values and all(item.get("acceptedWithoutManualHwpxEdit") is True for item in values)
    )
    receipt = {
        "schemaVersion": FIXTURE_RECEIPT_SCHEMA,
        "receiptKind": "deterministic_fixture_benchmark",
        "benchmarkId": benchmark_id,
        "manifestHash": _canonical_hash(manifest),
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "workOrderCount": len(work_orders),
        "fixtureClientProfileCount": len(clients),
        "runCount": len(runs),
        "coverageComplete": coverage_complete,
        "provenanceComplete": provenance_complete,
        "anonymizationComplete": anonymization_complete,
        "judgmentCoverageComplete": judgment_coverage_complete,
        "humanControls": False,
        "humanJudges": False,
        "realAgentClients": False,
        "realHancomVerified": False,
        "renderChecked": False,
        "replacementClaimAllowed": False,
        "verificationStatus": FIXTURE_STATUS,
    }
    result = {
        "schema": FIXTURE_RESULT_SCHEMA,
        "ok": not failures,
        "strict": strict,
        "receipt": receipt,
        "metrics": {
            "fixtureArtifactsAcceptedWithoutManualEdit": accepted,
            "fixtureArtifactCount": len(opaque_ids),
            "fixtureAcceptanceRate": accepted / len(opaque_ids) if opaque_ids else None,
            "replacementThresholdEvaluated": False,
        },
        "failReasons": sorted(set(failures)),
        "privateRuns": normalized_runs,
        "workOrders": list(work_orders.values()),
        "judgments": judgments,
    }
    if output_dir is not None:
        target_dir = Path(output_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "fixture-benchmark-result.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["resultManifestPath"] = str(target)
    return result


def export_fixture_benchmark(
    result_manifest_path: str | Path,
    *,
    output_dir: str | Path,
    strict: bool = True,
) -> dict[str, Any]:
    """Export an opaque fixture judge bundle without private run provenance."""

    source = Path(result_manifest_path).expanduser().resolve()
    result = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("schema") != FIXTURE_RESULT_SCHEMA:
        raise ValueError("unsupported blind benchmark fixture result schema")
    receipt = _require_mapping(result.get("receipt"), "receipt")
    required_true = ("coverageComplete", "provenanceComplete", "anonymizationComplete", "judgmentCoverageComplete")
    failures = list(result.get("failReasons", []))
    if result.get("ok") is not True or any(receipt.get(field) is not True for field in required_true):
        failures.append("fixture_result_not_exportable")
    if any(receipt.get(field) is not False for field in ("humanControls", "humanJudges", "realAgentClients", "realHancomVerified", "renderChecked")):
        failures.append("fixture_receipt_contains_promoted_claim")
    if failures and strict:
        raise ValueError("fixture benchmark export failed closed: " + ", ".join(sorted(set(failures))))

    destination = Path(output_dir).expanduser().resolve()
    artifacts_dir = destination / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    public_artifacts: list[dict[str, Any]] = []
    for raw in _require_list(result.get("privateRuns"), "privateRuns"):
        run = _require_mapping(raw, "privateRuns")
        opaque_id = str(run.get("opaqueArtifactId", ""))
        source_artifact = Path(str(run.get("artifactPath", ""))).resolve()
        expected_hash = _require_hash(run.get("artifactContentHash"), "artifactContentHash")
        if not opaque_id.startswith("artifact-") or not source_artifact.is_file() or _file_hash(source_artifact) != expected_hash:
            raise ValueError("artifact provenance changed after benchmark validation")
        suffix = source_artifact.suffix.lower()
        if suffix not in {".hwpx", ".pdf", ".png", ".json"}:
            raise ValueError("fixture benchmark artifact type is not allow-listed")
        target = artifacts_dir / f"{opaque_id}{suffix}"
        shutil.copy2(source_artifact, target)
        public_artifacts.append(
            {"opaqueArtifactId": opaque_id, "path": f"artifacts/{target.name}", "contentHash": expected_hash}
        )

    work_orders = []
    for raw in _require_list(result.get("workOrders"), "workOrders"):
        item = _require_mapping(raw, "workOrders")
        work_orders.append(
            {
                "workOrderId": item.get("workOrderId"),
                "family": item.get("family"),
                "taskBrief": item.get("taskBrief"),
                "taskBriefHash": _require_hash(item.get("taskBriefHash"), "taskBriefHash"),
            }
        )
    public_judgments = []
    allowed_judgment_fields = {
        "opaqueArtifactId", "reviewerId", "reviewerType", "humanLabels", "provenanceVisible",
        "acceptedWithoutManualHwpxEdit", "rubricScores", "manualEditMinutes", "abstentionCorrect",
        "criticalFailure", "adjudicationId",
    }
    forbidden_judgment_fields = {"clientId", "workflowId", "artifactPath", "sourcePath", "filename", "provenance"}
    for raw in _require_list(result.get("judgments"), "judgments"):
        judgment = _require_mapping(raw, "judgments")
        if forbidden_judgment_fields.intersection(judgment):
            raise ValueError("judgment contains private provenance")
        public_judgments.append({key: value for key, value in judgment.items() if key in allowed_judgment_fields})
    public = {
        "schema": PUBLIC_EXPORT_SCHEMA,
        "assurance": "fixture",
        "benchmarkId": receipt.get("benchmarkId"),
        "sourceResultHash": _canonical_hash(result),
        "receipt": dict(receipt),
        "workOrders": work_orders,
        "artifacts": public_artifacts,
        "judgments": public_judgments,
        "privateProvenanceIncluded": False,
    }
    manifest_target = destination / "blind-fixture-benchmark.json"
    manifest_target.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": not failures,
        "schemaVersion": PUBLIC_EXPORT_SCHEMA,
        "outputPath": str(manifest_target),
        "artifactCount": len(public_artifacts),
        "privateProvenanceIncluded": False,
        "humanControls": False,
        "humanJudges": False,
        "realAgentClients": False,
        "realHancomVerified": False,
        "renderChecked": False,
        "replacementClaimAllowed": False,
        "verificationStatus": FIXTURE_STATUS,
        "failReasons": sorted(set(failures)),
    }


__all__ = [
    "FIXTURE_MANIFEST_SCHEMA",
    "FIXTURE_RECEIPT_SCHEMA",
    "FIXTURE_RESULT_SCHEMA",
    "FIXTURE_STATUS",
    "PUBLIC_EXPORT_SCHEMA",
    "export_fixture_benchmark",
    "load_fixture_manifest",
    "run_fixture_benchmark",
]
