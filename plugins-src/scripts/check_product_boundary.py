#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prevent Python document/workflow implementation from drifting into skills."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

APPROVED_SUPPORT_SCRIPTS = frozenset(
    {
        "fix_namespaces.py",
        "quickcheck.py",
        "task_eval_harness.py",
        "text_extract.py",
        "visual_review.py",
        "zip_replace_all.py",
    }
)


def evaluate(root: Path) -> dict[str, Any]:
    violations: list[str] = []
    files = sorted((root / "plugins").rglob("*.py"))
    for path in files:
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if "examples" in parts:
            continue
        if "scripts" in parts and path.name in APPROVED_SUPPORT_SCRIPTS:
            continue
        violations.append(f"unapproved Python implementation in skill bundle: {relative}")
    return {
        "ok": not violations,
        "pluginPythonFiles": len(files),
        "approvedSupportScripts": sorted(APPROVED_SUPPORT_SCRIPTS),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    report = evaluate(args.root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
