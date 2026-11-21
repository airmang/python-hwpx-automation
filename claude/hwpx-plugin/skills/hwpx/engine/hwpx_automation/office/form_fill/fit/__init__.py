# SPDX-License-Identifier: Apache-2.0
"""Form-fit decision, reporting, and geometry owned by the automation layer."""

import hwpx_automation.office.form_fill.fit.seal as seal
import hwpx_automation.office.form_fill.fit.wordbox as wordbox
from .engine import FitEngine
from .measure import (
    DEFAULT_SAFETY,
    Measurement,
    SlotMetrics,
    estimate_lines,
    estimate_text_width,
    measure,
    resolve_slot_metrics,
)
from .policy import FitMode, FitPolicy, OverflowAction
from .report import FIELD_OVERFLOW, FitResult, to_form_report

__all__ = [
    "DEFAULT_SAFETY",
    "FIELD_OVERFLOW",
    "FitEngine",
    "FitMode",
    "FitPolicy",
    "FitResult",
    "Measurement",
    "OverflowAction",
    "SlotMetrics",
    "estimate_lines",
    "estimate_text_width",
    "measure",
    "resolve_slot_metrics",
    "seal",
    "to_form_report",
    "wordbox",
]
