#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prevent Python document/workflow implementation from drifting into skills."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

APPROVED_SUPPORT_SCRIPTS = frozenset(
    {
        "detect_hwpx_viewer.py",
        "fix_namespaces.py",
        "quickcheck.py",
        "task_eval_harness.py",
        "text_extract.py",
        "visual_review.py",
        "visual_review_batch.py",
        "zip_replace_all.py",
    }
)


def _vendored_engine_files(root: Path) -> set[Path]:
    """Published engine source unpacked by scripts/vendor_claude_engine.py, byte-identical to VENDOR.json.

    It is the released python-hwpx / python-hwpx-automation itself, not Python
    written for the skill, so only files whose sha256 matches the manifest are
    exempt. An edited or added file under engine/ is still a violation.
    """
    exempt: set[Path] = set()
    for manifest_path in (root / "plugins").glob("*/*/skills/*/engine/VENDOR.json"):
        engine = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel, digest in manifest.get("files", {}).items():
            path = engine / rel
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                exempt.add(path.resolve())
    return exempt


def evaluate(root: Path) -> dict[str, Any]:
    violations: list[str] = []
    files = sorted((root / "plugins").rglob("*.py"))
    vendored = _vendored_engine_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if "examples" in parts or path.resolve() in vendored:
            continue
        if "scripts" in parts and path.name in APPROVED_SUPPORT_SCRIPTS:
            continue
        violations.append(f"unapproved Python implementation in skill bundle: {relative}")
    return {
        "ok": not violations,
        "pluginPythonFiles": len(files),
        "vendoredEngineFiles": len(vendored),
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
