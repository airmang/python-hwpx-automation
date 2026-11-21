# SPDX-License-Identifier: Apache-2.0
"""Re-export of the neutral fit measurement model that python-hwpx owns.

This module used to be a copy. The two versions were behaviourally identical —
comparing normalised syntax trees showed no semantic difference across the five
fit-contract modules, only comment alignment and whether a forward reference was
quoted — so maintaining both bought nothing and cost a drift risk that had
already come due elsewhere in this stack.

Slot measurement and the keep/wrap/shrink ladder are format reasoning, not
application policy: core's own table and field APIs call them. What this layer
owns is the application half — seal placement, PDF extraction, institutional
rules — which stays here and is not re-exported from core.
"""

from __future__ import annotations

from hwpx.form_fit.measure import (  # noqa: F401 - re-exported public surface
    Confidence,
    DEFAULT_LINE_SPACING_RATIO,
    DEFAULT_SAFETY,
    GROSS_ROW_GROWTH_FACTOR,
    MIN_LINE_SPACING_RATIO,
    MIN_ROW_GROWTH_LINES,
    Measurement,
    SlotMetrics,
    char_advance,
    classify_char,
    estimate_lines,
    estimate_text_width,
    measure,
    resolve_slot_metrics,
)

__all__ = [
    "Confidence",
    "DEFAULT_LINE_SPACING_RATIO",
    "DEFAULT_SAFETY",
    "GROSS_ROW_GROWTH_FACTOR",
    "MIN_LINE_SPACING_RATIO",
    "MIN_ROW_GROWTH_LINES",
    "Measurement",
    "SlotMetrics",
    "char_advance",
    "classify_char",
    "estimate_lines",
    "estimate_text_width",
    "measure",
    "resolve_slot_metrics",
]
