#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
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
import copy
import os
import shutil
import sys
import tempfile
import zipfile

HWPML_COMPAT_ROOT_NAMESPACES = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}


def _clone_zipinfo(info: zipfile.ZipInfo, *, force_stored: bool = False) -> zipfile.ZipInfo:
    cloned = copy.copy(info)
    if force_stored:
        cloned.compress_type = zipfile.ZIP_STORED
    return cloned


def _is_hwpml_root_part(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return (name.startswith("section") or name.startswith("header")) and name.endswith(".xml")


def _local_name(element) -> str:
    tag = getattr(element, "tag", "")
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _serialize_xml_part(path: str, root, etree) -> bytes:
    if _is_hwpml_root_part(path) and _local_name(root) in {"sec", "head"}:
        wrapped = etree.Element(root.tag, nsmap=HWPML_COMPAT_ROOT_NAMESPACES)
        wrapped.attrib.update(root.attrib)
        wrapped.text = root.text
        wrapped.tail = root.tail
        for child in root:
            wrapped.append(child)
        return etree.tostring(
            wrapped,
            encoding="UTF-8",
            xml_declaration=True,
            standalone=True,
        )
    return etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        standalone=None,
    )


def normalize_hwpml_root_bytes(path: str, data: bytes) -> bytes:
    """Normalize section/header root declarations when the payload is parseable XML."""

    if not _is_hwpml_root_part(path):
        return data
    try:
        from lxml import etree  # type: ignore
    except Exception:
        return data
    try:
        root = etree.fromstring(data)
    except Exception:
        return data
    if _local_name(root) not in {"sec", "head"}:
        return data
    return _serialize_xml_part(path, root, etree)


def fix_namespaces(
    in_hwpx: str,
    out_hwpx: str,
) -> dict:
    """Normalize namespace declarations by parsing+serializing XML parts.

    Returns stats:
      {
        "total_parts": int,
        "xml_parts": int,
        "xml_fixed": int,
        "xml_failed": int,
      }
    """

    final_hwpx = os.path.abspath(out_hwpx)
    temp_dir = os.path.dirname(final_hwpx) or os.getcwd()
    temp_hwpx = _make_temp_hwpx_path(temp_dir, "hwpx-ns-")
    try:
        stats = _fix_namespaces_unchecked(in_hwpx, temp_hwpx)
        validate_open_safety(temp_hwpx)
        os.replace(temp_hwpx, final_hwpx)
        return stats
    except BaseException:
        try:
            os.unlink(temp_hwpx)
        except OSError:
            pass
        raise


def _fix_namespaces_unchecked(in_hwpx: str, out_hwpx: str) -> dict:
    """Write a namespace-normalized ZIP without replacing a user target."""

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
                        data2 = _serialize_xml_part(item.filename, root, etree)
                        if data2 != data:
                            stats["xml_fixed"] += 1
                        data = data2
                    except Exception:
                        # Keep original bytes if parsing fails.
                        stats["xml_failed"] += 1

                force_stored = item.filename == "mimetype"
                zout.writestr(_clone_zipinfo(item, force_stored=force_stored), data)

    return stats


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


def _make_temp_hwpx_path(directory: str, prefix: str) -> str:
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".hwpx", dir=directory)
    os.close(fd)
    return temp_path


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

    final_hwpx = in_hwpx if args.inplace else os.path.abspath(args.out or (in_hwpx + ".fixed.hwpx"))
    temp_dir = os.path.dirname(final_hwpx) or os.getcwd()
    out_hwpx = _make_temp_hwpx_path(temp_dir, "hwpx-ns-")

    try:
        stats = _fix_namespaces_unchecked(in_hwpx, out_hwpx)
        validate_open_safety(out_hwpx)
    except Exception as e:
        print(f"[ERR] failed: {e}", file=sys.stderr)
        try:
            os.unlink(out_hwpx)
        except OSError:
            pass
        return 1

    if args.inplace:
        if args.backup:
            bak = in_hwpx + ".bak"
            shutil.copy2(in_hwpx, bak)
            print(f"[OK] backup: {bak}")
        os.replace(out_hwpx, final_hwpx)
        print(f"[OK] wrote (inplace): {in_hwpx}")
    else:
        os.replace(out_hwpx, final_hwpx)
        print(f"[OK] wrote: {final_hwpx}")

    print(
        "[STATS] "
        f"parts={stats['total_parts']} xml={stats['xml_parts']} "
        f"fixed={stats['xml_fixed']} failed={stats['xml_failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
