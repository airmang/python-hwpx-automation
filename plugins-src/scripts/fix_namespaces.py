#!/usr/bin/env python3
"""fix_namespaces.py

Re-serialize XML parts inside a .hwpx (ZIP) to normalize namespace
prefix declarations after ZIP-level text replacements (hwpx skill v3).

Why:
- After raw string replacement inside XML parts, namespace declarations can
  become inconsistent, duplicated, or partially removed.
- Parsing with lxml and re-serializing makes namespace mappings consistent.

This script is intentionally small and dependency-light.

Usage:
  python3 scripts/fix_namespaces.py input.hwpx
  python3 scripts/fix_namespaces.py input.hwpx --out fixed.hwpx
  python3 scripts/fix_namespaces.py input.hwpx --inplace --backup

Exit codes:
  0 success
  2 invalid arguments / file not found
  3 not a valid HWPX zip
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile


def fix_namespaces(in_hwpx: str, out_hwpx: str) -> dict:
    """Normalize namespace declarations by parsing+serializing XML parts.

    Returns stats:
      {
        "total_parts": int,
        "xml_parts": int,
        "xml_fixed": int,
        "xml_failed": int,
      }
    """

    # Import lazily so --help works without lxml installed.
    try:
        from lxml import etree  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "lxml is required. Install: pip install lxml\n" f"Import error: {e}"
        )

    stats = {"total_parts": 0, "xml_parts": 0, "xml_fixed": 0, "xml_failed": 0}

    # Copy across ZIP entries while normalizing XML parts.
    with zipfile.ZipFile(in_hwpx, "r") as zin:
        with zipfile.ZipFile(out_hwpx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                stats["total_parts"] += 1
                data = zin.read(item.filename)

                if item.filename.lower().endswith(".xml"):
                    stats["xml_parts"] += 1
                    try:
                        # lxml accepts bytes; keep encoding as UTF-8 on output.
                        root = etree.fromstring(data)
                        data2 = etree.tostring(
                            root,
                            encoding="utf-8",
                            xml_declaration=True,
                            standalone=None,
                        )
                        if data2 != data:
                            stats["xml_fixed"] += 1
                        data = data2
                    except Exception:
                        # Keep original bytes if parsing fails.
                        stats["xml_failed"] += 1

                # Preserve filename; ZipInfo metadata is not strictly required for HWPX.
                zout.writestr(item.filename, data)

    return stats


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Normalize XML namespaces inside a .hwpx by parsing+re-serializing XML parts. "
            "Useful after ZIP-level string replacement."
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
        help="Write back to the input file (uses a temporary file internally)",
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

    if args.inplace:
        out_hwpx = in_hwpx + ".ns_tmp.hwpx"
    else:
        out_hwpx = os.path.abspath(args.out or (in_hwpx + ".fixed.hwpx"))

    try:
        stats = fix_namespaces(in_hwpx, out_hwpx)
    except Exception as e:
        print(f"[ERR] failed: {e}", file=sys.stderr)
        return 1

    if args.inplace:
        if args.backup:
            bak = in_hwpx + ".bak"
            shutil.copy2(in_hwpx, bak)
            print(f"[OK] backup: {bak}")
        os.replace(out_hwpx, in_hwpx)
        print(f"[OK] wrote (inplace): {in_hwpx}")
    else:
        print(f"[OK] wrote: {out_hwpx}")

    print(
        "[STATS] "
        f"parts={stats['total_parts']} xml={stats['xml_parts']} "
        f"fixed={stats['xml_fixed']} failed={stats['xml_failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
