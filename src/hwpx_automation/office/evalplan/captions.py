# SPDX-License-Identifier: Apache-2.0
"""Evaluation-plan label selection over core's neutral trailing-text edit."""

from __future__ import annotations

import re
from pathlib import Path

from hwpx.table_patch import CellFillResult, strip_trailing_table_text

_SHORT_ORDINAL_LABEL = re.compile(r"\(\d+\)\s*\S{1,8}")


def _is_caption(text: str) -> bool:
    return bool(_SHORT_ORDINAL_LABEL.fullmatch(text))


def strip_evalplan_table_captions(
    source: str | Path | bytes,
    *,
    output_path: str | Path | None = None,
) -> CellFillResult:
    """Remove short ordinal labels only where core proves an eligible text tail."""
    return strip_trailing_table_text(
        source, predicate=_is_caption, output_path=output_path
    )


__all__ = ["strip_evalplan_table_captions"]
