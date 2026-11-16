# SPDX-License-Identifier: Apache-2.0

"""Leaf helpers for table border-fill resolution, matching, and construction.

Private to the ops_services package: imported only by ``tables.py``. This module
holds no service class and depends solely on the standard library and the typed
``upstream`` seam, so it can never participate in an import cycle.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional
from xml.etree import ElementTree as ET

from ..upstream import HH_NS, HwpxDocument


class _BorderFillSpec(NamedTuple):
    border_type: str
    width_value: str
    diagonal_width_value: str
    width_token: str
    diagonal_width_token: str
    edge_color: Optional[str]
    diagonal_color: Optional[str]
    fill_color: Optional[str]


def _normalize_border_length(value: Optional[str | float | int], default: str) -> str:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return f"{value:g} mm"
    text = str(value).strip()
    if not text:
        return default
    match = re.fullmatch(r"([0-9]+(?:\\.[0-9]+)?)\\s*([A-Za-z]+)?", text)
    if match:
        number, unit = match.groups()
        unit = (unit or "mm").lower()
        return f"{number} {unit}"
    return text


def _normalize_length_token(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", str(value)).lower()


def _resolve_border_fill_spec(
    normalized_style: Optional[str],
    normalized_border_color: Optional[str],
    normalized_fill_color: Optional[str],
    border_width: Optional[str | float | int],
) -> _BorderFillSpec:
    border_type = "NONE" if normalized_style == "none" else "SOLID"
    if border_type == "NONE":
        width_default = "0 mm"
        diag_default = "0 mm"
    else:
        width_default = "0.12 mm"
        diag_default = "0.1 mm"

    width_value = _normalize_border_length(border_width, width_default)
    if border_width is not None:
        diagonal_width_value = _normalize_border_length(border_width, width_default)
    else:
        diagonal_width_value = _normalize_border_length(None, diag_default)
    width_token = _normalize_length_token(width_value)
    diagonal_width_token = _normalize_length_token(diagonal_width_value)

    edge_color: Optional[str] = normalized_border_color
    diagonal_color: Optional[str] = normalized_border_color
    if border_type == "SOLID":
        edge_color = normalized_border_color or "#000000"
        diagonal_color = edge_color
    # Non-solid borders retain the optional normalized color.
    return _BorderFillSpec(
        border_type=border_type,
        width_value=width_value,
        diagonal_width_value=diagonal_width_value,
        width_token=width_token,
        diagonal_width_token=diagonal_width_token,
        edge_color=edge_color,
        diagonal_color=diagonal_color,
        fill_color=normalized_fill_color,
    )


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
        return "0"

    if (
        normalized_style in {None, "solid"}
        and normalized_border_color is None
        and normalized_fill_color is None
        and border_width is None
    ):
        return document.oxml.ensure_basic_border_fill()

    return None


def _border_fill_flags_match(existing: ET.Element) -> bool:
    if (existing.get("threeD") or "0") != "0":
        return False
    if (existing.get("shadow") or "0") != "0":
        return False
    if (existing.get("centerLine") or "NONE").upper() != "NONE":
        return False
    if (existing.get("breakCellSeparateLine") or "0") != "0":
        return False
    return True


def _border_fill_slashes_match(existing: ET.Element) -> bool:
    for slash_name in ("slash", "backSlash"):
        slash = existing.find(f"{HH_NS}{slash_name}")
        if slash is None:
            return False
        if (slash.get("type") or "NONE").upper() != "NONE":
            return False
        if slash.get("Crooked", "0") != "0":
            return False
        if slash.get("isCounter", "0") != "0":
            return False
    return True


def _border_fill_edges_match(
    existing: ET.Element,
    border_type: str,
    width_token: str,
    edge_color: Optional[str],
) -> bool:
    for child_name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        border_child = existing.find(f"{HH_NS}{child_name}")
        if border_child is None:
            return False
        if (border_child.get("type") or "").upper() != border_type:
            return False
        if _normalize_length_token(border_child.get("width")) != width_token:
            return False
        if edge_color is not None:
            if (border_child.get("color") or "").upper() != edge_color:
                return False
        else:
            if border_child.get("color") not in (None, ""):
                return False
    return True


def _border_fill_diagonal_matches(
    existing: ET.Element,
    border_type: str,
    diagonal_width_token: str,
    diagonal_color: Optional[str],
) -> bool:
    diagonal_child = existing.find(f"{HH_NS}diagonal")
    if diagonal_child is None:
        return False
    expected_diagonal_type = "SOLID" if border_type == "SOLID" else "NONE"
    if (diagonal_child.get("type") or "").upper() != expected_diagonal_type:
        return False
    if _normalize_length_token(diagonal_child.get("width")) != diagonal_width_token:
        return False
    if diagonal_color is not None:
        if (diagonal_child.get("color") or "").upper() != diagonal_color:
            return False
    else:
        if diagonal_child.get("color") not in (None, ""):
            return False
    return True


def _border_fill_fill_matches(
    existing: ET.Element, normalized_fill_color: Optional[str]
) -> bool:
    fill_brush = existing.find(f"{HH_NS}fillBrush")
    if normalized_fill_color is None:
        if fill_brush is not None:
            return False
    else:
        if fill_brush is None:
            return False
        solid_brush = fill_brush.find(f"{HH_NS}solidBrush")
        if solid_brush is None:
            return False
        if (solid_brush.get("type") or "SOLID").upper() != "SOLID":
            return False
        if (solid_brush.get("color") or "").upper() != normalized_fill_color:
            return False
    return True


def _border_fill_matches(existing: ET.Element, spec: _BorderFillSpec) -> bool:
    return (
        _border_fill_flags_match(existing)
        and _border_fill_slashes_match(existing)
        and _border_fill_edges_match(
            existing, spec.border_type, spec.width_token, spec.edge_color
        )
        and _border_fill_diagonal_matches(
            existing, spec.border_type, spec.diagonal_width_token, spec.diagonal_color
        )
        and _border_fill_fill_matches(existing, spec.fill_color)
    )


def _find_matching_border_fill(
    border_fills_element: ET.Element, spec: _BorderFillSpec
) -> Optional[str]:
    for candidate in border_fills_element.findall(f"{HH_NS}borderFill"):
        identifier = candidate.get("id")
        if not identifier:
            continue
        if _border_fill_matches(candidate, spec):
            return identifier
    return None


def _next_border_fill_id(border_fills_element: ET.Element) -> str:
    """The id a new ``hh:borderFill`` takes: one past the largest numeric id (0 when none)."""

    existing = {child.get("id") or "" for child in border_fills_element.findall(f"{HH_NS}borderFill")}
    existing.discard("")
    numeric_ids: list[int] = []
    for value in existing:
        try:
            numeric_ids.append(int(value))
        except ValueError:
            continue
    next_id = 0 if not numeric_ids else max(numeric_ids) + 1
    while str(next_id) in existing:
        next_id += 1
    return str(next_id)


def _build_border_fill_element(
    border_fills_element: ET.Element, new_id: str, spec: _BorderFillSpec
) -> None:
    border_fill_element = ET.SubElement(
        border_fills_element,
        f"{HH_NS}borderFill",
        {
            "id": new_id,
            "threeD": "0",
            "shadow": "0",
            "centerLine": "NONE",
            "breakCellSeparateLine": "0",
        },
    )

    for slash_name in ("slash", "backSlash"):
        ET.SubElement(
            border_fill_element,
            f"{HH_NS}{slash_name}",
            {"type": "NONE", "Crooked": "0", "isCounter": "0"},
        )

    def append_border(
        name: str, *, width: str, color: Optional[str], kind: str
    ) -> None:
        attrs = {"type": kind}
        if width:
            attrs["width"] = width
        if color is not None:
            attrs["color"] = color
        ET.SubElement(border_fill_element, f"{HH_NS}{name}", attrs)

    for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        append_border(
            side, width=spec.width_value, color=spec.edge_color, kind=spec.border_type
        )

    append_border(
        "diagonal",
        width=spec.diagonal_width_value,
        color=spec.diagonal_color,
        kind="SOLID" if spec.border_type == "SOLID" else "NONE",
    )

    if spec.fill_color is not None:
        fill_brush = ET.SubElement(border_fill_element, f"{HH_NS}fillBrush")
        ET.SubElement(
            fill_brush,
            f"{HH_NS}solidBrush",
            {"type": "SOLID", "color": spec.fill_color, "alpha": "255"},
        )
