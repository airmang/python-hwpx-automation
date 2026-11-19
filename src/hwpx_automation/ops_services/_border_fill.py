# SPDX-License-Identifier: Apache-2.0

"""Leaf helpers for the border fills a table service asks for before python-hwpx is asked.

Private to the ops_services package: imported only by ``tables.py``. This module
holds no service class and depends solely on the standard library and the typed
``upstream`` seam, so it can never participate in an import cycle. The border fill
itself is found or added by python-hwpx (``doc.styles.ensure_border_fill``).
"""

from __future__ import annotations

from typing import Optional

from ..upstream import HwpxDocument


def _shortcut_border_fill_id(
    document: HwpxDocument,
    normalized_style: Optional[str],
    normalized_border_color: Optional[str],
    normalized_fill_color: Optional[str],
    border_width: Optional[str | float | int],
) -> Optional[str]:
    if normalized_style == "none" and not any(
        [normalized_border_color, normalized_fill_color, border_width]
    ):
        # Hancom writes "no lines" as a border fill whose four sides are NONE (id 1 in every one of
        # python-hwpx's 1,204 Hancom-saved fixtures); no table or cell names an id "0". None here
        # (no such fill yet) builds one below.
        return _no_line_border_fill_id(document)

    if (
        normalized_style in {None, "solid"}
        and normalized_border_color is None
        and normalized_fill_color is None
        and border_width is None
    ):
        return document.oxml.ensure_basic_border_fill()

    return None


def _no_line_border_fill_id(document: HwpxDocument) -> Optional[str]:
    """The first border fill drawing no line on any side and no fill, or None."""

    for identifier, info in document.styles.border_fills.items():
        sides = (info.left, info.right, info.top, info.bottom)
        if info.fill is None and all(side is not None and side.type == "NONE" for side in sides):
            return str(identifier)
    return None
