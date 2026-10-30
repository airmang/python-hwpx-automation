#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prevent Python document/workflow implementation from drifting into skills."""
from __future__ import annotations

import argparse
import ast
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


# The two package-editing support scripts are command-line wrappers around
# python-hwpx's public API (#62). They parse arguments, pick the target and
# print; the package/XML work is core's. Each copy -- the root script and every
# generated bundle copy -- must call its core function and must not grow a ZIP
# or XML editor back: no lxml/xml/re/copy import, no ZipFile, writestr or
# ZipInfo, no zipfile use beyond is_zipfile, and no private hwpx import.
CORE_WRAPPER_SCRIPTS = {
    "zip_replace_all.py": "replace_package_text",
    "fix_namespaces.py": "normalize_package_namespaces",
}
WRAPPER_FORBIDDEN_IMPORTS = ("lxml", "xml", "re", "copy")
WRAPPER_FORBIDDEN_NAMES = frozenset({"ZipFile", "ZipInfo", "writestr", "etree"})


def wrapper_violations(path: Path, relative: str) -> list[str]:
    """Why a core wrapper script at *path* is doing package or XML work itself."""

    violations: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    core_function = CORE_WRAPPER_SCRIPTS[path.name]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in WRAPPER_FORBIDDEN_IMPORTS:
                    violations.append(f"core wrapper imports {alias.name}: {relative}")
                if alias.name == "hwpx" or alias.name.startswith("hwpx."):
                    if any(part.startswith("_") for part in alias.name.split(".")):
                        violations.append(f"core wrapper imports private hwpx module {alias.name}: {relative}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_name = node.module.split(".")[0]
            if root_name in WRAPPER_FORBIDDEN_IMPORTS:
                violations.append(f"core wrapper imports {node.module}: {relative}")
            if root_name == "zipfile":
                violations.append(f"core wrapper imports from zipfile: {relative}")
            if root_name == "hwpx" and (
                any(part.startswith("_") for part in node.module.split("."))
                or any(alias.name.startswith("_") for alias in node.names)
            ):
                violations.append(f"core wrapper imports private hwpx name from {node.module}: {relative}")
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "zipfile"
                and node.attr != "is_zipfile"
            ):
                violations.append(f"core wrapper uses zipfile.{node.attr}: {relative}")
        elif isinstance(node, ast.Name):
            names.add(node.id)
    for name in sorted(WRAPPER_FORBIDDEN_NAMES & names):
        violations.append(f"core wrapper touches ZIP/XML directly ({name}): {relative}")
    if core_function not in names:
        violations.append(f"core wrapper does not call python-hwpx {core_function}: {relative}")
    return violations


def _core_wrapper_paths(root: Path) -> list[Path]:
    paths = [root / "scripts" / name for name in CORE_WRAPPER_SCRIPTS]
    for name in CORE_WRAPPER_SCRIPTS:
        paths.extend(sorted((root / "plugins").rglob(f"scripts/{name}")))
    return [path for path in paths if path.is_file()]


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
    wrappers = _core_wrapper_paths(root)
    for path in wrappers:
        violations.extend(wrapper_violations(path, path.relative_to(root).as_posix()))
    return {
        "ok": not violations,
        "pluginPythonFiles": len(files),
        "vendoredEngineFiles": len(vendored),
        "approvedSupportScripts": sorted(APPROVED_SUPPORT_SCRIPTS),
        "coreWrapperScripts": dict(sorted(CORE_WRAPPER_SCRIPTS.items())),
        "coreWrapperCopies": len(wrappers),
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
