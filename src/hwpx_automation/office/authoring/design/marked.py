# SPDX-License-Identifier: Apache-2.0
"""Marked-template profiles — fragments named by the template author.

:func:`~hwpx_automation.office.authoring.design.harvest.harvest_profile` guesses
roles from font size and keeps a single info table, so it cannot tell a coloured
chapter-band table from a data table, or one bullet level from another. Here the
author decides instead: in a Hancom-saved template they type placeholders where
content goes —

* ``□ {{1단계}}`` — a paragraph role ``1단계`` with one unnamed slot;
* ``{{띠.번호}}`` / ``{{띠.제목}}`` in the cells of a band table — a role ``띠``
  with the slots ``번호`` and ``제목``.

Every top-level paragraph that carries placeholders becomes one role. Text-less
paragraphs directly above it (the spacer lines Hancom users put between items)
belong to the same role, so spacing is cloned with it. Fills, borders, fonts and
indents are never interpreted: the composer clones the saved XML and swaps only
the placeholder text.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Callable, Mapping

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

from hwpx.document import HwpxDocument

import hwpx_automation.office.authoring.design._support as S
from .harvest import PROFILE_SCHEMA, _build_skeleton, _references_binary

MARKED_PROFILE_KIND = "marked"
# Wrapper for a multi-paragraph fragment file; never written into a document.
FRAGMENT_WRAPPER_TAG = "fragment"

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}.\s]+)(?:\.([^{}\s]+))?\s*\}\}")

# Objects whose ``id`` must stay unique when a fragment is cloned more than once.
OBJECT_TAGS = frozenset(
    {
        "tbl", "pic", "rect", "ellipse", "arc", "polygon", "curve", "line",
        "connectLine", "container", "ole", "equation", "textart",
    }
)


class MarkedTemplateError(ValueError):
    """The template's placeholders cannot be turned into a profile."""


def is_marked_profile(manifest: Mapping[str, object]) -> bool:
    return manifest.get("kind") == MARKED_PROFILE_KIND


def _text_pieces(element: etree._Element) -> list[tuple[etree._Element, str]]:
    """(owner, attr) pairs for every text piece of every ``<hp:t>`` under *element*.

    ``attr`` is ``"text"`` for ``t.text`` and ``"tail"`` for the tail of an inline
    child (tab, line break) inside the ``<hp:t>``.
    """

    pieces: list[tuple[etree._Element, str]] = []
    for t in S.iter_local(element, "t"):
        pieces.append((t, "text"))
        for child in t:
            pieces.append((child, "tail"))
    return pieces


def _get(piece: tuple[etree._Element, str]) -> str:
    owner, attr = piece
    return (owner.text if attr == "text" else owner.tail) or ""


def _set(piece: tuple[etree._Element, str], value: str) -> None:
    owner, attr = piece
    if attr == "text":
        owner.text = value
    else:
        owner.tail = value


def placeholders_in(element: etree._Element) -> list[tuple[str, str]]:
    """(role, slot) for every placeholder under *element*; slot ``""`` if unnamed."""

    found: list[tuple[str, str]] = []
    for para in S.iter_local(element, "p"):
        joined = "".join(_get(p) for p in _direct_pieces(para))
        found.extend((m.group(1), m.group(2) or "") for m in PLACEHOLDER_RE.finditer(joined))
    return list(dict.fromkeys(found))


def _direct_pieces(paragraph: etree._Element) -> list[tuple[etree._Element, str]]:
    """Text pieces of *paragraph* itself, excluding paragraphs nested in its tables."""

    pieces: list[tuple[etree._Element, str]] = []
    for run in S.children_local(paragraph, "run"):
        for t in S.children_local(run, "t"):
            pieces.append((t, "text"))
            for child in t:
                pieces.append((child, "tail"))
    return pieces


def _is_blank(paragraph: etree._Element) -> bool:
    if any(_get(p).strip() for p in _text_pieces(paragraph)):
        return False
    for node in paragraph.iter():
        if S.ln(node.tag) in OBJECT_TAGS:
            return False
    return True


def _strip_section_setup(fragment: etree._Element) -> None:
    """Drop the page setup a template's first paragraph carries (secPr + colPr ctrl)."""

    for run in S.children_local(fragment, "run"):
        for secpr in S.children_local(run, "secPr"):
            run.remove(secpr)
        for ctrl in S.children_local(run, "ctrl"):
            if any(S.ln(c.tag) == "colPr" for c in ctrl):
                run.remove(ctrl)


def fill_placeholders(
    paragraphs: list[etree._Element], role: str, values: Mapping[str, str]
) -> list[str]:
    """Replace ``{{role}}``/``{{role.slot}}`` text in place; return unfilled slots.

    The value goes into the piece where the placeholder starts, so it takes that
    run's style. A placeholder Hancom split across runs (the character shape
    changed inside it) loses only its own characters from the later pieces;
    the rest of those runs, and their styles, stay. A value's line breaks and
    tabs become the ``<hp:lineBreak/>``/``<hp:tab/>`` Hancom writes for them.
    Missing values become empty text so a placeholder never ships.
    """

    unfilled: list[str] = []

    def value_for(match: re.Match[str]) -> str | None:
        if match.group(1) != role:
            return None
        slot = match.group(2) or ""
        if slot not in values:
            unfilled.append(slot)
            return ""
        return str(values[slot])

    for root in paragraphs:
        for para in S.iter_local(root, "p"):
            _replace_in_pieces(_direct_pieces(para), value_for)
        S.strip_lineseg(root)
    return list(dict.fromkeys(unfilled))


def _replace_in_pieces(
    pieces: list[tuple[etree._Element, str]],
    value_for: Callable[[re.Match[str]], str | None],
) -> None:
    texts = [_get(p) for p in pieces]
    starts: list[int] = []
    offset = 0
    for text in texts:
        starts.append(offset)
        offset += len(text)
    touched: set[int] = set()
    # Right to left, so an earlier match's offsets still hold.
    for match in reversed(list(PLACEHOLDER_RE.finditer("".join(texts)))):
        value = value_for(match)
        if value is None:
            continue
        covered = [
            i for i, start in enumerate(starts)
            if start < match.end() and match.start() < start + len(texts[i])
        ]
        for index in reversed(covered):
            lo = max(match.start(), starts[index]) - starts[index]
            hi = min(match.end(), starts[index] + len(texts[index])) - starts[index]
            insert = value if index == covered[0] else ""
            texts[index] = texts[index][:lo] + insert + texts[index][hi:]
            touched.add(index)
    for index in sorted(touched, reverse=True):
        _set_with_marks(pieces[index], texts[index])


_TEXT_MARK_RE = re.compile(r"(\t|\r\n|\r|\n)")


def _set_with_marks(piece: tuple[etree._Element, str], value: str) -> None:
    """Set *piece* to *value*, each tab/line break as the element inside ``<hp:t>``."""

    owner, attr = piece
    parts = _TEXT_MARK_RE.split(value)
    _set(piece, parts[0])
    if attr == "text":
        parent, at = owner, 0
    else:
        parent = owner.getparent()
        at = parent.index(owner) + 1
    for mark, segment in zip(parts[1::2], parts[2::2]):
        element = parent.makeelement(S.hp(parent, "tab" if mark == "\t" else "lineBreak"), {})
        element.tail = segment
        parent.insert(at, element)
        at += 1


def _pick_marked_fragments(
    section_element: etree._Element,
) -> tuple[dict[str, list[etree._Element]], dict[str, list[str]], int]:
    fragments: dict[str, list[etree._Element]] = {}
    slots: dict[str, list[str]] = {}
    pending: list[etree._Element] = []
    ignored = 0
    for para in S.children_local(section_element, "p"):
        marks = placeholders_in(para)
        if not marks:
            if _is_blank(para):
                pending.append(para)
            else:
                ignored += 1  # static content outside any role
                pending = []
            continue
        roles = list(dict.fromkeys(role for role, _ in marks))
        if len(roles) > 1:
            raise MarkedTemplateError(
                f"one paragraph carries placeholders of several roles {roles}; "
                "put each role in its own paragraph or table"
            )
        role = roles[0]
        if role in fragments:
            raise MarkedTemplateError(f"role {role!r} appears more than once in the template")
        group = [deepcopy(p) for p in (*pending, para)]
        pending = []
        for frag in group:
            if _references_binary(frag):
                raise MarkedTemplateError(
                    f"role {role!r} contains an image or embedded object; "
                    "fragments must be text, tables and shapes only"
                )
            _strip_section_setup(frag)
            S.strip_lineseg(frag)
        fragments[role] = group
        slots[role] = [slot for _, slot in marks]
    if not fragments:
        raise MarkedTemplateError("template has no {{placeholder}} paragraphs")
    return fragments, slots, ignored


def harvest_marked_profile(source: str | Path, profile_id: str, out_root: str | Path) -> dict:
    """Harvest a placeholder-marked template into ``<out_root>/<profile_id>/``.

    Only the first section is read. Returns the written manifest plus
    ``skeleton_open_safe`` and ``stripped_parts`` diagnostics.
    """

    source = Path(source)
    out_dir = Path(out_root) / profile_id
    (out_dir / "fragments").mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.open(source)
    try:
        fragments, slots, ignored = _pick_marked_fragments(doc.sections[0].element)
    finally:
        doc.close()

    paths: dict[str, str] = {}
    for index, (role, group) in enumerate(fragments.items()):
        wrapper = etree.Element(FRAGMENT_WRAPPER_TAG)
        wrapper.extend(group)
        rel = f"fragments/{index:02d}.xml"
        (out_dir / rel).write_bytes(etree.tostring(wrapper, encoding="UTF-8"))
        paths[role] = rel

    skel = _build_skeleton(source, out_dir / "template.hwpx")
    manifest = {
        "schemaVersion": PROFILE_SCHEMA,
        "kind": MARKED_PROFILE_KIND,
        "id": profile_id,
        "template": "template.hwpx",
        "fragments": paths,
        "slots": slots,
        "page": skel["page"],
        "char_pr_count": skel["char_pr_count"],
        "style_coverage_threshold": 0.98,
        "source_basename": source.name,
        "ignored_static_paragraphs": ignored,
    }
    (out_dir / "profile.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        **manifest,
        "skeleton_open_safe": skel["open_safe"],
        "stripped_parts": skel.get("stripped_parts", []),
    }


def fragment_paragraphs(fragment: etree._Element) -> list[etree._Element]:
    """The ``<hp:p>`` list a (possibly wrapped) fragment element stands for."""

    if fragment.tag == FRAGMENT_WRAPPER_TAG:
        return list(fragment)
    return [fragment]


__all__ = [
    "MARKED_PROFILE_KIND",
    "PLACEHOLDER_RE",
    "MarkedTemplateError",
    "harvest_marked_profile",
    "fill_placeholders",
    "placeholders_in",
    "fragment_paragraphs",
    "is_marked_profile",
]
