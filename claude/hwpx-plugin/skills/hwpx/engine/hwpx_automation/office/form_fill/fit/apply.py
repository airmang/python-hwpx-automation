# SPDX-License-Identifier: Apache-2.0
"""Re-export of the neutral fit cell application helper that python-hwpx owns.

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

from hwpx.form_fit.apply import (  # noqa: F401 - re-exported public surface
    fit_cell_text,
)

__all__ = [
    "fit_cell_text",
]
