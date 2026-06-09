#!/usr/bin/env python3
"""quickcheck.py

Run a beginner-friendly end-to-end sanity check for the HWPX skill.

What it verifies:
1. Required Python packages import successfully
2. Example document creation works
3. Generated HWPX outputs pass editor-open safety verification
4. Example inspection works on the created document
5. CLI text extraction works on the created document
6. Optional document-plan/proposal/builder/government-report generation paths work when requested
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCRIPTS_DIR = ROOT / "scripts"
OUTPUT_PATH = EXAMPLES_DIR / "out" / "01_created.hwpx"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = None if env is None else {**os.environ, **env}
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=run_env)


def _print_block(label: str, output: str) -> None:
    print(f"[{label}]")
    text = output.rstrip()
    if text:
        print(text)
    else:
        print("(no output)")
    print()


def _open_safety_command(path: Path) -> list[str]:
    check_code = (
        "from pathlib import Path; "
        "from hwpx.tools.package_validator import validate_editor_open_safety; "
        f"path = Path({str(path)!r}); "
        "raise SystemExit(f'output missing: {path}' if not path.exists() "
        "else (0 if validate_editor_open_safety(path).ok "
        "else validate_editor_open_safety(path).summary))"
    )
    return [sys.executable, "-c", check_code]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HWPX skill sanity checks")
    parser.add_argument("--proposal", action="store_true", help="also run the proposal-generation preset example")
    parser.add_argument("--document-plan", action="store_true", help="also run the declarative document-plan generation example")
    parser.add_argument(
        "--builder",
        action="store_true",
        help="also run the hwpx.builder layout-sensitive generation example",
    )
    parser.add_argument(
        "--operating-plan",
        action="store_true",
        help="also run the operating-plan document-plan quality example",
    )
    parser.add_argument(
        "--government-report",
        action="store_true",
        help="also run the government-report preset, parser, computed-value, and quality example",
    )
    parser.add_argument(
        "--template-formfit",
        action="store_true",
        help="also run the template-preserving form-fit example",
    )
    parser.add_argument(
        "--visual-review",
        action="store_true",
        help="also validate the visual-review fallback evidence shape",
    )
    parser.add_argument(
        "--visual-review-batch",
        action="store_true",
        help="also validate the visual-review batch fallback report shape",
    )
    args = parser.parse_args(argv)

    print("[STEP] checking Python runtime")
    if sys.version_info < MIN_PYTHON:
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        required = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+"
        print(f"[ERR] Python {required} is required, current: {current}")
        print(f"        run this script with a newer interpreter, for example: {sys.executable}")
        return 2

    print("[OK] Python version passed")
    print()

    print("[STEP] checking Python package imports")
    try:
        import lxml  # noqa: F401
        import hwpx  # noqa: F401
    except Exception as exc:
        print("[ERR] required packages are not ready")
        print(f"        install with: {sys.executable} -m pip install -U python-hwpx lxml")
        print(f"        import error: {exc}")
        return 2

    print("[OK] imports passed")
    print()

    visual_review_evidence = EXAMPLES_DIR / "out" / "09_visual_review_fallback.json"
    visual_review_batch_dir = EXAMPLES_DIR / "out" / "11_visual_review_batch"
    visual_review_batch_report = visual_review_batch_dir / "visual_review_batch_report.json"
    commands = [
        (
            "create",
            [sys.executable, str(EXAMPLES_DIR / "01_create_and_save.py")],
        ),
        (
            "create-open-safety",
            _open_safety_command(OUTPUT_PATH),
        ),
        (
            "inspect",
            [sys.executable, str(EXAMPLES_DIR / "02_extract_and_inspect.py"), str(OUTPUT_PATH)],
        ),
        (
            "extract",
            [sys.executable, str(SCRIPTS_DIR / "text_extract.py"), str(OUTPUT_PATH)],
        ),
    ]

    if args.proposal:
        proposal_output = EXAMPLES_DIR / "out" / "04_proposal.hwpx"
        commands.append((
            "proposal",
            [sys.executable, str(EXAMPLES_DIR / "04_create_proposal.py")],
        ))
        commands.append((
            "proposal-open-safety",
            _open_safety_command(proposal_output),
        ))
    if args.document_plan:
        document_plan_output = EXAMPLES_DIR / "out" / "06_document_plan.hwpx"
        commands.append((
            "document-plan",
            [sys.executable, str(EXAMPLES_DIR / "06_create_from_document_plan.py")],
        ))
        commands.append((
            "document-plan-open-safety",
            _open_safety_command(document_plan_output),
        ))
    if args.builder:
        commands.append((
            "builder",
            [sys.executable, str(EXAMPLES_DIR / "10_create_with_builder.py")],
        ))
        builder_output = EXAMPLES_DIR / "out" / "10_builder_vertical_slice.hwpx"
        commands.append((
            "builder-open-safety",
            _open_safety_command(builder_output),
        ))
        check_code = (
            "from hwpx import HwpxDocument; "
            f"doc = HwpxDocument.open({str(builder_output)!r}); "
            "text = doc.export_text(); "
            "checks = ["
            "('제목: 2026 AI 교육 운영계획' in text, 'metadata title missing'), "
            "('추진 개요' in text, 'heading missing'), "
            "('전 학년' in text, 'rich run text missing'), "
            "('준비' in text and '운영' in text, 'table text missing'), "
            "('샘플 이미지' in text, 'image caption missing'), "
            "('다음 페이지 점검' in text, 'page-break follow-up text missing')"
            "]; "
            "failures = [message for passed, message in checks if not passed]; "
            "raise SystemExit('; '.join(failures) if failures else 0)"
        )
        commands.append((
            "builder-readback",
            [sys.executable, "-c", check_code],
        ))
    if args.operating_plan:
        operating_plan_output = EXAMPLES_DIR / "out" / "07_operating_plan.hwpx"
        commands.append((
            "operating-plan",
            [sys.executable, str(EXAMPLES_DIR / "07_create_operating_plan.py")],
        ))
        commands.append((
            "operating-plan-open-safety",
            _open_safety_command(operating_plan_output),
        ))
        check_code = (
            "from hwpx import inspect_operating_plan_quality; "
            f"report = inspect_operating_plan_quality({str(operating_plan_output)!r}); "
            "checks = ["
            "(report.get('report_version') == 'operating-plan-quality-v1', 'report_version mismatch'), "
            "(report.get('status') == 'ready', 'status is not ready'), "
            "(report.get('visual_review_required') is True, 'visual_review_required is not true')"
            "]; "
            "failures = [message for passed, message in checks if not passed]; "
            "raise SystemExit('; '.join(failures) if failures else 0)"
        )
        commands.append((
            "operating-plan-file-only-quality",
            [sys.executable, "-c", check_code],
        ))
    if args.government_report:
        commands.append((
            "government-report",
            [sys.executable, str(EXAMPLES_DIR / "10_create_government_report.py")],
        ))
        government_report_output = EXAMPLES_DIR / "out" / "10_government_report.hwpx"
        check_code = (
            "from hwpx import HwpxDocument, inspect_document_authoring_quality; "
            "from hwpx.tools.package_validator import validate_editor_open_safety, validate_package; "
            "from hwpx.tools.validator import validate_document; "
            "from hwpx.tools.report_parser import parse_government_report_text; "
            "from hwpx.tools.report_utils import format_krw_hangul; "
            f"path = {str(government_report_output)!r}; "
            "doc = HwpxDocument.open(path); "
            "text = doc.export_text(); "
            "doc.close(); "
            "parsed = parse_government_report_text('Ⅰ. 추진 개요\\n□ 주요 성과', title='검증 보고'); "
            "report = inspect_document_authoring_quality(path, quality_profile='government_report'); "
            "checks = ["
            "(validate_package(path).ok, 'package validation failed'), "
            "(validate_editor_open_safety(path).ok, 'editor-open safety failed'), "
            "(validate_document(path).ok, 'document validation failed'), "
            "(report.get('pass') is True, 'authoring quality did not pass'), "
            "(report.get('visual_review_required') is True, 'visual_review_required is not true'), "
            "('AI 활용 교육 추진 현황' in text, 'report text missing'), "
            "('70.0' in text, 'ratio computed value missing'), "
            "(format_krw_hangul(8750000) in text, 'KRW Hangul computed value missing'), "
            "(parsed.get('schemaVersion') == 'hwpx.document_plan.v2', 'parser schema mismatch')"
            "]; "
            "failures = [message for passed, message in checks if not passed]; "
            "raise SystemExit('; '.join(failures) if failures else 0)"
        )
        commands.append((
            "government-report-readback",
            [sys.executable, "-c", check_code],
        ))
    if args.template_formfit:
        template_formfit_output = EXAMPLES_DIR / "out" / "08_template_formfit_filled.hwpx"
        commands.append((
            "template-formfit",
            [sys.executable, str(EXAMPLES_DIR / "08_template_formfit.py")],
        ))
        commands.append((
            "template-formfit-open-safety",
            _open_safety_command(template_formfit_output),
        ))
    if args.visual_review:
        visual_review_evidence.unlink(missing_ok=True)
        if not args.operating_plan:
            commands.append((
                "operating-plan",
                [sys.executable, str(EXAMPLES_DIR / "07_create_operating_plan.py")],
            ))
        commands.append((
            "visual-review-fallback",
            [
                sys.executable,
                str(SCRIPTS_DIR / "visual_review.py"),
                str(EXAMPLES_DIR / "out" / "07_operating_plan.hwpx"),
                "--evidence",
                str(visual_review_evidence),
                "--viewer",
                "none",
                "--status",
                "blocked",
                "--notes",
                "CI fallback smoke: document viewer is intentionally disabled.",
                "--layout-risk",
                "Rendered page breaks and table fit require opened-document review.",
            ],
        ))
    if args.visual_review_batch:
        if visual_review_batch_dir.exists():
            for path in visual_review_batch_dir.glob("*.json"):
                path.unlink()
        if not args.operating_plan and not args.visual_review:
            commands.append((
                "operating-plan",
                [sys.executable, str(EXAMPLES_DIR / "07_create_operating_plan.py")],
            ))
        commands.append((
            "visual-review-batch-fallback",
            [
                sys.executable,
                str(SCRIPTS_DIR / "visual_review_batch.py"),
                "--inputs",
                str(EXAMPLES_DIR / "out" / "07_operating_plan.hwpx"),
                "--evidence-dir",
                str(visual_review_batch_dir),
                "--notes",
                "CI fallback smoke: batch viewer detection is intentionally forced to blocked.",
            ],
            {"HWPX_VIEWER_FORCE": "blocked"},
        ))

    for command in commands:
        label, cmd = command[:2]
        env = command[2] if len(command) > 2 else None
        print(f"[STEP] running {label}: {' '.join(cmd)}")
        result = _run(cmd, env=env)
        if result.stdout:
            _print_block(f"{label.upper()} STDOUT", result.stdout)
        if result.stderr:
            _print_block(f"{label.upper()} STDERR", result.stderr)
        if result.returncode != 0:
            print(f"[ERR] {label} failed with exit code {result.returncode}")
            return result.returncode

    if not OUTPUT_PATH.exists():
        print(f"[ERR] expected output file was not created: {OUTPUT_PATH}")
        return 3

    print(f"[OK] output exists: {OUTPUT_PATH}")
    print("[OK] basic hwpx skill workflow passed")
    if args.proposal:
        print("[OK] proposal generation workflow passed")
    if args.document_plan:
        print("[OK] document-plan generation workflow passed")
    if args.builder:
        print("[OK] builder generation workflow passed")
    if args.operating_plan:
        print("[OK] operating-plan document-plan workflow passed")
    if args.government_report:
        print("[OK] government-report document-plan workflow passed")
    if args.template_formfit:
        print("[OK] template form-fit workflow passed")
    if args.visual_review:
        try:
            evidence = json.loads(visual_review_evidence.read_text(encoding="utf-8"))
            checks = [
                (evidence.get("schemaVersion") == "hwpx.visual-review.v1", "schemaVersion mismatch"),
                (evidence.get("current", {}).get("status") == "blocked", "current.status is not blocked"),
                (
                    evidence.get("summary", {}).get("resolved_visual_review_required") == "blocked",
                    "summary.resolved_visual_review_required is not blocked",
                ),
                (
                    evidence.get("summary", {}).get("ready_for_submission_claim") is False,
                    "summary.ready_for_submission_claim is not false",
                ),
                (evidence.get("viewer", {}).get("available") is False, "viewer.available is not false"),
                (
                    evidence.get("current", {}).get("tool_path", "").endswith("visual_review.py"),
                    "current.tool_path does not end with visual_review.py",
                ),
            ]
            for passed, message in checks:
                if not passed:
                    raise ValueError(message)
        except Exception as exc:
            print(f"[ERR] visual-review fallback evidence validation failed: {exc}")
            return 4
        print("[OK] visual-review fallback evidence workflow passed")
    if args.visual_review_batch:
        try:
            report = json.loads(visual_review_batch_report.read_text(encoding="utf-8"))
            rows = report.get("rows", [])
            evidence_paths = [Path(row.get("evidence", "")) for row in rows]
            checks = [
                (report.get("schemaVersion") == "hwpx.visual-review-batch.v1", "batch schemaVersion mismatch"),
                (report.get("viewer_detection", {}).get("status") == "blocked", "viewer detection is not blocked"),
                (report.get("counts", {}).get("blocked") == len(rows) == 1, "blocked count/row count mismatch"),
                (report.get("counts", {}).get("observed_pass") == 0, "observed_pass count is not zero"),
                (report.get("ready_for_submission_claim") is False, "batch ready_for_submission_claim is not false"),
                (all(path.exists() for path in evidence_paths), "per-file evidence path is missing"),
            ]
            for passed, message in checks:
                if not passed:
                    raise ValueError(message)
            evidence = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
            if evidence.get("current", {}).get("status") != "blocked":
                raise ValueError("per-file evidence current.status is not blocked")
        except Exception as exc:
            print(f"[ERR] visual-review batch fallback validation failed: {exc}")
            return 5
        print("[OK] visual-review batch fallback evidence workflow passed")
    print("[NEXT] try placeholder replacement:")
    print(
        "       python3 examples/03_template_replace.py examples/out/01_created.hwpx "
        "examples/out/03_replaced.hwpx --replace \"학부모님께 안내드립니다.=학부모님께 수정 안내드립니다.\""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
