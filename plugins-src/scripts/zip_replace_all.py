#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""zip_replace_all.py

Replace plain-text placeholders in the text of an HWPX container.

For template-style replacements where placeholders sit anywhere in the
package: body, table cells, headers and footers, and ``content.hpf`` metadata.

Only character data (text nodes) of the ``.xml``/``.hpf`` parts is searched.
Element and attribute names, attribute values (font names, sizes, ids),
comments, processing instructions and CDATA are never touched. Keys and values
are plain text: ``&``, ``<`` and ``>`` are escaped on the way in, so a value
can never become markup. A line break in a value becomes ``hp:lineBreak``
inside a paragraph text element (``hp:t``). A key split across two elements
(two runs, say) is not found.

When the installed python-hwpx has ``hwpx.patch.replace_package_text``
(6.10.0 or newer) the replacement is delegated to it; values with a line
break, and older engines, use the built-in text-node replacer below.

Usage:
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx --inplace --backup --replace "{A}=B"
  python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{A}=B" --auto-fix-ns
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fix_namespaces import fix_namespaces, normalize_hwpml_root_bytes, validate_open_safety


_LINESEGARRAY_PATTERN = re.compile(
    r"<(?P<tag>(?:[A-Za-z_][\w.-]*:)?lineSegArray)\b[^>]*>.*?</(?P=tag)>"
    r"|<(?P<empty>(?:[A-Za-z_][\w.-]*:)?lineSegArray)\b[^>]*/>",
    re.IGNORECASE | re.DOTALL,
)


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
        if "<" in old or ">" in old:
            warnings += 1
            print(
                f"[WARN] replacement key looks like XML markup and is matched as plain text only: {old!r}",
                file=sys.stderr,
            )
    return warnings


def _remove_layout_cache(text: str) -> tuple[str, int]:
    """Remove HWPX paragraph line-layout caches from a changed XML part."""

    return _LINESEGARRAY_PATTERN.subn("", text)


# One token per piece of markup; everything between two tokens is character data.
_MARKUP_RE = re.compile(
    r"<!--.*?-->"
    r"|<!\[CDATA\[.*?\]\]>"
    r"|<\?.*?\?>"
    r"|<!(?:[^>\"']|\"[^\"]*\"|'[^']*')*>"
    r"|<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
    re.DOTALL,
)
_TAG_NAME_RE = re.compile(r"<(/?)([A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?)")
_XMLNS_RE = re.compile(r"""\sxmlns:([A-Za-z_][\w.\-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_XML_REFERENCE_RE = re.compile(r"&(#x[0-9A-Fa-f]+|#[0-9]+|amp|lt|gt|quot|apos);")
_XML_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_PARAGRAPH_NS_SUFFIX = "/paragraph"


def _unescape_xml_text(text: str) -> str:
    def resolve(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            if name.startswith("#x"):
                return chr(int(name[2:], 16))
            if name.startswith("#"):
                return chr(int(name[1:]))
        except (ValueError, OverflowError):
            return match.group(0)
        return _XML_ENTITIES[name]

    return _XML_REFERENCE_RE.sub(resolve, text)


def _escape_xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pick_sentinel(*texts: str) -> str:
    """A private-use character that occurs in none of *texts*."""

    for codepoint in range(0xE000, 0xF900):
        candidate = chr(codepoint)
        if not any(candidate in text for text in texts):
            return candidate
    raise ValueError("no free private-use character for line-break marking")


def _replace_in_text_nodes(xml: str, replacements: Mapping[str, str]) -> tuple[str, int]:
    """Replace inside character data only.

    Tags, attribute values, comments, processing instructions and CDATA stay
    byte-for-byte. A line break that a replacement value brings in becomes a
    ``lineBreak`` element when the text sits directly in a paragraph-namespace
    ``t`` element; anywhere else it stays a plain newline.
    """

    normalized = {
        old: new.replace("\r\n", "\n").replace("\r", "\n") for old, new in replacements.items()
    }
    sentinel = _pick_sentinel(xml, *normalized.keys(), *normalized.values())
    marked = {old: new.replace("\n", sentinel) for old, new in normalized.items()}

    # Prefixes are resolved from every xmlns declaration in the part. HWPX parts
    # declare them once on the root; a prefix bound to two URIs is not trusted.
    prefixes: dict[str, str | None] = {}
    for declared in _XMLNS_RE.finditer(xml):
        prefix = declared.group(1)
        uri = declared.group(2) if declared.group(2) is not None else declared.group(3)
        if prefix in prefixes and prefixes[prefix] != uri:
            prefixes[prefix] = None
        else:
            prefixes[prefix] = uri

    def text_element_prefix(qname: str) -> str | None:
        prefix, _, local = qname.rpartition(":")
        uri = prefixes.get(prefix)
        if local == "t" and prefix and uri and uri.endswith(_PARAGRAPH_NS_SUFFIX):
            return prefix
        return None

    pieces: list[str] = []
    stack: list[str] = []
    count = 0
    cursor = 0
    for markup in (*_MARKUP_RE.finditer(xml), None):
        end = len(xml) if markup is None else markup.start()
        segment = xml[cursor:end]
        if segment:
            text = _unescape_xml_text(segment)
            replaced = text
            for old, new in marked.items():
                hits = replaced.count(old)
                if hits:
                    replaced = replaced.replace(old, new)
                    count += hits
            if replaced == text:
                pieces.append(segment)
            else:
                escaped = _escape_xml_text(replaced)
                if sentinel in escaped:
                    prefix = text_element_prefix(stack[-1]) if stack else None
                    escaped = escaped.replace(
                        sentinel, f"<{prefix}:lineBreak/>" if prefix else "\n"
                    )
                pieces.append(escaped)
        if markup is None:
            break
        token = markup.group(0)
        pieces.append(token)
        cursor = markup.end()
        if token.startswith(("<!", "<?")):
            continue
        name = _TAG_NAME_RE.match(token)
        if name is None:
            continue
        if name.group(1):
            if stack:
                stack.pop()
        elif not token.endswith("/>"):
            stack.append(name.group(2))
    return "".join(pieces), count


def _engine_replace_package_text():
    """python-hwpx's text-node replacer, or None when the installed engine has none."""

    try:
        from hwpx.patch import replace_package_text  # type: ignore
    except Exception:
        return None
    return replace_package_text


def _engine_zip_replace_all(
    replace_package_text,
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Delegate to ``hwpx.patch.replace_package_text`` and write its bytes to *out_hwpx*.

    The caller still runs the open-safety check on *out_hwpx* before it
    replaces a user target, so the engine's own gate result is not relied on.
    """

    result = replace_package_text(Path(in_hwpx).read_bytes(), dict(replacements))
    Path(out_hwpx).write_bytes(result.data)
    return {
        "parts": len(result.entries),
        "xml_parts": len(result.scanned_parts),
        "changed_xml": len(result.changed_parts),
        "replacements": int(result.replacements),
        "layout_caches_removed": int(result.layout_caches_removed),
        "decode_failed": len(result.undecodable_parts),
    }


def zip_replace_all(
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Replace plain text in the text nodes of the XML/HPF parts of an HWPX package."""

    output_path = Path(out_hwpx)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path(_make_temp_hwpx_path(output_path.parent, "hwpx-replace-"))
    try:
        stats = _zip_replace_all_unchecked(in_hwpx, temp_path, replacements)
        validate_open_safety(str(temp_path))
        os.replace(temp_path, output_path)
        return stats
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _zip_replace_all_unchecked(
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Write a replaced ZIP without replacing a user target.

    Uses the engine API when it exists and no value carries a line break (the
    engine API escapes text but does not write ``hp:lineBreak``); otherwise the
    built-in text-node replacer.
    """

    has_line_break = any("\n" in new or "\r" in new for new in replacements.values())
    if not has_line_break:
        replace_package_text = _engine_replace_package_text()
        if replace_package_text is not None:
            return _engine_zip_replace_all(replace_package_text, in_hwpx, out_hwpx, replacements)
    return _builtin_zip_replace_all(in_hwpx, out_hwpx, replacements)


def _builtin_zip_replace_all(
    in_hwpx: str | os.PathLike[str],
    out_hwpx: str | os.PathLike[str],
    replacements: Mapping[str, str],
) -> dict[str, int]:
    """Text-node replacement with the standard library only."""

    stats = {
        "parts": 0,
        "xml_parts": 0,
        "changed_xml": 0,
        "replacements": 0,
        "layout_caches_removed": 0,
        "decode_failed": 0,
    }

    with zipfile.ZipFile(in_hwpx, "r") as zin:
        with zipfile.ZipFile(out_hwpx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                stats["parts"] += 1
                data = zin.read(info.filename)

                if info.filename.lower().endswith((".xml", ".hpf")):
                    stats["xml_parts"] += 1
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        stats["decode_failed"] += 1
                        zout.writestr(_clone_zipinfo(info, force_stored=info.filename == "mimetype"), data)
                        continue

                    original_text = text
                    text, replaced_here = _replace_in_text_nodes(text, replacements)

                    if replaced_here and text != original_text:
                        text, removed_caches = _remove_layout_cache(text)
                        stats["changed_xml"] += 1
                        stats["replacements"] += replaced_here
                        stats["layout_caches_removed"] += removed_caches
                        data = normalize_hwpml_root_bytes(
                            info.filename,
                            text.encode("utf-8"),
                        )

                zout.writestr(_clone_zipinfo(info, force_stored=info.filename == "mimetype"), data)

    return stats


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replace plain-text placeholders in the text of a .hwpx package (text nodes only; "
            "attribute values such as font names and sizes are never changed). "
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
    same_output_path = _same_path(input_path, target_path)
    if same_output_path and not args.inplace:
        print(
            f"[WARN] output path matches input; using a temporary file: {target_path}",
            file=sys.stderr,
        )

    warn_if_xml_like_keys(replacements)

    temp_dir = input_path.parent if args.inplace else target_path.parent
    replace_out = Path(_make_temp_hwpx_path(temp_dir, "hwpx-replace-"))

    try:
        replace_stats = _zip_replace_all_unchecked(
            str(input_path),
            str(replace_out),
            replacements,
        )
    except Exception as exc:
        print(f"[ERR] replacement failed: {exc}", file=sys.stderr)
        if replace_out != target_path and replace_out.exists():
            replace_out.unlink(missing_ok=True)
        return 1

    final_path = target_path
    ns_stats: dict[str, int] | None = None

    if args.auto_fix_ns:
        ns_out = Path(_make_temp_hwpx_path(temp_dir, "hwpx-ns-"))
        try:
            ns_stats = fix_namespaces(str(replace_out), str(ns_out))
        except Exception as exc:
            print(f"[ERR] namespace fix failed: {exc}", file=sys.stderr)
            replace_out.unlink(missing_ok=True)
            ns_out.unlink(missing_ok=True)
            return 1
        replace_out.unlink(missing_ok=True)
        produced_path = ns_out
    else:
        produced_path = replace_out

    try:
        validate_open_safety(str(produced_path))
        if args.inplace and args.backup:
            backup_path = input_path.with_suffix(input_path.suffix + ".bak")
            shutil.copy2(input_path, backup_path)
            print(f"[OK] backup: {backup_path}")
        if args.backup and not args.inplace:
            print("[WARN] --backup is ignored when output does not overwrite input", file=sys.stderr)
        os.replace(produced_path, final_path)
    except Exception as exc:
        print(f"[ERR] open-safety validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if produced_path != final_path and Path(produced_path).exists():
            Path(produced_path).unlink(missing_ok=True)

    print(f"[OK] wrote: {final_path}")
    print(
        "[STATS] "
        f"parts={replace_stats['parts']} xml={replace_stats['xml_parts']} "
        f"changed_xml={replace_stats['changed_xml']} replacements={replace_stats['replacements']} "
        f"layout_caches_removed={replace_stats['layout_caches_removed']} "
        f"decode_failed={replace_stats['decode_failed']}"
    )
    if not replace_stats["replacements"]:
        print(
            "[WARN] no text matched; only text nodes are searched (not attribute values, "
            "font names, or keys split across runs)",
            file=sys.stderr,
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
