"""The preview shows every character the document holds: a check for the engine preview tests.

Document text is every ``hp:t`` of the sections and the number or bullet each numbered, outline
and bullet paragraph shows before its text (a paragraph with a number shows it); preview text is
the page markup without its tags and markers. Characters are compared as multisets, whitespace apart, so this finds text
that is missing, not text that is misplaced. Text Hangul itself does not put on the page -- a
memo: the ``hp:subList`` of a ``MEMO`` field and ``hp:memogroup`` -- is left out.
"""

from __future__ import annotations

import html as htmllib
import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from hwpx import HwpxDocument
from hwpx.tools.exporter import ListLabels
from preview_overlap import drawn_wrongly, overlaps

from hwpx_automation.preview import layout_preview

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_NOT_TEXT = re.compile(
    r'<p class="hwpx-engine-page-status">.*?</p>|<span class="hwpx-object-marker">.*?</span>'
    r'|<span class="hwpx-equation-tag">.*?</span>|<script\b.*?</script\b[^>]*>|<style\b.*?</style\b[^>]*>',
    re.S | re.I,
)
_TAG = re.compile(r"<[^>]+>")


def _characters(text: str) -> Counter[str]:
    return Counter(character for character in text if not character.isspace())


def _in_a_memo(node: Any) -> bool:
    for parent in node.iterancestors():
        if parent.tag == f"{HP}memogroup":
            return True
        if parent.tag == f"{HP}fieldBegin" and parent.get("type") == "MEMO":
            return True
    return False


def label_characters(document: HwpxDocument) -> Counter[str]:
    """The characters of the numbers and bullets Hangul draws before numbered, outline and bullet
    paragraphs (python-hwpx's count, :class:`hwpx.tools.exporter.ListLabels`)."""
    labels = ListLabels(document)
    found: Counter[str] = Counter()
    for section in document.sections:
        for paragraph in section.element.iter(f"{HP}p"):
            if not _in_a_memo(paragraph):
                found.update(_characters(labels.label(paragraph)))
    return found


def document_characters(document: HwpxDocument) -> Counter[str]:
    """The characters Hangul puts on the document's pages: its text and its paragraphs' labels."""
    found = label_characters(document)
    for section in document.sections:
        for node in section.element.iter(f"{HP}t"):
            if not _in_a_memo(node):
                found.update(_characters("".join(node.itertext())))
    return found


def missing_characters(document: HwpxDocument, fragments: tuple[str, ...]) -> Counter[str]:
    """What the document holds and the preview's pages do not show."""
    shown = _characters(htmllib.unescape(_TAG.sub("", _NOT_TEXT.sub("", "".join(fragments)))))
    return document_characters(document) - shown


@pytest.fixture(autouse=True)
def every_engine_preview_shows_the_text(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every document a test renders through the engine path must show all its text, and its pages
    drawn at coordinates no overlap the engine's line pitch does not set (:mod:`preview_overlap`)."""
    render = layout_preview._render_engine_preview

    def checked(document: HwpxDocument, *args: Any, **kwargs: Any) -> Any:
        preview = render(document, *args, **kwargs)
        missing = missing_characters(document, preview.page_fragments)
        assert not missing, f"the preview drops {sum(missing.values())} characters of the document"
        found = overlaps(preview.page_fragments)
        assert not drawn_wrongly(found), f"the preview draws overlapping text: {dict(found)}"
        return preview

    monkeypatch.setattr(layout_preview, "_render_engine_preview", checked)
    yield
