# SPDX-License-Identifier: Apache-2.0
"""Split-run aware HWPX form filling helpers.

The helpers in this module are a clean-room implementation based on local
tests and verified public behavior descriptions. They operate on one section
XML document at a time, preserving run structure while editing placeholder
fragments inside ``hp:t`` text nodes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import lxml.etree as etree

__all__ = [
    "MISSING_CHAR_PR_ID_REF",
    "PLACEHOLDER_RE",
    "FillReport",
    "HeterogeneousWarning",
    "Placeholder",
    "TextFragment",
    "fill_section_bytes",
    "find_split_placeholders",
    "heterogeneous_warnings",
]

PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_.:-]+\}\}")
MISSING_CHAR_PR_ID_REF = "<missing>"


@dataclass(frozen=True)
class TextFragment:
    paragraph_index: int
    run_index: int
    text_index: int
    char_pr_id_ref: str | None
    local_start: int
    local_end: int


@dataclass(frozen=True)
class Placeholder:
    key: str
    paragraph_index: int
    start: int
    end: int
    split: bool
    charprid_refs: tuple[str, ...]
    fragments: tuple[TextFragment, ...]


@dataclass(frozen=True)
class HeterogeneousWarning:
    key: str
    paragraph_index: int
    charprid_refs: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class FillReport:
    replacements: int
    placeholders_found: int
    missing_keys: tuple[str, ...]
    warnings: tuple[HeterogeneousWarning, ...]


@dataclass(frozen=True)
class _TextNode:
    element: etree._Element
    text: str
    run_index: int
    text_index: int
    char_pr_id_ref: str | None
    start: int
    end: int


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _parse_section(section_bytes: bytes) -> etree._Element:
    try:
        return etree.fromstring(section_bytes)
    except etree.XMLSyntaxError as exc:
        raise ValueError("invalid section XML") from exc


def _iter_paragraphs(root: etree._Element) -> list[etree._Element]:
    return [element for element in root.iter() if _local_name(element.tag) == "p"]


def _has_nested_block_ancestor(
    run: etree._Element,
    element: etree._Element,
) -> bool:
    parent = element.getparent()
    while parent is not None and parent is not run:
        if _local_name(parent.tag) in {"p", "subList", "tbl", "tr", "tc"}:
            return True
        parent = parent.getparent()
    return False


def _iter_run_text_elements(run: etree._Element) -> list[etree._Element]:
    elements: list[etree._Element] = []
    for element in run.iter():
        if _local_name(element.tag) != "t":
            continue
        if _has_nested_block_ancestor(run, element):
            continue
        elements.append(element)
    return elements


def _ensure_plain_text_element(element: etree._Element) -> None:
    if len(element) == 0:
        return
    text_content = "".join(element.itertext())
    if "{{" in text_content or "}}" in text_content:
        raise ValueError("inline hp:t placeholder content is not supported")


def _paragraph_text_nodes(paragraph: etree._Element) -> list[_TextNode]:
    nodes: list[_TextNode] = []
    cursor = 0
    text_index = 0
    runs = [element for element in paragraph if _local_name(element.tag) == "run"]
    for run_index, run in enumerate(runs):
        char_pr_id_ref = run.get("charPrIDRef")
        for child in _iter_run_text_elements(run):
            _ensure_plain_text_element(child)
            text = child.text or ""
            start = cursor
            cursor += len(text)
            nodes.append(
                _TextNode(
                    element=child,
                    text=text,
                    run_index=run_index,
                    text_index=text_index,
                    char_pr_id_ref=char_pr_id_ref,
                    start=start,
                    end=cursor,
                )
            )
            text_index += 1
    return nodes


def _unique_refs(nodes: Sequence[_TextNode]) -> tuple[str, ...]:
    refs: list[str] = []
    for node in nodes:
        ref = (
            node.char_pr_id_ref
            if node.char_pr_id_ref is not None
            else MISSING_CHAR_PR_ID_REF
        )
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _placeholder_from_match(
    paragraph_index: int,
    nodes: Sequence[_TextNode],
    match: re.Match[str],
) -> Placeholder | None:
    start, end = match.span()
    touched = [node for node in nodes if node.start < end and node.end > start]
    if not touched:
        return None

    fragments = tuple(
        TextFragment(
            paragraph_index=paragraph_index,
            run_index=node.run_index,
            text_index=node.text_index,
            char_pr_id_ref=node.char_pr_id_ref,
            local_start=max(start, node.start) - node.start,
            local_end=min(end, node.end) - node.start,
        )
        for node in touched
    )
    run_indexes = {node.run_index for node in touched}
    return Placeholder(
        key=match.group(0),
        paragraph_index=paragraph_index,
        start=start,
        end=end,
        split=len(run_indexes) > 1,
        charprid_refs=_unique_refs(touched),
        fragments=fragments,
    )


def _find_placeholders_in_nodes(
    paragraph_index: int,
    nodes: Sequence[_TextNode],
) -> list[Placeholder]:
    logical = "".join(node.text for node in nodes)
    placeholders: list[Placeholder] = []
    for match in PLACEHOLDER_RE.finditer(logical):
        placeholder = _placeholder_from_match(paragraph_index, nodes, match)
        if placeholder is not None:
            placeholders.append(placeholder)
    return placeholders


def find_split_placeholders(section_bytes: bytes) -> list[Placeholder]:
    """Find ``{{key}}`` placeholders in section XML.

    Text is evaluated paragraph-by-paragraph, so placeholders split across
    paragraph boundaries are intentionally not detected.
    """

    root = _parse_section(section_bytes)
    results: list[Placeholder] = []
    for paragraph_index, paragraph in enumerate(_iter_paragraphs(root)):
        nodes = _paragraph_text_nodes(paragraph)
        if nodes:
            results.extend(_find_placeholders_in_nodes(paragraph_index, nodes))
    return results


def heterogeneous_warnings(
    placeholders: Sequence[Placeholder],
) -> list[HeterogeneousWarning]:
    """Report placeholders that span multiple character property references."""

    warnings: list[HeterogeneousWarning] = []
    for placeholder in placeholders:
        if len(placeholder.charprid_refs) <= 1:
            continue
        refs = ", ".join(placeholder.charprid_refs)
        warnings.append(
            HeterogeneousWarning(
                key=placeholder.key,
                paragraph_index=placeholder.paragraph_index,
                charprid_refs=placeholder.charprid_refs,
                message=(
                    f"{placeholder.key} crosses multiple charPrIDRef values "
                    f"in paragraph {placeholder.paragraph_index}: {refs}"
                ),
            )
        )
    return warnings


def _remove_linesegarray(paragraph: etree._Element) -> None:
    for element in list(paragraph.iter()):
        if _local_name(element.tag).lower() != "linesegarray":
            continue
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


# Characters XML 1.0 cannot carry in a text node. A value holding one used to
# abort the whole fill with ``ValueError: All strings must be XML compatible``
# (audit ENG-19); python-hwpx's own setters drop them, and so does this path.
_ILLEGAL_TEXT_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_TEXT_MARK_SPLIT = re.compile("(\t|\r\n|\r|\n)")


def _write_replacement(
    text_element: etree._Element, before: str, replacement: str, after: str
) -> None:
    """Write ``before + replacement + after`` as the leading text of one ``hp:t``.

    A tab in *replacement* becomes ``<hp:tab/>`` and a line break
    ``<hp:lineBreak/>``, inserted ahead of whatever inline children the element
    already has; a raw LF inside ``hp:t`` is not a line break to Hancom.
    Placeholders are filled from the end of a paragraph backwards, so text
    before this placeholder stays in ``.text`` where later replacements look.
    """

    parts = _TEXT_MARK_SPLIT.split(_ILLEGAL_TEXT_CHARS.sub("", replacement))
    if len(parts) == 1:
        text_element.text = before + parts[0] + after
        return
    namespace = text_element.tag.rsplit("}", 1)[0] + "}" if "}" in text_element.tag else ""
    text_element.text = before + parts[0]
    position = 0
    last: etree._Element | None = None
    for mark, segment in zip(parts[1::2], parts[2::2]):
        child = text_element.makeelement(namespace + ("tab" if mark == "\t" else "lineBreak"), {})
        child.tail = segment
        text_element.insert(position, child)
        position += 1
        last = child
    assert last is not None
    last.tail = (last.tail or "") + after


def _replace_match_in_nodes(
    nodes: Sequence[_TextNode],
    placeholder: Placeholder,
    replacement: str,
) -> None:
    touched = [
        node
        for node in nodes
        if node.start < placeholder.end and node.end > placeholder.start
    ]
    if not touched:
        return

    updated: dict[_TextNode, str] = {}
    for node in touched:
        local_start = max(placeholder.start, node.start) - node.start
        local_end = min(placeholder.end, node.end) - node.start
        current_text = node.element.text or ""
        updated[node] = current_text[:local_start] + current_text[local_end:]

    first = touched[0]
    insert_at = placeholder.start - first.start
    first_text = updated[first]
    for node, text in updated.items():
        if node is not first:
            node.element.text = text
    _write_replacement(first.element, first_text[:insert_at], replacement, first_text[insert_at:])


def fill_section_bytes(
    section_bytes: bytes,
    values: Mapping[str, str],
) -> tuple[bytes, FillReport]:
    """Fill mapped placeholders in one section XML document."""

    root = _parse_section(section_bytes)
    replacements = 0
    placeholders_found = 0
    missing_keys: list[str] = []
    all_placeholders: list[Placeholder] = []
    paragraphs = _iter_paragraphs(root)

    for paragraph_index in reversed(range(len(paragraphs))):
        paragraph = paragraphs[paragraph_index]
        nodes = _paragraph_text_nodes(paragraph)
        placeholders = _find_placeholders_in_nodes(paragraph_index, nodes)
        placeholders_found += len(placeholders)
        all_placeholders.extend(placeholders)
        paragraph_changed = False

        for placeholder in reversed(placeholders):
            if placeholder.key not in values:
                if placeholder.key not in missing_keys:
                    missing_keys.append(placeholder.key)
                continue
            _replace_match_in_nodes(nodes, placeholder, values[placeholder.key])
            replacements += 1
            paragraph_changed = True

        if paragraph_changed:
            _remove_linesegarray(paragraph)

    report = FillReport(
        replacements=replacements,
        placeholders_found=placeholders_found,
        missing_keys=tuple(missing_keys),
        warnings=tuple(heterogeneous_warnings(all_placeholders)),
    )
    return etree.tostring(root, encoding="UTF-8"), report
