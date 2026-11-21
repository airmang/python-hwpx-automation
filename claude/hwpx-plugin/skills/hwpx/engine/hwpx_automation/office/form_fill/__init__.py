# SPDX-License-Identifier: Apache-2.0
"""Canonical automation owner for application-level form-fill behavior."""

import hwpx_automation.office.form_fill.fit as fit
from .fill_residue import (
    ResidueFinding,
    ResidueReport,
    inspect_fill_residue,
)
from .guidance import (
    Candidate,
    CellLoc,
    GuidanceReport,
    LegendBinding,
    ScannedParagraph,
    is_form_instruction,
    scan_form_guidance,
)
from .quality import (
    NEEDS_REVIEW,
    UNVERIFIED,
    AxisScore,
    ScoreCard,
    score_form_fill,
)
from .split_run import (
    FillReport,
    HeterogeneousWarning,
    Placeholder,
    TextFragment,
    fill_section_bytes,
    find_split_placeholders,
    heterogeneous_warnings,
)
from .template_formfit import (
    analyze_template_formfit,
    apply_template_formfit,
)

__all__ = [
    "NEEDS_REVIEW",
    "UNVERIFIED",
    "AxisScore",
    "Candidate",
    "CellLoc",
    "FillReport",
    "GuidanceReport",
    "HeterogeneousWarning",
    "LegendBinding",
    "Placeholder",
    "ResidueFinding",
    "ResidueReport",
    "ScannedParagraph",
    "ScoreCard",
    "TextFragment",
    "analyze_template_formfit",
    "apply_template_formfit",
    "fill_section_bytes",
    "find_split_placeholders",
    "fit",
    "heterogeneous_warnings",
    "inspect_fill_residue",
    "is_form_instruction",
    "scan_form_guidance",
    "score_form_fill",
]
