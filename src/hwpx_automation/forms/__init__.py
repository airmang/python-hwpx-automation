# SPDX-License-Identifier: Apache-2.0
"""Form guessing: table cells found by the label beside them, and check-mark choices.

These moved here from python-hwpx 7.0, which keeps the engine that reads and
writes what the file says. Each function takes the document first:

=========================================  ==============================================
python-hwpx 6.x                            here
=========================================  ==============================================
``doc.tables.find_cell_by_label(...)``     :func:`find_cell_by_label` ``(doc, ...)``
``doc.tables.form_slots(...)``             :func:`form_slots` ``(doc, ...)``
``doc.tables.fill_by_path(...)``           :func:`fill_by_path` ``(doc, ...)``
``doc.fields.choices()``                   :func:`form_choices` ``(doc)``
``doc.fields.choose(...)``                 :func:`choose` ``(doc, ...)``
=========================================  ==============================================

The table map (``doc.tables.map()``) and cell fitting (``hwpx.form_fit``) stay in
python-hwpx. This module imports only python-hwpx and the standard library.
"""

from __future__ import annotations

from .choices import (
    ChoiceApplied,
    ChoiceFailed,
    ChoiceGroup,
    ChoiceOption,
    ChoiceSelection,
    ChooseResult,
    FormChoicesResult,
    choose,
    form_choices,
)
from .labels import (
    PathDirection,
    SearchDirection,
    TableCellReference,
    TableFillApplied,
    TableFillFailed,
    TableFillResult,
    TableFormSlot,
    TableFormSlotsResult,
    TableLabelCandidate,
    TableLabelMatch,
    TableLabelSearchResult,
    fill_by_path,
    find_cell_by_label,
    form_slots,
)

__all__ = [
    "ChoiceApplied",
    "ChoiceFailed",
    "ChoiceGroup",
    "ChoiceOption",
    "ChoiceSelection",
    "ChooseResult",
    "FormChoicesResult",
    "PathDirection",
    "SearchDirection",
    "TableCellReference",
    "TableFillApplied",
    "TableFillFailed",
    "TableFillResult",
    "TableFormSlot",
    "TableFormSlotsResult",
    "TableLabelCandidate",
    "TableLabelMatch",
    "TableLabelSearchResult",
    "choose",
    "fill_by_path",
    "find_cell_by_label",
    "form_choices",
    "form_slots",
]
