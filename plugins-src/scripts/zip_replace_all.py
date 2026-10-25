#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""zip_replace_all.py

Replace plain-text placeholders across the XML/HPF parts of an HWPX package.

For template-style replacements where placeholders sit anywhere in the
package: body, table cells, headers and footers, and ``content.hpf``
metadata.

This is a thin command-line wrapper. The work is python-hwpx's
``hwpx.patch.replace_package_text``: only character data (text nodes) of the
``.xml``/``.hpf`` parts is searched — element and attribute names, attribute
values, comments and CDATA are not — keys and values are plain text and are
escaped on the way in, a changed part loses its ``linesegarray`` layout
caches, and every other part keeps its bytes. ``--auto-fix-ns`` runs
``hwpx.tools.repair.normalize_package_namespaces`` on the result. The output
is checked for editor open-safety and written atomically only when the check
passes; otherwise the target is left as it was. This script only parses
arguments, picks the target and prints the result.

Usage:
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx --inplace --backup --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B" --auto-fix-ns
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fix_namespaces import REQUIRED_CORE, _normalize, _publish


def _replace_package_text() -> Any:
    try:
        from hwpx.patch import replace_package_text
    except ImportError as exc:  # pragma: no cover - depends on the installed core
        raise RuntimeError(f"{REQUIRED_CORE} is required for package text replacement: {exc}") from exc
    return replace_package_text


def _same_path(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    left_path = os.path.normcase(str(Path(left).resolve(strict=False)))
    right_path = os.path.normcase(str(Path(right).resolve(strict=False)))
    return left_path == right_path


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
    """Warn about keys that look like markup: only text nodes are searched now."""

    warnings = 0
    for old in replacements:
        if "<" in old or ">" in old:
            warnings += 1
            print(
                f"[WARN] replacement key looks like XML markup and is matched as plain text only: {old!r}",
                file=sys.stderr,
            )
    return warnings


def _replace(source: str | bytes, replacements: Mapping[str, str]) -> Any:
    result = _replace_package_text()(source, replacements)
    if not result.ok:
        raise RuntimeError(
            "generated HWPX failed open-safety validation: " + str(result.open_safety.get("summary", ""))
        )
    return result


def _stats(result: Any) -> dict[str, int]:
    return {
        "parts": len(result.entries),
        "xml_parts": len(result.scanned_parts),
        "changed_xml": len(result.changed_parts),
        "replacements": result.replacements,
        "layout_caches_removed": result.layout_caches_removed,
        "decode_failed": len(result.undecodable_parts),
    }


def zip_replace_all(
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Replace plain text in the text nodes of an HWPX package; write only an open-safe result."""

    result = _replace(str(in_hwpx), replacements)
    output_path = Path(out_hwpx)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _publish(result.data, str(output_path))
    return _stats(result)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace plain-text placeholders in the text of a .hwpx package (python-hwpx "
            "replace_package_text). Use this for template-style global replacements, "
            "especially when table cells must be included."
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
        help="Write back to the input file (only after the result passes open-safety)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="When overwriting the input file, create <input>.bak before replacing it",
    )
    parser.add_argument(
        "--auto-fix-ns",
        action="store_true",
        help="Also normalize namespaces (python-hwpx normalize_package_namespaces)",
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
    if _same_path(input_path, target_path) and not args.inplace:
        print(
            f"[WARN] output path matches input; it is replaced only after validation: {target_path}",
            file=sys.stderr,
        )

    warn_if_xml_like_keys(replacements)

    try:
        result = _replace(str(input_path), replacements)
    except Exception as exc:
        print(f"[ERR] replacement failed: {exc}", file=sys.stderr)
        return 1
    data = result.data

    ns_result = None
    if args.auto_fix_ns:
        try:
            ns_result = _normalize(data)
        except Exception as exc:
            print(f"[ERR] namespace fix failed: {exc}", file=sys.stderr)
            return 1
        data = ns_result.data

    try:
        if args.inplace and args.backup:
            backup_path = input_path.with_suffix(input_path.suffix + ".bak")
            shutil.copy2(input_path, backup_path)
            print(f"[OK] backup: {backup_path}")
        if args.backup and not args.inplace:
            print("[WARN] --backup is ignored when output does not overwrite input", file=sys.stderr)
        _publish(data, str(target_path))
    except Exception as exc:
        print(f"[ERR] open-safety validation failed: {exc}", file=sys.stderr)
        return 1

    stats = _stats(result)
    print(f"[OK] wrote: {target_path}")
    print(
        "[STATS] "
        f"parts={stats['parts']} xml={stats['xml_parts']} "
        f"changed_xml={stats['changed_xml']} replacements={stats['replacements']} "
        f"layout_caches_removed={stats['layout_caches_removed']} "
        f"decode_failed={stats['decode_failed']}"
    )
    if ns_result is not None:
        print(
            "[NS] "
            f"parts={len(ns_result.entries)} xml={len(ns_result.xml_parts)} "
            f"fixed={len(ns_result.normalized_parts)} failed={len(ns_result.unparsed_parts)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
