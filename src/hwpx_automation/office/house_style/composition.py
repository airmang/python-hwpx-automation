# SPDX-License-Identifier: Apache-2.0
"""Typed application composition for an operating-plan section divider."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

_HEX_COLOR_RE = re.compile(r"#?([0-9A-Fa-f]{6})")


class SectionChipPlan(BaseModel):
    """Application-level section divider lowered to generic plan blocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    number: str
    title: str
    style: Literal["box", "inline"] = "box"
    accent_color: str | None = None

    @field_validator("number", "title")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("section chip number and title must be non-empty")
        return normalized

    @field_validator("accent_color")
    @classmethod
    def _hex_color(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        match = _HEX_COLOR_RE.fullmatch(str(value).strip())
        if match is None:
            raise ValueError("section chip accent_color must be a #RRGGBB colour")
        return f"#{match.group(1).upper()}"

    def to_document_plan_block(self) -> dict[str, Any]:
        if self.style == "inline":
            return {
                "type": "heading",
                "level": 1,
                "text": f"{self.number} {self.title}",
            }
        block: dict[str, Any] = {
            "type": "table",
            "showHeader": False,
            "columns": [
                {"key": "number", "label": "번호", "widthWeight": 2},
                {"key": "gap", "label": "여백", "widthWeight": 1},
                {"key": "title", "label": "제목", "widthWeight": 15},
            ],
            "rows": [
                {"number": self.number, "gap": "", "title": self.title}
            ],
        }
        if self.accent_color is not None:
            # The number sits on the accent (genres.json: section_chip_number
            # onAccent), so its text takes whichever of white or black reads.
            block["cellStyles"] = [
                {
                    "row": 0,
                    "column": "number",
                    "fillColor": self.accent_color,
                    "textColor": _text_color_on(self.accent_color),
                }
            ]
        return block


def _text_color_on(fill: str) -> str:
    """Return white or black, whichever contrasts more with ``fill`` (WCAG 2)."""

    def channel(offset: int) -> float:
        value = int(fill[offset : offset + 2], 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
    # Contrast with white is 1.05 / (L + 0.05), with black (L + 0.05) / 0.05.
    return "#FFFFFF" if 1.05 / (luminance + 0.05) >= (luminance + 0.05) / 0.05 else "#000000"


def compose_section_chip(
    number: str,
    title: str,
    *,
    style: Literal["box", "inline"] = "box",
    accent_color: str | None = None,
) -> dict[str, Any]:
    """Compose a genre-specific divider using generic document-plan blocks."""

    return SectionChipPlan(
        number=number,
        title=title,
        style=style,
        accent_color=accent_color,
    ).to_document_plan_block()


__all__ = ["SectionChipPlan", "compose_section_chip"]
