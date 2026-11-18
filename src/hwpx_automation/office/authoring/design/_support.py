# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the design composer/harvester: element names (read only), the text a node can
hold, the fixed id seeds, and the column definition a profile's first paragraph needs (through
python-hwpx). The documents themselves are changed through python-hwpx's public API."""
from __future__ import annotations

import re
from typing import Iterable

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def ln(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def hp(element: etree._Element, name: str) -> str:
    """Namespaced tag for *name* using the element's own paragraph namespace."""

    ns = element.tag.rsplit("}", 1)[0].lstrip("{") if "}" in element.tag else HP_NS
    return f"{{{ns}}}{name}"


def iter_local(element: etree._Element, name: str) -> Iterable[etree._Element]:
    for child in element.iter():
        if ln(child.tag) == name:
            yield child


def children_local(element: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in element if ln(c.tag) == name]


# Characters XML 1.0 cannot carry in a text node (tab and the line breaks are
# handled separately: they become hp:tab / hp:lineBreak elements).
_ILLEGAL_TEXT_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_TEXT_MARK_SPLIT = re.compile("(\t|\r\n|\r|\n)")


def clean_text(value: str) -> str:
    """*value* without the control characters an XML text node refuses."""

    return _ILLEGAL_TEXT_CHARS.sub("", value)


__all__ = [
    "HP_NS",
    "ln",
    "hp",
    "iter_local",
    "children_local",
    "clean_text",
]


#: Seeds for the ids python-hwpx makes for the new paragraphs and objects of a document this
#: package writes (``HwpxDocument.open(seed=)``, python-hwpx #775): the same input writes the same
#: bytes. A seed is used for new ids only; the ids a document already holds are kept.
COMPOSE_SEED = 0x48575058  # "HWPX": a document composed from a profile
HARVEST_SEED = 0x48415256  # "HARV": a profile's template.hwpx and fragments.hwpx


def open_seeded(source: object, seed: int) -> object:
    """``HwpxDocument.open(source, seed=seed)``; the clock (``now=``) is left alone."""

    from hwpx.document import HwpxDocument

    try:
        return HwpxDocument.open(source, seed=seed)
    except TypeError:  # a python-hwpx 7.0 development build before seed= on open (#775)
        return HwpxDocument.open(source)


def ensure_section_columns(document: object, first: object) -> None:
    """Give the section's first paragraph the column definition (``hp:ctrl/hp:colPr``) Hancom keeps
    next to ``hp:secPr``. Without it Hancom drops the section's page settings and opens the document
    on its default margins (8.0 14차: every profile skeleton, harvested with its controls stripped,
    lacked it). One column, as Hancom writes a new document's."""

    if document is None or first is None:
        return
    for run in first.element:  # type: ignore[attr-defined]
        if run.tag.endswith("}run") and any(node.tag.endswith("}colPr") for node in run.iter()):
            return
    document.page.set_columns(1, same_gap=0, paragraph=first)  # type: ignore[attr-defined]
