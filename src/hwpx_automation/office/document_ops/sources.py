# SPDX-License-Identifier: Apache-2.0
"""Document-plan inputs owned by the application layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hwpx.tools.doc_diff import paragraph_texts


def paragraph_plan_to_paragraphs(plan: Mapping[str, Any]) -> list[str]:
    """Normalize the application plan schema, preserving existing block precedence."""
    if not isinstance(plan, Mapping):
        raise TypeError("plan must be a mapping")
    paragraphs: list[str] = []
    for section in plan.get("sections") or ():
        if not isinstance(section, Mapping):
            continue
        for block in section.get("blocks", section.get("children")) or ():
            if not isinstance(block, Mapping):
                continue
            block_type = str(block.get("type") or "").strip()
            if (
                block_type in {"heading", "paragraph"}
                and str(block.get("text") or "").strip()
            ):
                paragraphs.append(str(block.get("text") or "").strip())
            elif block_type == "table":
                for row in block.get("rows") or ():
                    if isinstance(row, Sequence) and not isinstance(
                        row, (str, bytes, bytearray)
                    ):
                        text = " ".join(
                            str(cell).strip() for cell in row if str(cell).strip()
                        )
                        if text:
                            paragraphs.append(text)
    return paragraphs


def source_paragraphs(source: Any) -> list[str]:
    """Normalize plans here and delegate generic HWPX/text reads to core."""
    if (
        isinstance(source, Mapping)
        and "sections" in source
        and "paragraphs" not in source
        and "text" not in source
    ):
        return paragraph_plan_to_paragraphs(source)
    return paragraph_texts(source)


__all__ = ["paragraph_plan_to_paragraphs", "source_paragraphs"]
