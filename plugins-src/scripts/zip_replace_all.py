#!/usr/bin/env python3
"""zip_replace_all.py

Replace plain-text placeholders across XML parts in an HWPX container.

This script is intended for template-style replacements where placeholders
exist as text nodes across the package, including table cells.

Usage:
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx --inplace --backup --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B" --auto-fix-ns
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fix_namespaces import fix_namespaces


def _clone_zipinfo(info: zipfile.ZipInfo, *, force_stored: bool = False) -> zipfile.ZipInfo:
    cloned = copy.copy(info)
    if force_stored:
        cloned.compress_type = zipfile.ZIP_STORED
    return cloned


def _same_path(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    left_path = os.path.normcase(str(Path(left).resolve(strict=False)))
    right_path = os.path.normcase(str(Path(right).resolve(strict=False)))
    return left_path == right_path


def _make_temp_hwpx_path(directory: Path, prefix: str) -> str:
    fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".hwpx", dir=directory)
    os.close(fd)
    return temp_path


def parse_replace_args(values: list[str]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"replacement must be OLD=NEW: {value!r}")
        old, new = value.split("=", 1)
        if not old:
            raise ValueError("replacement key must not be empty")
        replacements[old] = new
    if not replacements:
        raise ValueError("at least one replacement is required")
    return replacements


def warn_if_xml_like_keys(replacements: Mapping[str, str]) -> int:
    warnings = 0
    for old in replacements:
        if "<" in old or ">" in old or "</" in old:
            warnings += 1
            print(
                f"[WARN] replacement key looks like XML markup: {old!r}",
                file=sys.stderr,
            )
    return warnings


def zip_replace_all(
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Replace plain strings across XML parts in an HWPX package."""

    stats = {
        "parts": 0,
        "xml_parts": 0,
        "changed_xml": 0,
        "replacements": 0,
        "decode_failed": 0,
    }

    with zipfile.ZipFile(in_hwpx, "r") as zin:
        with zipfile.ZipFile(out_hwpx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                stats["parts"] += 1
                data = zin.read(info.filename)

                if info.filename.lower().endswith(".xml"):
                    stats["xml_parts"] += 1
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        stats["decode_failed"] += 1
                        zout.writestr(_clone_zipinfo(info, force_stored=info.filename == "mimetype"), data)
                        continue

                    original_text = text
                    replaced_here = 0
                    for old, new in replacements.items():
                        count = text.count(old)
                        if count:
                            text = text.replace(old, new)
                            replaced_here += count

                    if text != original_text:
                        stats["changed_xml"] += 1
                        stats["replacements"] += replaced_here
                        data = text.encode("utf-8")

                zout.writestr(_clone_zipinfo(info, force_stored=info.filename == "mimetype"), data)

    return stats


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace plain-text placeholders across XML parts in a .hwpx package. "
            "Use this for template-style global replacements, especially when table cells must be included."
        )
    )
    parser.add_argument("input_hwpx", help="Input .hwpx path")
    parser.add_argument(
        "output_hwpx",
        nargs="?",
        default=None,
        help="Output .hwpx path (omit when using --inplace)",
    )
    parser.add_argument(
        "--replace",
        nargs="+",
        required=True,
        metavar="OLD=NEW",
        help="One or more replacement pairs",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="Write back to the input file using a temporary file internally",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="When overwriting the input file, create <input>.bak before replacing it",
    )
    parser.add_argument(
        "--auto-fix-ns",
        action="store_true",
        help="Run scripts/fix_namespaces.py logic after replacement",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        replacements = parse_replace_args(args.replace)
    except ValueError as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 2

    input_path = Path(args.input_hwpx).resolve()
    if not input_path.exists():
        print(f"[ERR] file not found: {input_path}", file=sys.stderr)
        return 2
    if not zipfile.is_zipfile(input_path):
        print(f"[ERR] not a ZIP file (invalid HWPX): {input_path}", file=sys.stderr)
        return 3

    if args.inplace and args.output_hwpx is not None:
        print("[ERR] do not pass output_hwpx with --inplace", file=sys.stderr)
        return 2
    if not args.inplace and args.output_hwpx is None:
        print("[ERR] output_hwpx is required unless --inplace is used", file=sys.stderr)
        return 2

    target_path = input_path if args.inplace else Path(args.output_hwpx).resolve()
    if not args.inplace:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    needs_temp_output = args.inplace or _same_path(input_path, target_path)
    if needs_temp_output and not args.inplace:
        print(
            f"[WARN] output path matches input; using a temporary file: {target_path}",
            file=sys.stderr,
        )

    warn_if_xml_like_keys(replacements)

    temp_dir = input_path.parent
    replace_out = (
        Path(_make_temp_hwpx_path(temp_dir, "hwpx-replace-"))
        if needs_temp_output or args.auto_fix_ns
        else target_path
    )

    try:
        replace_stats = zip_replace_all(str(input_path), str(replace_out), replacements)
    except Exception as exc:
        print(f"[ERR] replacement failed: {exc}", file=sys.stderr)
        if replace_out != target_path and replace_out.exists():
            replace_out.unlink(missing_ok=True)
        return 1

    final_path = target_path
    ns_stats: dict[str, int] | None = None

    if args.auto_fix_ns:
        ns_out = (
            Path(_make_temp_hwpx_path(temp_dir, "hwpx-ns-"))
            if needs_temp_output
            else target_path
        )
        try:
            ns_stats = fix_namespaces(str(replace_out), str(ns_out))
        except Exception as exc:
            print(f"[ERR] namespace fix failed: {exc}", file=sys.stderr)
            replace_out.unlink(missing_ok=True)
            if ns_out != target_path:
                ns_out.unlink(missing_ok=True)
            return 1
        replace_out.unlink(missing_ok=True)
        produced_path = ns_out
    else:
        produced_path = replace_out

    try:
        if needs_temp_output:
            if args.backup:
                backup_path = input_path.with_suffix(input_path.suffix + ".bak")
                shutil.copy2(input_path, backup_path)
                print(f"[OK] backup: {backup_path}")
            os.replace(produced_path, final_path)
        elif args.backup:
            print("[WARN] --backup is ignored when output does not overwrite input", file=sys.stderr)
    finally:
        if produced_path != final_path and Path(produced_path).exists():
            Path(produced_path).unlink(missing_ok=True)

    print(f"[OK] wrote: {final_path}")
    print(
        "[STATS] "
        f"parts={replace_stats['parts']} xml={replace_stats['xml_parts']} "
        f"changed_xml={replace_stats['changed_xml']} replacements={replace_stats['replacements']} "
        f"decode_failed={replace_stats['decode_failed']}"
    )
    if ns_stats is not None:
        print(
            "[NS] "
            f"parts={ns_stats['total_parts']} xml={ns_stats['xml_parts']} "
            f"fixed={ns_stats['xml_fixed']} failed={ns_stats['xml_failed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
