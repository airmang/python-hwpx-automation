#!/usr/bin/env python3
"""Build and validate the S-070 synthetic, provenance-blind fixture benchmark.

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
        write_json(root / "judge-templates" / f"{pass_id}.json", {
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
    summary = {
        "schemaVersion": "hwpx.fixture-public-projection.v1",
        "sourceManifestSha256": digest(result),
        "status": result["status"],
        "coverage": {k: result[k] for k in ("workOrderCount", "artifactCount", "clientProfileCount", "familyCounts", "mustAbstainCount")},
        "metrics": result["metrics"],
        "releaseVersions": result["releaseVersions"],
        **HONEST_FLAGS,
    }
    write_json(output_dir / "fixture-scorecard.json", summary)
    write_json(output_dir / "fixture-gallery.json", dict(summary, artifactDisplay="anonymized_only"))
    lines = [
        "# S-070 synthetic fixture qualification",
        "",
        f"Status: `{result['status']}`",
        f"Frozen work orders: {result['workOrderCount']}; anonymized artifacts: {result['artifactCount']}.",
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
    args = parser.parse_args()
    if args.command == "build":
        report = build(args.root)
    elif args.command == "validate":
        report = validate(args.root)
    elif args.command == "project":
        project(args.result, args.output)
        report = {"ok": True}
    else:
        check_drift(args.result, args.output)
        report = {"ok": True}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
