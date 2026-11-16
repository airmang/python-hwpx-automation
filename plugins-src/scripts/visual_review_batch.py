#!/usr/bin/env python3
"""Run scaled HWPX visual-review evidence collection.

This is an orchestration layer over scripts/visual_review.py. Per-file evidence
keeps the existing hwpx.visual-review.v1 contract; the batch report only
summarizes Axis A structural acceptance and Axis B visual-review status.
"""

from __future__ import annotations

import argparse
import glob
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from detect_hwpx_viewer import detect_hwpx_viewer  # noqa: E402
from visual_review import ALLOWED_STATUSES, build_evidence, _write_json_atomic  # noqa: E402


def _expand_inputs(patterns: list[str]) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            candidate = Path(pattern).expanduser()
            if candidate.exists():
                matches = [str(candidate)]
        for match in matches:
            path = Path(match).expanduser().resolve()
            if path.suffix.lower() != ".hwpx" or not path.is_file() or path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return sorted(paths, key=lambda item: str(item))


def _safe_stem(path: Path) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in path.stem)


def _viewer_mode(detection: dict[str, Any], mode: str) -> str:
    if mode == "none" or detection.get("status") == "blocked":
        return "none"
    if mode.startswith("command:"):
        return mode
    command = detection.get("command") or []
    return f"command:{shlex.join(command)}" if command else "none"


def _status_for(detection: dict[str, Any], requested: str | None) -> str:
    if detection.get("status") == "blocked":
        return "blocked"
    return requested or "needs_review"


def _axis_a(structural: dict[str, Any]) -> str:
    if structural.get("status") == "accepted":
        return "accepted"
    if structural.get("status") == "skipped":
        return "skipped"
    return "rejected"


def _axis_b(status: str) -> str:
    if status == "observed_pass":
        return "observed_pass"
    if status == "needs_review":
        return "needs_review"
    return "blocked"


def _evidence_args(
    *,
    target: Path,
    evidence_path: Path,
    status: str,
    viewer_mode: str,
    launch_viewer: bool,
    detection: dict[str, Any],
    notes: str,
    method: str,
    skip_structural_check: bool,
) -> argparse.Namespace:
    layout_risks: list[str] = []
    observations = [
        f"viewer_detection={detection.get('viewer')}",
        f"viewer_reason={detection.get('reason')}",
    ]
    if status == "blocked":
        layout_risks.append("Rendered layout requires opened-document review in a supported HWPX viewer.")
    elif status == "needs_review":
        layout_risks.append("Viewer is available, but no opened-document visual pass has been recorded.")

    return SimpleNamespace(
        hwpx=str(target),
        evidence=str(evidence_path),
        viewer=viewer_mode,
        launch_viewer=launch_viewer,
        status=status,
        method=method,
        screenshot=None,
        observation=observations,
        layout_risk=layout_risks,
        notes=notes,
        regenerated_from="",
        skip_structural_check=skip_structural_check,
    )


def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    targets = _expand_inputs(args.inputs)
    if not targets:
        raise ValueError("no .hwpx inputs matched")

    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).expanduser().resolve() if args.report else evidence_dir / "visual_review_batch_report.json"
    detection = detect_hwpx_viewer()
    viewer_mode = _viewer_mode(detection, args.viewer)
    status = _status_for(detection, args.status)

    rows: list[dict[str, Any]] = []
    counts = {"observed_pass": 0, "needs_review": 0, "blocked": 0}
    axis_a_counts = {"accepted": 0, "rejected": 0, "skipped": 0}
    for target in targets:
        evidence_path = evidence_dir / f"{_safe_stem(target)}.visual-review.json"
        evidence = build_evidence(
            _evidence_args(
                target=target,
                evidence_path=evidence_path,
                status=status,
                viewer_mode=viewer_mode,
                launch_viewer=args.launch_viewer,
                detection=detection,
                notes=args.notes,
                method=args.method,
                skip_structural_check=args.skip_structural_check,
            )
        )
        _write_json_atomic(evidence_path, evidence)

        current = evidence["current"]
        axis_a = _axis_a(current.get("structural_acceptance", {}))
        axis_b = _axis_b(current["status"])
        counts[current["status"]] += 1
        axis_a_counts[axis_a] += 1
        rows.append(
            {
                "file": str(target),
                "axis_a": axis_a,
                "axis_b": axis_b,
                "status": current["status"],
                "evidence": str(evidence_path),
                "structural_acceptance": current.get("structural_acceptance", {}),
                "fallback_reason": current.get("fallback_reason", ""),
            }
        )

    report = {
        "schemaVersion": "hwpx.visual-review-batch.v1",
        "viewer_detection": detection,
        "inputs": [str(path) for path in targets],
        "counts": counts,
        "axis_a_counts": axis_a_counts,
        "ready_for_submission_claim": counts["blocked"] == 0 and counts["needs_review"] == 0,
        "rows": rows,
    }
    _write_json_atomic(report_path, report)
    report["report_path"] = str(report_path)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HWPX visual review evidence collection for many files")
    parser.add_argument("--inputs", action="append", required=True, help="input .hwpx glob; repeatable")
    parser.add_argument("--evidence-dir", required=True, help="directory for per-file evidence JSON")
    parser.add_argument("--report", help="batch report JSON path; defaults inside --evidence-dir")
    parser.add_argument("--viewer", default="auto", help="auto, none, or command:...")
    parser.add_argument("--launch-viewer", action="store_true", help="launch each file in the detected viewer")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), help="requested status when a viewer is available")
    parser.add_argument("--method", default="batch-preflight", help="review method label stored in evidence")
    parser.add_argument("--notes", default="Batch visual acceptance preflight.", help="notes stored in each evidence file")
    parser.add_argument("--skip-structural-check", action="store_true", help="skip Axis A structural acceptance")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_batch(args)
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 2

    print(f"[OK] visual review batch report written: {report['report_path']}")
    print(
        "[OK] counts "
        f"observed_pass={report['counts']['observed_pass']} "
        f"needs_review={report['counts']['needs_review']} "
        f"blocked={report['counts']['blocked']}"
    )
    print(f"[OK] ready_for_submission_claim={report['ready_for_submission_claim']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
