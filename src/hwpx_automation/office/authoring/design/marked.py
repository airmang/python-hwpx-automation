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
belong to the same role, so spacing is copied with it. Fills, borders, fonts and
indents are never interpreted: the composer copies the saved paragraphs and swaps
only the placeholder text (:func:`~hwpx_automation.office.authoring.design.composer.fill_placeholders`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from hwpx.document import HwpxDocument

from .harvest import PROFILE_SCHEMA, _build_skeleton, _references_binary, _write_fragments_document
from .profile import FRAGMENTS_DOCUMENT

MARKED_PROFILE_KIND = "marked"

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


def _paragraphs_within(paragraph: Any) -> list[Any]:
    """*paragraph* and every paragraph inside it (its tables' cells, text boxes …), in order."""

    return [paragraph, *(place.paragraph for place in paragraph.iter_paragraphs())]


def placeholders_in(paragraph: Any) -> list[tuple[str, str]]:
    """(role, slot) for every placeholder in *paragraph* and the paragraphs inside it; slot ``""`` if unnamed."""

    found: list[tuple[str, str]] = []
    for inner in _paragraphs_within(paragraph):
        found.extend((m.group(1), m.group(2) or "") for m in PLACEHOLDER_RE.finditer(inner.text or ""))
    return list(dict.fromkeys(found))


def _is_blank(paragraph: Any) -> bool:
    if any((inner.text or "").strip() for inner in _paragraphs_within(paragraph)):
        return False
    return not any(True for _ in paragraph.iter_objects())


def _pick_marked_fragments(section: Any) -> tuple[list[tuple[str, list[Any]]], dict[str, list[str]], int]:
    groups: list[tuple[str, list[Any]]] = []
    slots: dict[str, list[str]] = {}
    pending: list[Any] = []
    ignored = 0
    for para in section.paragraphs:
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
        if role in slots:
            raise MarkedTemplateError(f"role {role!r} appears more than once in the template")
        group = [*pending, para]
        pending = []
        for frag in group:
            if _references_binary(frag.element):
                raise MarkedTemplateError(
                    f"role {role!r} contains an image or embedded object; "
                    "fragments must be text, tables and shapes only"
                )
        groups.append((role, group))
        slots[role] = [slot for _, slot in marks]
    if not groups:
        raise MarkedTemplateError("template has no {{placeholder}} paragraphs")
    return groups, slots, ignored


def harvest_marked_profile(source: str | Path, profile_id: str, out_root: str | Path) -> dict:
    """Harvest a placeholder-marked template into ``<out_root>/<profile_id>/``.

    Only the first section is read. The role paragraphs are copied, as they are, into
    ``fragments.hwpx`` (python-hwpx ``paragraph.copy_to``: the page setup a template's
    first paragraph carries stays behind, line layout caches do not come along).
    Returns the written manifest plus ``skeleton_open_safe`` and ``stripped_parts``
    diagnostics.
    """

    source = Path(source)
    out_dir = Path(out_root) / profile_id
    out_dir.mkdir(parents=True, exist_ok=True)

    with HwpxDocument.open(source) as doc:
        groups, slots, ignored = _pick_marked_fragments(doc.sections[0])
        skel = _build_skeleton(source, out_dir / "template.hwpx")
        places = _write_fragments_document(out_dir / "template.hwpx", groups, out_dir / FRAGMENTS_DOCUMENT)

    manifest = {
        "schemaVersion": PROFILE_SCHEMA,
        "kind": MARKED_PROFILE_KIND,
        "id": profile_id,
        "template": "template.hwpx",
        "fragments_document": FRAGMENTS_DOCUMENT,
        "fragments": places,
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


__all__ = [
    "MARKED_PROFILE_KIND",
    "PLACEHOLDER_RE",
    "MarkedTemplateError",
    "harvest_marked_profile",
    "placeholders_in",
    "is_marked_profile",
]
