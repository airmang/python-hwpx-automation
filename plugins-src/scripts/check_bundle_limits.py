#!/usr/bin/env python3
"""Check the Claude plugin directory limits before and after a bundle build.

Claude's plugin directory reads at most 256 KiB per file and 512 files per
plugin. The Claude bundle vendors the python-hwpx and python-hwpx-automation
sources (``skills/hwpx/engine``), so the limits bind the *engine* packages, not
only this plugin source. Issue #66: core 6.9 grew ``_glyph_table.py`` past
256 KiB and the runtime refresh stalled for weeks.

Two modes:

* default: check the built bundle ``plugins/claude/hwpx-plugin`` (after
  ``build_hwpx_plugins.py``), same rule as ``vendor_claude_engine.py --check``.
* ``--engine-src PKG_DIR`` (repeatable): *forecast* the bundle for engine
  sources that are not on PyPI yet, e.g. the core 7.0 and automation 8.0
  candidates. Applies the vendoring filters (no ``.pyi``, no ``py.typed``, no
  ``__pycache__``) and adds them to the non-engine files of the current bundle.

    python scripts/check_bundle_limits.py
    python scripts/check_bundle_limits.py --engine-src ../../python-hwpx/src/hwpx \\
        --engine-src ../src/hwpx_automation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
ENGINE_REL = Path("skills") / "hwpx" / "engine"
MAX_FILE_BYTES = 256 * 1024
MAX_PLUGIN_FILES = 512
# Kept by vendoring per wheel/document: dist-info METADATA, LICENSE, NOTICE-like
# files and the two core docs plus VENDOR.json. Measured on the 6.12/7.5 engine.
ENGINE_OVERHEAD_FILES = 3 + 3 + 2 + 1
SKIPPED_SUFFIXES = (".pyi", ".pyc")
SKIPPED_NAMES = {"py.typed"}
# Files of the vendored tomli (Python < 3.11 shim), measured on 2.4.1.
TOMLI_FILES = 4 + 2


def _bundle_files(bundle: Path) -> list[Path]:
    return [
        p for p in bundle.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and "examples/out" not in p.as_posix()
    ]


def _engine_files(package_dir: Path) -> list[Path]:
    return [
        p for p in package_dir.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.name not in SKIPPED_NAMES
        and not p.name.endswith(SKIPPED_SUFFIXES)
    ]


def check_built(bundle: Path) -> list[str]:
    if not bundle.is_dir():
        return [f"{bundle} missing; run scripts/build_hwpx_plugins.py first"]
    files = _bundle_files(bundle)
    problems = [
        f"{p.relative_to(bundle).as_posix()} is {p.stat().st_size} bytes (> {MAX_FILE_BYTES})"
        for p in files if p.stat().st_size > MAX_FILE_BYTES
    ]
    if len(files) > MAX_PLUGIN_FILES:
        problems.append(f"bundle has {len(files)} files (> {MAX_PLUGIN_FILES})")
    print(f"built bundle: {len(files)} files, largest "
          f"{max((p.stat().st_size for p in files), default=0)} bytes")
    return problems


def forecast(bundle: Path, engine_sources: list[Path]) -> list[str]:
    base = [p for p in _bundle_files(bundle) if ENGINE_REL not in p.relative_to(bundle).parents
            and p.relative_to(bundle) != ENGINE_REL] if bundle.is_dir() else []
    problems: list[str] = []
    engine_count = ENGINE_OVERHEAD_FILES + TOMLI_FILES
    for src in engine_sources:
        files = _engine_files(src)
        engine_count += len(files)
        big = sorted(((p.stat().st_size, p) for p in files if p.stat().st_size > MAX_FILE_BYTES), reverse=True)
        problems += [f"{src.name}/{p.relative_to(src).as_posix()} is {size} bytes (> {MAX_FILE_BYTES})"
                     for size, p in big]
        largest = max((p.stat().st_size for p in files), default=0)
        print(f"engine source {src}: {len(files)} files, largest {largest} bytes")
    total = len(base) + engine_count
    print(f"forecast: {len(base)} non-engine bundle files + {engine_count} engine files = {total} "
          f"(limit {MAX_PLUGIN_FILES}, headroom {MAX_PLUGIN_FILES - total})")
    if not base:
        problems.append("no built bundle to take the non-engine files from; run build_hwpx_plugins.py")
    if total > MAX_PLUGIN_FILES:
        problems.append(f"forecast bundle has {total} files (> {MAX_PLUGIN_FILES})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--engine-src", type=Path, action="append", default=[],
                        help="package directory to forecast (hwpx/, hwpx_automation/)")
    args = parser.parse_args(argv)
    problems = forecast(args.bundle, args.engine_src) if args.engine_src else check_built(args.bundle)
    for problem in problems:
        print(f"[FAIL] {problem}")
    if not problems:
        print("[OK] Claude plugin directory limits")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
