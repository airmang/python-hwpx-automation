"""Overlaps on the preview's pages drawn at coordinates: a check for the engine preview tests.

Boxes come from the drawn markup (``left``/``top``/``width`` and the line height, in millimetres,
cell boxes inside their table and cell lines inside their cell). A line's text box is as tall as its
largest character size, centred in the line's height as the browser sets it. Two things must not
overlap:

- ``cell-lines``: the text boxes of two lines of one cell that follow each other (the upper one's
  foot below the lower one's top);
- ``table-body``: a table drawn at coordinates and a body line with text on the same page.

An overlap the engine's own line pitch sets is counted apart, as the document's: two cell lines
set closer than the upper one's height (``cell-lines closer than their height``: a line spacing
under 100 %, or fixed under the line, as Hangul's saved lines also stand), and a body line set
inside the height of the line that holds the table (``table-body inside the table's line``: a
fixed line spacing under the table's height). What remains is drawn wrongly: the check wants it 0.

Objects, text boxes and headers, footers and notes are measured too (see :func:`_objects_and_areas`):
an object against the body lines it does not stand on (``object-body``), two lines of a text box
(``box-lines``, its pitch-set part apart as for cells), and a header, footer or note line against a
body line (``area-body``). What is drawn at a place the engine does not give (``data-approx``) is
counted apart, as approximate.

Only text that shows counts (a line without characters takes room but draws nothing), and an
object the document sets in front of or behind the text is left out: there the overlap is the
document's own. Pages drawn as flow are not measured: the browser stacks them.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from lxml import html

_EPSILON_MM = 0.02


def _css(element: Any, name: str) -> float | None:
    found = re.search(rf"(?:^|;)\s*{re.escape(name)}:\s*(-?[\d.]+)mm", element.get("style") or "")
    return float(found.group(1)) if found else None


def _box(element: Any, origin: tuple[float, float] = (0.0, 0.0), *, height: str = "height") -> tuple[float, ...] | None:
    left, top, width = (_css(element, name) for name in ("left", "top", "width"))
    tall = _css(element, height)
    if None in (left, top, width, tall):
        return None
    assert left is not None and top is not None and width is not None and tall is not None
    return origin[0] + left, origin[1] + top, width, tall


def _text_box(element: Any, box: tuple[float, ...]) -> tuple[float, ...]:
    """The part of a line's *box* its characters take: the largest character size, centred."""
    sizes = [float(size) for size in re.findall(r"font-size:\s*([\d.]+)pt", html.tostring(element, encoding="unicode"))]
    tall = max(sizes, default=10.0) * 25.4 / 72
    return box[0], box[1] + (box[3] - tall) / 2, box[2], tall


def _shows_text(element: Any) -> bool:
    return bool("".join(element.itertext()).strip())


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > _EPSILON_MM
            and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > _EPSILON_MM)


def page_overlaps(fragment: str) -> Counter[str]:
    """The overlaps on one page fragment (nothing for a flow page)."""
    found: Counter[str] = Counter()
    page = html.fromstring(fragment)
    if page.get("data-layout-mode") != "positioned":
        return found
    every = [
        (box, _shows_text(line)) for line in page.xpath(
            ".//div[@class='hwpx-engine-line' or @class='hwpx-engine-area-line'][not(ancestor::*[@data-overlay])]"
        )
        if (box := _box(line, height="--hwpx-line-height")) is not None
    ]
    body = [box for box, shows in every if shows]
    for table in page.xpath(".//div[@class='hwpx-engine-table']"):
        if table.xpath("ancestor::*[@data-overlay]"):
            continue
        frame = _box(table)
        if frame is None:
            continue
        found["tables"] += 1
        holders = [box for box, _ in every if abs(box[1] - frame[1]) < _EPSILON_MM and _cross(box, frame)]
        for line in body:
            if _cross(frame, line):
                found["table-body"] += 1
                found["table-body inside the table's line"] += any(
                    holder[1] + holder[3] - line[1] > _EPSILON_MM for holder in holders
                )
        for cell in table.xpath("./div[@class='hwpx-engine-cell']"):
            box = _box(cell, (frame[0], frame[1]))
            if box is None:
                continue
            _stacked_lines(cell, box, found, "cell-lines")
    _objects_and_areas(page, every, found)
    return found


def _stacked_lines(holder: Any, box: tuple[float, ...], found: Counter[str], name: str) -> None:
    """Two lines of one cell or text box that follow each other (*name* and its pitch-set part)."""
    lines = sorted(
        ((line_box, _text_box(line, line_box)) for line in holder.xpath("./div[@class='hwpx-engine-cell-line']")
         if _shows_text(line) and (line_box := _box(line, (box[0], box[1]))) is not None),
        key=lambda item: item[0][1],
    )
    found[f"{name.removesuffix('s')} pairs"] += max(0, len(lines) - 1)
    for (upper, upper_text), (lower, lower_text) in zip(lines, lines[1:]):
        if upper_text[1] + upper_text[3] - lower_text[1] > _EPSILON_MM:
            found[name] += 1
            found[f"{name} closer than their height"] += upper[1] + upper[3] - lower[1] > _EPSILON_MM


def _objects_and_areas(page: Any, every: list[tuple[tuple[float, ...], bool]], found: Counter[str]) -> None:
    """Objects drawn at coordinates and headers, footers and notes, against the body's text lines.

    - ``object-body``: an object (not in front of or behind the text) and a body line with text it does not
      stand on (an object set as a character stands inside its line's height, beside that line's text);
      one at an approximate place (``data-approx``) is counted apart (``object-body approximate``);
    - ``box-lines``: two lines of a text box, as ``cell-lines``;
    - ``area-body``: a header, footer or note line and a body line; an area drawn whole at an approximate
      place in its room is counted apart (``area-room-body approximate``).
    """
    lines = [
        (box, _text_box(line, box), _shows_text(line)) for line in page.xpath(".//div[@class='hwpx-engine-line']")
        if (box := _box(line, height="--hwpx-line-height")) is not None
    ]
    body = [(box, text) for box, text, shows in lines if shows]
    placed = "contains(concat(' ', @class, ' '), ' hwpx-placed-object ')"
    for item in page.xpath(f".//div[{placed}][not(ancestor::*[{placed}])]"):
        classes = item.get("class") or ""
        if item.get("data-overlay") or "hwpx-object-caption" in classes:
            continue
        box = _box(item)
        if box is None:
            continue
        if "hwpx-area-room" in classes:
            found["area-room-body approximate"] += sum(1 for line, _ in body if _cross(box, line))
            continue
        found["objects"] += 1
        # An object set as a character stands in the line holding it (as tall as it or taller).
        holders = [
            line for line, _, _ in lines if item.get("data-wrap") == "AS_CHARACTER"
            and box[1] >= line[1] - _EPSILON_MM and box[1] + box[3] <= line[1] + line[3] + _EPSILON_MM
        ]
        for line, _ in body:
            if not _cross(box, line) or line in holders:
                continue  # an object's own line holds it beside that line's text
            if item.get("data-approx"):
                found["object-body approximate"] += 1
                continue
            found["object-body"] += 1
            # The line and the line holding the object set inside each other's height (a line spacing
            # under the lines' height, as Hangul's saved lines also stand): the document's own overlap.
            found["object-body inside its line's height"] += any(
                min(holder[1] + holder[3], line[1] + line[3]) - max(holder[1], line[1]) > _EPSILON_MM
                for holder in holders
            )
        _box_lines(item, (0.0, 0.0), found, placed)
    for line in page.xpath(".//div[@class='hwpx-area-layer']/div[@class='hwpx-engine-area-line']"):
        area = _box(line, height="--hwpx-line-height")
        if area is None or not _shows_text(line):
            continue
        found["area-lines"] += 1
        note = line.getparent().get("data-area-kind") in ("footNote", "endNote")
        for box, text in body:
            if _cross(_text_box(line, area), text):
                found["area-body"] += 1
                # A note shares the body's column: the engine may set its line inside the height of the
                # body's last line (or that line inside the note's). A header or footer has its own room.
                found["area-body inside a line's height"] += note and (
                    box[1] - _EPSILON_MM <= area[1] < box[1] + box[3] - _EPSILON_MM
                    or area[1] - _EPSILON_MM <= box[1] < area[1] + area[3] - _EPSILON_MM
                )


def _box_lines(item: Any, origin: tuple[float, float], found: Counter[str], placed: str) -> None:
    """The lines of a text box, and of the text boxes of a group's members (at their places in the group)."""
    box = _box(item, origin)
    if box is None:
        return
    _stacked_lines(item, box, found, "box-lines")
    for member in item.xpath(f"./div[{placed}]"):
        _box_lines(member, (box[0], box[1]), found, placed)


def overlaps(fragments: Iterable[str]) -> Counter[str]:
    """The overlaps over all the pages of a preview (see :func:`page_overlaps`)."""
    total: Counter[str] = Counter()
    for fragment in fragments:
        total.update(page_overlaps(fragment))
    return total


def drawn_wrongly(found: Counter[str]) -> int:
    """The overlaps the engine's line pitch does not set (see the module)."""
    return (found["cell-lines"] - found["cell-lines closer than their height"]
            + found["table-body"] - found["table-body inside the table's line"]
            + found["box-lines"] - found["box-lines closer than their height"]
            + found["object-body"] - found["object-body inside its line's height"]
            + found["area-body"] - found["area-body inside a line's height"])
