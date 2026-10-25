#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""fix_namespaces.py

Normalize the namespace declarations of the XML parts in a .hwpx package
after text-level edits.

This is a thin command-line wrapper. The work is python-hwpx's
``hwpx.tools.repair.normalize_package_namespaces``: every ``.xml`` part is
parsed and re-serialized, section and header roots get the full namespace
surface Hancom declares and ``standalone="yes"``, a part that does not parse
keeps its bytes, ``.hpf`` and binary entries are not touched, and ``mimetype``
is stored uncompressed. The output is checked for editor open-safety and
written atomically only when the check passes; otherwise the target is left
as it was. This script only parses arguments, picks the target and prints
the result.

Usage:
  python3 scripts/fix_namespaces.py input.hwpx
  python3 scripts/fix_namespaces.py input.hwpx --out fixed.hwpx
  python3 scripts/fix_namespaces.py input.hwpx --inplace --backup

Exit codes:
  0 success
  1 normalization or open-safety validation failed (target unchanged)
  2 invalid arguments / file not found
  3 not a valid HWPX zip
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

#: The python-hwpx release that ships ``normalize_package_namespaces``.
REQUIRED_CORE = "python-hwpx>=6.10.0"


def _normalize_package_namespaces() -> Any:
    try:
        from hwpx.tools.repair import normalize_package_namespaces
    except ImportError as exc:  # pragma: no cover - depends on the installed core
        raise RuntimeError(f"{REQUIRED_CORE} is required for namespace normalization: {exc}") from exc
    return normalize_package_namespaces


def _publish(data: bytes, target: str) -> None:
    """Gate *data* once more and write it to *target* atomically."""

    from hwpx.quality import QualityPolicy, SavePipeline

    report = SavePipeline().run(data, output_path=target, quality=QualityPolicy.transparent())
    if not report.ok:
        raise RuntimeError("generated HWPX failed open-safety validation: " + report.open_safety.summary)


def _stats(result: Any) -> dict:
    return {
        "total_parts": len(result.entries),
        "xml_parts": len(result.xml_parts),
        "xml_fixed": len(result.normalized_parts),
        "xml_failed": len(result.unparsed_parts),
    }


def _normalize(source: str | bytes) -> Any:
    result = _normalize_package_namespaces()(source)
    if not result.ok:
        raise RuntimeError(
            "generated HWPX failed open-safety validation: " + str(result.open_safety.get("summary", ""))
        )
    return result


def fix_namespaces(
    in_hwpx: str,
    out_hwpx: str,
) -> dict:
    """Normalize namespace declarations and write *out_hwpx* only when it is open-safe.

    Returns stats:
      {
        "total_parts": int,
        "xml_parts": int,
        "xml_fixed": int,
        "xml_failed": int,
      }
    """

    result = _normalize(in_hwpx)
    _publish(result.data, os.path.abspath(out_hwpx))
    return _stats(result)


def validate_open_safety(hwpx_path: str) -> None:
    """Raise when a generated HWPX should not replace an editor-openable file."""

    try:
        from hwpx.tools.package_validator import validate_editor_open_safety
    except Exception as exc:
        raise RuntimeError(
            "python-hwpx>=2.10.3 is required for HWPX open-safety validation"
        ) from exc

    report = validate_editor_open_safety(hwpx_path)
    if not report.ok:
        raise RuntimeError(
            "generated HWPX failed open-safety validation: " + report.summary
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Normalize XML namespaces inside a .hwpx by parsing+re-serializing XML parts "
            "(python-hwpx normalize_package_namespaces). Useful after text-level edits."
        )
    )
    p.add_argument("hwpx", help="Input .hwpx path")
    p.add_argument(
        "--out",
        dest="out",
        default=None,
        help="Output .hwpx path (default: <input>.fixed.hwpx)",
    )
    p.add_argument(
        "--inplace",
        action="store_true",
        help="Write back to the input file (only after the result passes open-safety)",
    )
    p.add_argument(
        "--backup",
        action="store_true",
        help="When using --inplace, create <input>.bak before overwriting",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    in_hwpx = os.path.abspath(args.hwpx)
    if not os.path.exists(in_hwpx):
        print(f"[ERR] file not found: {in_hwpx}", file=sys.stderr)
        return 2
    if not in_hwpx.lower().endswith(".hwpx"):
        print(f"[WARN] input does not end with .hwpx: {in_hwpx}", file=sys.stderr)

    if not zipfile.is_zipfile(in_hwpx):
        print(f"[ERR] not a ZIP file (invalid HWPX): {in_hwpx}", file=sys.stderr)
        return 3

    final_hwpx = in_hwpx if args.inplace else os.path.abspath(args.out or (in_hwpx + ".fixed.hwpx"))

    try:
        result = _normalize(in_hwpx)
        if args.inplace and args.backup:
            bak = in_hwpx + ".bak"
            shutil.copy2(in_hwpx, bak)
            print(f"[OK] backup: {bak}")
        Path(final_hwpx).parent.mkdir(parents=True, exist_ok=True)
        _publish(result.data, final_hwpx)
    except Exception as e:
        print(f"[ERR] failed: {e}", file=sys.stderr)
        return 1

    if args.inplace:
        print(f"[OK] wrote (inplace): {in_hwpx}")
    else:
        print(f"[OK] wrote: {final_hwpx}")

    stats = _stats(result)
    print(
        "[STATS] "
        f"parts={stats['total_parts']} xml={stats['xml_parts']} "
        f"fixed={stats['xml_fixed']} failed={stats['xml_failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
