# SPDX-License-Identifier: Apache-2.0
"""Canonical application utilities unrelated to HWPX format semantics."""

from .report_utils import (
    calculate_age,
    calculate_ratios,
    format_delta,
    format_delta_percent,
    format_krw_hangul,
    format_number_commas,
    normalize_korean_date,
)
from .table_cleanup import (
    add_reverse_sum,
    add_sequence_column,
    normalize_cell_text,
    normalize_table_rows,
)
from .table_compute import (
    TABLE_COMPUTE_REPORT_VERSION,
    table_compute,
)

__all__ = [
    "TABLE_COMPUTE_REPORT_VERSION",
    "add_reverse_sum",
    "add_sequence_column",
    "calculate_age",
    "calculate_ratios",
    "format_delta",
    "format_delta_percent",
    "format_krw_hangul",
    "format_number_commas",
    "normalize_cell_text",
    "normalize_korean_date",
    "normalize_table_rows",
    "table_compute",
]
