#!/usr/bin/env python3
"""quickcheck.py

Run a beginner-friendly end-to-end sanity check for hwpx-skill.

What it verifies:
1. Required Python packages import successfully
2. Example document creation works
3. Example inspection works on the created document
4. CLI text extraction works on the created document
5. Optional document-plan/proposal generation paths work when requested
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCRIPTS_DIR = ROOT / "scripts"
OUTPUT_PATH = EXAMPLES_DIR / "out" / "01_created.hwpx"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def _print_block(label: str, output: str) -> None:
    print(f"[{label}]")
    text = output.rstrip()
    if text:
        print(text)
    else:
        print("(no output)")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hwpx-skill sanity checks")
    parser.add_argument("--proposal", action="store_true", help="also run the proposal-generation preset example")
    parser.add_argument("--document-plan", action="store_true", help="also run the declarative document-plan generation example")
    parser.add_argument(
        "--operating-plan",
        action="store_true",
        help="also run the operating-plan document-plan quality example",
    )
    parser.add_argument(
        "--template-formfit",
        action="store_true",
        help="also run the template-preserving form-fit example",
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

    commands = [
        (
            "create",
            [sys.executable, str(EXAMPLES_DIR / "01_create_and_save.py")],
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
        commands.append((
            "proposal",
            [sys.executable, str(EXAMPLES_DIR / "04_create_proposal.py")],
        ))
    if args.document_plan:
        commands.append((
            "document-plan",
            [sys.executable, str(EXAMPLES_DIR / "06_create_from_document_plan.py")],
        ))
    if args.operating_plan:
        commands.append((
            "operating-plan",
            [sys.executable, str(EXAMPLES_DIR / "07_create_operating_plan.py")],
        ))
        operating_plan_output = EXAMPLES_DIR / "out" / "07_operating_plan.hwpx"
        check_code = (
            "from hwpx import inspect_operating_plan_quality; "
            f"report = inspect_operating_plan_quality({str(operating_plan_output)!r}); "
            "assert report['report_version'] == 'operating-plan-quality-v1'; "
            "assert report['status'] == 'ready'; "
            "assert report['visual_review_required'] is True"
        )
        commands.append((
            "operating-plan-file-only-quality",
            [sys.executable, "-c", check_code],
        ))
    if args.template_formfit:
        commands.append((
            "template-formfit",
            [sys.executable, str(EXAMPLES_DIR / "08_template_formfit.py")],
        ))

    for label, cmd in commands:
        print(f"[STEP] running {label}: {' '.join(cmd)}")
        result = _run(cmd)
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
    if args.operating_plan:
        print("[OK] operating-plan document-plan workflow passed")
    if args.template_formfit:
        print("[OK] template form-fit workflow passed")
    print("[NEXT] try placeholder replacement:")
    print(
        "       python3 examples/03_template_replace.py examples/out/01_created.hwpx "
        "examples/out/03_replaced.hwpx --replace \"학부모님께 안내드립니다.=학부모님께 수정 안내드립니다.\""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
