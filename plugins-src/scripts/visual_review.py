#!/usr/bin/env python3
"""Record HWPX visual-review evidence for submission handoff.

The script is intentionally useful without Hancom or ComputerUse. In CI it can
write a blocked fallback record that proves the evidence shape is valid. In a
local GUI session, launch or open the target with a viewer, inspect it with
ComputerUse or a human reviewer, then rerun this command with observations and
a screenshot path for observed_pass evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hwpx.visual-review.v1"
ALLOWED_STATUSES = {"observed_pass", "needs_review", "blocked"}
ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quality_report(path: Path) -> dict[str, Any]:
    try:
        from hwpx_automation.office.authoring import inspect_operating_plan_quality
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "visual_review_required": True,
        }

    try:
        report = inspect_operating_plan_quality(path)
    except Exception as exc:
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "visual_review_required": True,
        }

    return {
        "available": True,
        "report_version": report.get("report_version"),
        "status": report.get("status"),
        "score": report.get("score"),
        "pass": report.get("pass"),
        "gaps": report.get("gaps", []),
        "repair_hints": report.get("repair_hints", []),
        "visual_review_required": bool(report.get("visual_review_required", True)),
    }


def structural_acceptance(path: Path) -> dict[str, Any]:
    """Axis A: renderer-free acceptance through open and save->reopen round-trip."""

    try:
        from hwpx.document import HwpxDocument
    except Exception as exc:
        return {
            "opens": None,
            "roundtrip_ok": None,
            "status": "skipped",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    result: dict[str, Any] = {"opens": False, "roundtrip_ok": False, "status": "rejected"}
    try:
        doc = HwpxDocument.open(path)
        result["opens"] = True
        round_bytes = doc.to_bytes()
        reopened = HwpxDocument.open(round_bytes)
        result["roundtrip_ok"] = len(reopened.sections) == len(doc.sections)
        result["status"] = "accepted" if result["roundtrip_ok"] else "rejected"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    return result


def _viewer_command(mode: str) -> tuple[list[str] | None, str | None]:
    if mode == "none":
        return None, "viewer disabled by --viewer none"

    if mode.startswith("command:"):
        command = mode.removeprefix("command:").strip()
        if not command:
            return None, "empty command viewer"
        return shlex.split(command), None

    env_command = os.environ.get("HWPX_VIEWER_COMMAND", "").strip()
    if env_command:
        return shlex.split(env_command), None

    if platform.system() == "Darwin" and shutil.which("open"):
        return ["open"], None

    return None, "no viewer command found; set HWPX_VIEWER_COMMAND or use --viewer command:open"


def _output_snippet(value: str) -> str:
    return " ".join(value.split())[:300]


def _launch_viewer(command: list[str] | None, target: Path, enabled: bool) -> tuple[bool, str | None]:
    if not enabled:
        return False, "viewer launch skipped; rerun with --launch-viewer to open the document"
    if not command:
        return False, "viewer command unavailable"

    try:
        result = subprocess.run(
            [*command, str(target)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if result.returncode != 0:
        details = []
        stderr = _output_snippet(result.stderr)
        stdout = _output_snippet(result.stdout)
        if stderr:
            details.append(f"stderr={stderr}")
        if stdout:
            details.append(f"stdout={stdout}")
        suffix = f"; {'; '.join(details)}" if details else ""
        return False, f"viewer command exited with return code {result.returncode}{suffix}"

    return True, None


def _load_previous(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"unsupported evidence schema: {data.get('schemaVersion')}")

    return data


def _target_block(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "sha256": _sha256(path),
    }


def _same_path(path: Path, other: Path) -> bool:
    if path == other:
        return True
    try:
        return path.samefile(other)
    except FileNotFoundError:
        return False


def _screenshot_path(value: str | None) -> str | None:
    if not value:
        return None

    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"screenshot path does not exist: {path}")

    return str(path)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    target = Path(args.hwpx).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"target HWPX does not exist: {target}")
    if target.suffix.lower() != ".hwpx":
        raise ValueError(f"target must be a .hwpx file: {target}")

    evidence_path = Path(args.evidence).expanduser().resolve()
    if _same_path(evidence_path, target):
        raise ValueError(f"evidence path must not be the target HWPX path: {evidence_path}")

    target_info = _target_block(target)
    command, viewer_reason = _viewer_command(args.viewer)
    launched, launch_reason = _launch_viewer(command, target, args.launch_viewer)
    quality = _quality_report(target)
    fallback_reason = viewer_reason
    if fallback_reason is None and args.launch_viewer and launch_reason:
        fallback_reason = launch_reason
    status = args.status

    if status is None:
        status = "blocked" if command is None else "needs_review"
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {sorted(ALLOWED_STATUSES)}")
    layout_risks = list(args.layout_risk or [])
    if status == "observed_pass" and layout_risks:
        raise ValueError("observed_pass cannot include residual layout risks")
    if status == "observed_pass" and not args.screenshot:
        raise ValueError("observed_pass requires --screenshot evidence")
    if status == "observed_pass" and args.viewer == "none":
        raise ValueError("observed_pass requires an opened-document review, not --viewer none")
    if status == "observed_pass" and command is None:
        raise ValueError("observed_pass requires an available viewer command or explicit viewer mode")
    if status == "observed_pass" and args.launch_viewer and not launched and launch_reason:
        raise ValueError(f"observed_pass requires successful viewer launch: {launch_reason}")
    screenshot_path = _screenshot_path(args.screenshot)

    previous = _load_previous(evidence_path)
    previous_target = (previous or {}).get("target") or {}
    previous_sha256 = previous_target.get("sha256")
    if previous_sha256 and previous_sha256 != target_info["sha256"]:
        raise ValueError(f"evidence file belongs to a different target: {evidence_path}")

    previous_iterations = list((previous or {}).get("iterations", []))
    previous_current = (previous or {}).get("current")
    if previous_current:
        previous_iterations.append(previous_current)

    current = {
        "iteration": len(previous_iterations) + 1,
        "status": status,
        "timestamp": _utc_now(),
        "tool_path": str(Path(__file__).resolve()),
        "review_method": args.method,
        "screenshot_path": screenshot_path,
        "observations": list(args.observation or []),
        "layout_risks": layout_risks,
        "notes": args.notes or "",
        "regenerated_from": args.regenerated_from or "",
        "structural_acceptance": (
            {"opens": None, "roundtrip_ok": None, "status": "skipped", "reason": "--skip-structural-check"}
            if args.skip_structural_check
            else structural_acceptance(target)
        ),
    }
    if fallback_reason:
        current["fallback_reason"] = fallback_reason
    ready_for_submission_claim = (
        status == "observed_pass" and not layout_risks and command is not None and screenshot_path is not None
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "target": target_info,
        "quality": quality,
        "viewer": {
            "mode": args.viewer,
            "available": command is not None,
            "command": shlex.join(command) if command else "",
            "launched": launched,
        },
        "current": current,
        "iterations": previous_iterations,
        "summary": {
            "resolved_visual_review_required": status,
            "ready_for_submission_claim": ready_for_submission_claim,
            "residual_layout_risk_count": len(current["layout_risks"]),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record HWPX visual review evidence")
    parser.add_argument("hwpx", help="target .hwpx file")
    parser.add_argument(
        "--evidence",
        default=str(ROOT / "examples" / "out" / "visual_review_evidence.json"),
        help="JSON evidence path",
    )
    parser.add_argument("--viewer", default="auto", help="auto, none, or command:open")
    parser.add_argument("--launch-viewer", action="store_true", help="open the HWPX with the selected viewer")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), help="visual review result")
    parser.add_argument(
        "--method",
        default="computer-use-or-human-viewer",
        help="review method label stored in evidence",
    )
    parser.add_argument("--screenshot", help="path to screenshot captured during visual review")
    parser.add_argument("--observation", action="append", help="observed layout fact; repeatable")
    parser.add_argument("--layout-risk", action="append", help="remaining visual/layout risk; repeatable")
    parser.add_argument("--notes", default="", help="short reviewer note")
    parser.add_argument("--regenerated-from", default="", help="previous evidence path or source run id")
    parser.add_argument(
        "--skip-structural-check",
        action="store_true",
        help="skip axis-A renderer-free round-trip acceptance",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evidence = build_evidence(args)
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 2

    evidence_path = Path(args.evidence).expanduser().resolve()
    _write_json_atomic(evidence_path, evidence)

    print(f"[OK] visual review evidence written: {evidence_path}")
    print(f"[OK] status={evidence['current']['status']}")
    print(f"[OK] ready_for_submission_claim={evidence['summary']['ready_for_submission_claim']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
