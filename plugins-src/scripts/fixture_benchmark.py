#!/usr/bin/env python3
"""Build and validate the synthetic, provenance-blind fixture benchmark.

This module deliberately contains no model client.  It freezes work orders and
blind packets, and provides empty judge-pass templates that must be completed by
two independently invoked reviewers.  Fixture evidence can never be promoted to
a human, real-agent, real-Hancom, or replacement claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "hwpx.blind-benchmark.fixture-manifest/v1"
VERSION = "1.0.0"
FAMILIES = (
    "reading_extraction",
    "transactional_editing",
    "known_form_fill",
    "unfamiliar_form_fill",
    "typed_authoring",
    "batch_comparison",
)
PROFILES = (
    ("fixture-client-cautious", "1.0.0", 2),
    ("fixture-client-direct", "1.0.0", 3),
    ("fixture-client-resume", "1.0.0", 1),
)
WORKFLOW_API = (
    "start_workflow",
    "get_workflow",
    "continue_workflow",
    "approve_workflow_decision",
    "resume_workflow",
    "cancel_workflow",
)
HONEST_FLAGS = {
    "fixture": True,
    "humanLabels": False,
    "humanControls": False,
    "humanJudges": False,
    "realAgentClientsVerified": False,
    "realAgentClients": False,
    "realHancomVerified": False,
    "replacementClaimAllowed": False,
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _work_order(family: str, number: int) -> dict[str, Any]:
    case_id = f"wo-{FAMILIES.index(family) + 1:02d}-{number:02d}"
    must_abstain = number in (5, 11)
    scenario = "필수 근거가 의도적으로 누락된 요청" if must_abstain else "완결된 합성 한국 행정문서 요청"
    return {
        "schemaVersion": "hwpx.fixture-work-order.v1",
        "workOrderId": case_id,
        "family": family,
        "difficulty": ("ambiguous" if must_abstain else ("routine" if number <= 8 else "advanced")),
        "mustAbstain": must_abstain,
        "brief": f"{family} 합성 사례 {number}: {scenario}. 제공된 fixture만 사용하라.",
        "sourcePolicy": "synthetic_only",
        "expectedDisposition": "needs_review" if must_abstain else "complete",
        "workflowContract": "server-enforced-workflow.v1",
        "requiredApi": list(WORKFLOW_API),
        "privateData": False,
    }


def _rubric() -> dict[str, Any]:
    return {
        "schemaVersion": "hwpx.fixture-rubric.v1",
        "rubricVersion": VERSION,
        "judgeType": "agent_judge",
        "humanLabels": False,
        "dimensions": [
            {"id": key, "weight": weight, "scale": [0, 1, 2, 3, 4]}
            for key, weight in (
                ("semantic_correctness", 25),
                ("hwpx_fidelity", 20),
                ("visual_quality", 15),
                ("korean_office_compliance", 15),
                ("task_completeness", 15),
                ("manual_edit_necessity", 10),
            )
        ],
        "criticalOverrides": ["document_corruption", "unmasked_high_confidence_pii", "critical_false_complete"],
        "acceptanceRule": "weighted_score>=3.6 and no critical override and manual_edit_necessity>=3",
    }


def build(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    orders = [_work_order(family, number) for family in FAMILIES for number in range(1, 13)]
    profiles = []
    for profile_id, version, cadence in PROFILES:
        profile = {
            "schemaVersion": "hwpx.fixture-client-profile.v1",
            "profileId": profile_id,
            "profileVersion": version,
            "clientType": "fixture_client_profile",
            "materiallyDifferentRealAgent": False,
            "workflowContract": "server-enforced-workflow.v1",
            "requiredApi": list(WORKFLOW_API),
            "continueCadence": cadence,
            **HONEST_FLAGS,
        }
        profiles.append(profile)
        write_json(root / "profiles" / f"{profile_id}-{version}.json", profile)

    write_json(root / "rubric-v1.json", _rubric())
    write_json(root / "work-orders.json", {"schemaVersion": "hwpx.fixture-work-orders.v1", "orders": orders})

    artifacts = []
    routing = []
    runs = []
    for order in orders:
        for profile in profiles:
            token = digest({"order": order["workOrderId"], "profile": profile["profileId"], "salt": "s070-fixture-v1"})[:20]
            artifact_id = f"artifact-{token}"
            packet = {
                "schemaVersion": "hwpx.blind-artifact.v1",
                "artifactId": artifact_id,
                "taskBrief": order["brief"],
                "fixtureOutput": {"disposition": order["expectedDisposition"], "synthetic": True},
                **HONEST_FLAGS,
            }
            artifacts.append({
                "artifactId": artifact_id,
                "workOrderId": order["workOrderId"],
                "packet": f"blind/{artifact_id}.json",
                "sha256": digest(packet),
            })
            routing.append({"artifactId": artifact_id, "profileId": profile["profileId"], "profileVersion": profile["profileVersion"]})
            write_json(root / "blind" / f"{artifact_id}.json", packet)

            artifact_path = root / "blind" / f"{artifact_id}.json"
            client_id = profile["profileId"]
            run_id = "run-" + digest({"artifact": artifact_id})[:20]
            evidence = {"opaqueArtifactId": artifact_id, "scannerId": "fixture-metadata-scanner", "scannerVersion": "1.0.0"}
            runs.append({
                "runId": run_id,
                "workOrderId": order["workOrderId"],
                "clientId": client_id,
                "workflowReceipt": {
                    "schemaVersion": "hwpx.workflow.receipt.v1",
                    "workflowId": "fixture-workflow-" + digest({"run": run_id})[:16],
                    "toolSpecHash": "sha256:" + digest({"contract": "server-enforced-workflow.v1"}),
                    "versions": {"mcp": "2.21.0", "pythonHwpx": "2.27.0", "skill": "0.1.28"},
                    "terminal": True,
                    "state": order["expectedDisposition"].replace("complete", "completed"),
                    "benchmarkProvenance": {"clientId": client_id},
                },
                "artifact": {"path": f"blind/{artifact_id}.json", "contentHash": file_digest(artifact_path)},
                "anonymizationEvidence": {
                    **evidence,
                    "metadataScanComplete": True,
                    "revealingMetadataKeys": [],
                    "evidenceHash": "sha256:" + digest(evidence),
                },
            })

    manifest_body = {
        "schema": SCHEMA,
        "assurance": "fixture",
        "frozen": True,
        "benchmarkId": "s070-synthetic-qualification-v1",
        "benchmarkVersion": VERSION,
        "protocolStatus": "fixture_qualification",
        "workflowContract": "server-enforced-workflow.v1",
        "workOrdersPath": "work-orders.json",
        "rubricPath": "rubric-v1.json",
        "profilePaths": [f"profiles/{p['profileId']}-{p['profileVersion']}.json" for p in profiles],
        "workOrderCount": len(orders),
        "artifactCount": len(artifacts),
        "families": list(FAMILIES),
        "mustAbstainCount": sum(o["mustAbstain"] for o in orders),
        "artifacts": artifacts,
        "workOrders": [
            {
                "workOrderId": order["workOrderId"],
                "family": order["family"],
                "taskBrief": order["brief"],
                "taskBriefHash": "sha256:" + digest(order["brief"]),
                "mustAbstain": order["mustAbstain"],
            }
            for order in orders
        ],
        "clients": [
            {
                "clientId": profile["profileId"],
                "clientVersion": profile["profileVersion"],
                "clientType": "fixture_client_profile",
                "adapterFamily": profile["profileId"].removeprefix("fixture-client-"),
                "workflowContract": profile["workflowContract"],
                "materiallyDifferentRealAgent": False,
            }
            for profile in profiles
        ],
        "runs": runs,
        "judgments": [],
        **HONEST_FLAGS,
    }
    manifest = dict(manifest_body, manifestHash=digest(manifest_body))
    write_json(root / "manifest.json", manifest)
    # Private routing is explicitly excluded from blind judge packets and public projections.
    write_json(root / "private-routing.json", {"schemaVersion": "hwpx.fixture-routing.v1", "judgeVisible": False, "routes": routing})
    for pass_id in ("judge-a", "judge-b"):
        judge_path = root / "judge-templates" / f"{pass_id}.json"
        existing = _load(judge_path) if judge_path.is_file() else {}
        if existing.get("status") == "scored":
            continue
        write_json(judge_path, {
            "schemaVersion": "hwpx.agent-judge-pass.v1",
            "passId": pass_id,
            "judgeType": "agent_judge",
            "independentInvocationRequired": True,
            "humanLabels": False,
            "rubricVersion": VERSION,
            "manifestHash": manifest["manifestHash"],
            "status": "unscored_template",
            "judgments": [],
        })

    result = {
        "schemaVersion": "hwpx.fixture-result-manifest.v1",
        "benchmarkVersion": VERSION,
        "manifestHash": manifest["manifestHash"],
        "status": "awaiting_two_independent_agent_judge_passes",
        "workOrderCount": len(orders),
        "artifactCount": len(artifacts),
        "clientProfileCount": len(profiles),
        "familyCounts": dict(Counter(o["family"] for o in orders)),
        "mustAbstainCount": manifest["mustAbstainCount"],
        "judgePassesAccepted": 0,
        "metrics": None,
        "releaseVersions": {"python-hwpx": "2.27.0", "hwpx-mcp-server": "2.21.0", "hwpx-skill": "0.1.28"},
        **HONEST_FLAGS,
    }
    write_json(root / "result-manifest.json", result)
    project(root / "result-manifest.json", root / "public")
    return manifest


def finalize(root: Path, judge_paths: list[Path]) -> dict[str, Any]:
    """Bind two independently produced judge passes and compute core metrics."""
    # The blind-evaluation benchmark is repository QA and moved out of the shipped
    # python-hwpx package in 5.0. It lives in that repository's scripts/ tree, so
    # this harness needs a checkout rather than an install.
    from benchmark import build_result_projections, measure_fixture_benchmark

    manifest = _load(root / "manifest.json")
    manifest_hash = manifest.get("manifestHash")
    artifact_ids = {item["artifactId"] for item in manifest["artifacts"]}
    if len(judge_paths) != 2:
        raise ValueError("exactly two independent agent judge passes are required")
    passes = [_load(path) for path in judge_paths]
    pass_ids = {item.get("passId") for item in passes}
    if len(pass_ids) != 2:
        raise ValueError("judge pass ids must be distinct")
    judgments: list[dict[str, Any]] = []
    for item in passes:
        if item.get("status") != "scored" or item.get("manifestHash") != manifest_hash:
            raise ValueError("judge pass is not scored against the frozen manifest")
        rows = item.get("judgments", [])
        if {row.get("artifactId") for row in rows} != artifact_ids or len(rows) != len(artifact_ids):
            raise ValueError("judge pass must cover every anonymized artifact exactly once")
        for row in rows:
            if row.get("humanLabel") is not False or row.get("humanLabels") is not False:
                raise ValueError("agent judge pass cannot contain human labels")
            if row.get("provenanceVisible") is not False:
                raise ValueError("agent judge pass was not blind")
            normalized = dict(row)
            normalized["reviewerType"] = "fixture_agent_judge"
            normalized["judgeType"] = "agent_judge"
            normalized["reviewerId"] = str(row.get("reviewerId") or row.get("judgeId"))
            normalized["judgeId"] = normalized["reviewerId"]
            normalized["opaqueArtifactId"] = row["artifactId"]
            normalized["humanLabel"] = False
            normalized["humanLabels"] = False
            normalized["provenanceVisible"] = False
            normalized["rubricScores"] = dict(row["scores"])
            judgments.append(normalized)

    final_manifest = dict(manifest)
    final_manifest["judgments"] = judgments
    final_manifest.pop("manifestHash", None)
    final_manifest["manifestHash"] = digest(final_manifest)
    write_json(root / "final-manifest.json", final_manifest)

    route_by_artifact = {
        item["anonymizationEvidence"]["opaqueArtifactId"]: item["clientId"]
        for item in manifest["runs"]
    }
    order_external = {item["workOrderId"]: item for item in _load(root / "work-orders.json")["orders"]}
    protocol_orders = []
    for item in manifest["workOrders"]:
        source = order_external[item["workOrderId"]]
        protocol_orders.append({
            "workOrderId": item["workOrderId"],
            "family": item["family"],
            "difficulty": "must_abstain" if source["mustAbstain"] else source["difficulty"],
            "prompt": source["brief"],
        })
    protocol = {
        "schema": "hwpx.blind-real-work-eval/v1",
        "benchmarkId": manifest["benchmarkId"],
        "protocolVersion": VERSION,
        "promptVersion": VERSION,
        "rubricVersion": VERSION,
        "provenanceRandomizationSeed": "s070-fixture-v1",
        "assurance": "fixture",
        "executionKind": "fixture_simulation",
        "workOrders": protocol_orders,
        "clients": [
            {"clientId": item["clientId"], "clientType": "fixture_agent_client", "hostSpecificHints": False}
            for item in manifest["clients"]
        ],
        **HONEST_FLAGS,
    }
    artifacts = []
    for item in manifest["artifacts"]:
        order = order_external[item["workOrderId"]]
        artifacts.append({
            "artifactId": item["artifactId"],
            "blindId": item["artifactId"],
            "workOrderId": item["workOrderId"],
            "clientId": route_by_artifact[item["artifactId"]],
            "provenanceHiddenFromJudges": True,
            "filenameMetadataStripped": True,
            "transcriptExcludedFromJudges": True,
            "status": "abstained" if order["mustAbstain"] else "completed",
            "repairRounds": 0,
            "reviewMinutes": None,
            "editMinutes": None,
            "cost": None,
        })
    core_judgments = [
        {key: row[key] for key in ("artifactId", "judgeId", "judgeType", "humanLabel", "acceptedWithoutManualHwpxEdit", "criticalFailure", "scores")}
        for row in judgments
    ]
    result = {
        "schema": "hwpx.blind-real-work-eval-result/v1",
        "assurance": "fixture",
        "executionKind": "fixture_simulation",
        "protocol": protocol,
        "artifacts": artifacts,
        "judgments": core_judgments,
        **HONEST_FLAGS,
    }
    metrics = measure_fixture_benchmark(result, strict=True)
    projections = build_result_projections(metrics)
    by_artifact: dict[str, list[dict[str, Any]]] = {}
    for row in core_judgments:
        by_artifact.setdefault(row["artifactId"], []).append(row)
    adjudicated = []
    score_disagreements = 0
    for artifact_id, rows in sorted(by_artifact.items()):
        accepted = [bool(row["acceptedWithoutManualHwpxEdit"]) for row in rows]
        score_equal = rows[0]["scores"] == rows[1]["scores"]
        score_disagreements += not score_equal
        adjudicated.append({
            "artifactId": artifact_id,
            "acceptedWithoutManualHwpxEdit": all(accepted),
            "criticalFailure": any(row["criticalFailure"] for row in rows),
            "acceptanceAgreement": len(set(accepted)) == 1,
            "scoreAgreement": score_equal,
        })
    adjudication = {
        "schemaVersion": "hwpx.fixture-adjudication.v1",
        "reviewerType": "agent_judge",
        "humanLabels": False,
        "artifactCount": len(adjudicated),
        "acceptanceDisagreements": sum(not row["acceptanceAgreement"] for row in adjudicated),
        "scoreDisagreements": score_disagreements,
        "adjudicated": adjudicated,
    }
    result["metrics"] = metrics
    result["projections"] = projections
    result["adjudication"] = adjudication
    result["sourceMcpManifest"] = "final-manifest.json"
    write_json(root / "result-manifest.json", result)
    write_json(root / "adjudication.json", adjudication)
    project(root / "result-manifest.json", root / "public")
    return {"ok": True, "metrics": metrics, "agreement": metrics["agreement"], "adjudication": adjudication}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object required: {path}")
    return value


def validate(root: Path) -> dict[str, Any]:
    manifest = _load(root / "manifest.json")
    claimed = manifest.pop("manifestHash", None)
    if claimed != digest(manifest):
        raise ValueError("manifest hash mismatch")
    manifest["manifestHash"] = claimed
    for key, expected in HONEST_FLAGS.items():
        if manifest.get(key) is not expected:
            raise ValueError(f"dishonest provenance flag {key}")
    orders = _load(root / manifest["workOrdersPath"])["orders"]
    if len(orders) < 60 or set(o["family"] for o in orders) != set(FAMILIES):
        raise ValueError("benchmark requires >=60 orders across exactly six families")
    if not any(o["mustAbstain"] for o in orders):
        raise ValueError("must-abstain coverage missing")
    profiles = [_load(root / rel) for rel in manifest["profilePaths"]]
    if len(profiles) != 3 or len({tuple(p["requiredApi"]) for p in profiles}) != 1:
        raise ValueError("three profiles must share one high-level workflow API")
    if len(manifest["artifacts"]) != len(orders) * len(profiles):
        raise ValueError("incomplete client coverage")
    if len({a["artifactId"] for a in manifest["artifacts"]}) != len(manifest["artifacts"]):
        raise ValueError("duplicate artifact id")
    forbidden = tuple(p["profileId"] for p in profiles)
    for artifact in manifest["artifacts"]:
        packet = _load(root / artifact["packet"])
        if digest(packet) != artifact["sha256"]:
            raise ValueError(f"artifact hash mismatch {artifact['artifactId']}")
        raw = canonical(packet).decode()
        if any(value in raw for value in forbidden) or "profileId" in raw or "agentId" in raw:
            raise ValueError(f"provenance leaked into blind packet {artifact['artifactId']}")
    if len(manifest.get("runs", [])) != len(manifest["artifacts"]):
        raise ValueError("workflow receipt coverage incomplete")
    return {"ok": True, "manifestHash": claimed, "workOrders": len(orders), "artifacts": len(manifest["artifacts"])}


def project(result_path: Path, output_dir: Path) -> None:
    result = _load(result_path)
    for key, expected in HONEST_FLAGS.items():
        if result.get(key) is not expected:
            raise ValueError(f"result promoted fixture evidence through {key}")
    metrics = result.get("metrics")
    projections = result.get("projections")
    summary = {
        "schemaVersion": "hwpx.fixture-public-projection.v1",
        "sourceManifestSha256": digest(result),
        "status": result.get("status", "scored_fixture_only"),
        "coverage": metrics.get("counts") if isinstance(metrics, dict) else {k: result[k] for k in ("workOrderCount", "artifactCount", "clientProfileCount", "familyCounts", "mustAbstainCount")},
        "metrics": metrics,
        "projections": projections,
        "releaseVersions": result.get("releaseVersions", {"python-hwpx": "2.27.0", "hwpx-mcp-server": "2.21.0", "hwpx-skill": "0.1.28"}),
        **HONEST_FLAGS,
    }
    write_json(output_dir / "fixture-scorecard.json", summary)
    write_json(output_dir / "fixture-gallery.json", dict(summary, artifactDisplay="anonymized_only"))
    lines = [
        "# Synthetic fixture qualification",
        "",
        f"Status: `{summary['status']}`",
        f"Frozen work orders: {summary['coverage'].get('workOrders', result.get('workOrderCount'))}; anonymized artifacts: {summary['coverage'].get('artifacts', result.get('artifactCount'))}.",
        "",
        "This is synthetic fixture evidence. Human controls, human judges, three real agent clients, real Hancom, and any human-replacement claim remain unverified.",
        "",
        f"Projection source SHA-256: `{digest(result)}`",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fixture-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_drift(result_path: Path, output_dir: Path) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        expected = Path(temp)
        project(result_path, expected)
        for name in ("fixture-scorecard.json", "fixture-gallery.json", "fixture-report.md"):
            if (expected / name).read_bytes() != (output_dir / name).read_bytes():
                raise ValueError(f"generated projection drift: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "validate"):
        item = sub.add_parser(command)
        item.add_argument("root", type=Path)
    item = sub.add_parser("project")
    item.add_argument("result", type=Path)
    item.add_argument("output", type=Path)
    item = sub.add_parser("check-drift")
    item.add_argument("result", type=Path)
    item.add_argument("output", type=Path)
    item = sub.add_parser("finalize")
    item.add_argument("root", type=Path)
    item.add_argument("judges", type=Path, nargs=2)
    args = parser.parse_args()
    if args.command == "build":
        report = build(args.root)
    elif args.command == "validate":
        report = validate(args.root)
    elif args.command == "project":
        project(args.result, args.output)
        report = {"ok": True}
    elif args.command == "check-drift":
        check_drift(args.result, args.output)
        report = {"ok": True}
    else:
        report = finalize(args.root, args.judges)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
