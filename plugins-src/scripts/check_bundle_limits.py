#!/usr/bin/env python3
"""Check the Claude plugin directory limits before and after a bundle build.

Claude's plugin directory reads at most 256 KiB per file and 512 files per
plugin. The Claude bundle vendors the python-hwpx and python-hwpx-automation
sources (``skills/hwpx/engine``) for the chat path, so the limits bind the
*engine* packages, not only this plugin source. Issue #66: core 6.9 grew
``_glyph_table.py`` past 256 KiB and the runtime refresh stalled for weeks.

The file-count gate keeps a margin (``--min-headroom``, default 32) below 512 so
one ordinary core or automation release that adds a few modules does not break
the next bundle build: it fails at 481 files, while the directory only rejects
at 513.

Two modes:

* default: check the built bundle ``plugins/claude/hwpx-plugin`` (after
  ``build_hwpx_plugins.py``).
* ``--engine-src PKG_DIR`` (repeatable): *forecast* the bundle for engine
  sources that are not on PyPI yet, e.g. the core 7.0 and automation 8.0
  candidates. Applies the same vendoring filters as ``vendor_claude_engine.py``
  (no ``.pyi``/``py.typed``/caches, ``EXCLUDED_ENGINE_MEMBERS`` left out) and
  the same import guard, then adds the non-engine files of the current bundle.

    python scripts/check_bundle_limits.py
    python scripts/check_bundle_limits.py --engine-src ../../python-hwpx/src/hwpx \\
        --engine-src ../src/hwpx_automation
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
ENGINE_REL = Path("skills") / "hwpx" / "engine"
MAX_FILE_BYTES = 256 * 1024
MAX_PLUGIN_FILES = 512
DEFAULT_MIN_HEADROOM = 32
# Kept by vendoring besides the two packages: dist-info METADATA/LICENSE/NOTICE
# per engine wheel, the two core documents, VENDOR.json, and tomli (4 modules +
# METADATA + LICENSE). Measured on the 6.12/7.5 engine.
ENGINE_OVERHEAD_FILES = 3 + 3 + 2 + 1 + 6
SKIPPED_SUFFIXES = (".pyi", ".pyc")
SKIPPED_NAMES = {"py.typed"}

_spec = importlib.util.spec_from_file_location("vendor_claude_engine", Path(__file__).with_name("vendor_claude_engine.py"))
assert _spec and _spec.loader
vendor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vendor)


def _bundle_files(bundle: Path) -> list[Path]:
    return [
        p for p in bundle.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and "examples/out" not in p.as_posix()
    ]


def _engine_files(package_dir: Path) -> list[Path]:
    kept = []
    for p in package_dir.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts or p.name in SKIPPED_NAMES or p.name.endswith(SKIPPED_SUFFIXES):
            continue
        member = p.relative_to(package_dir.parent).as_posix()
        if vendor.is_excluded(member):
            continue
        kept.append(p)
    return kept


def _count_problems(total: int, min_headroom: int) -> list[str]:
    if total > MAX_PLUGIN_FILES:
        return [f"bundle has {total} files (> {MAX_PLUGIN_FILES}, the directory limit)"]
    if MAX_PLUGIN_FILES - total < min_headroom:
        return [f"bundle has {total} files: headroom {MAX_PLUGIN_FILES - total} < {min_headroom}; "
                "leave more modules out of the engine or trim the skill before the limit breaks"]
    return []


def check_built(bundle: Path, min_headroom: int) -> list[str]:
    if not bundle.is_dir():
        return [f"{bundle} missing; run scripts/build_hwpx_plugins.py first"]
    files = _bundle_files(bundle)
    problems = [
        f"{p.relative_to(bundle).as_posix()} is {p.stat().st_size} bytes (> {MAX_FILE_BYTES})"
        for p in files if p.stat().st_size > MAX_FILE_BYTES
    ]
    problems += _count_problems(len(files), min_headroom)
    print(f"built bundle: {len(files)} files (headroom {MAX_PLUGIN_FILES - len(files)}), largest "
          f"{max((p.stat().st_size for p in files), default=0)} bytes")
    return problems


def forecast(bundle: Path, engine_sources: list[Path], min_headroom: int) -> list[str]:
    base = []
    if bundle.is_dir():
        engine_dir = bundle / ENGINE_REL
        base = [p for p in _bundle_files(bundle) if engine_dir not in p.parents]
    problems: list[str] = []
    engine_count = ENGINE_OVERHEAD_FILES
    for src in engine_sources:
        files = _engine_files(src)
        engine_count += len(files)
        problems += [f"{src.name}/{p.relative_to(src).as_posix()} is {p.stat().st_size} bytes (> {MAX_FILE_BYTES})"
                     for p in files if p.stat().st_size > MAX_FILE_BYTES]
        largest = max((p.stat().st_size for p in files), default=0)
        print(f"engine source {src}: {len(files)} files kept, largest {largest} bytes")
    problems += vendor.excluded_imports(sorted({src.parent for src in engine_sources}))
    total = len(base) + engine_count
    print(f"forecast: {len(base)} non-engine bundle files + {engine_count} engine files = {total} "
          f"(limit {MAX_PLUGIN_FILES}, headroom {MAX_PLUGIN_FILES - total})")
    if not base:
        problems.append("no built bundle to take the non-engine files from; run build_hwpx_plugins.py")
    problems += _count_problems(total, min_headroom)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--engine-src", type=Path, action="append", default=[],
                        help="package directory to forecast (hwpx/, hwpx_automation/)")
    parser.add_argument("--min-headroom", type=int, default=DEFAULT_MIN_HEADROOM)
    args = parser.parse_args(argv)
    problems = (forecast(args.bundle, args.engine_src, args.min_headroom) if args.engine_src
                else check_built(args.bundle, args.min_headroom))
    for problem in problems:
        print(f"[FAIL] {problem}")
    if not problems:
        print("[OK] Claude plugin directory limits")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
