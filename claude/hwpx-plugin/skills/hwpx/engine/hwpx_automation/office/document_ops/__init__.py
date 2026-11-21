# SPDX-License-Identifier: Apache-2.0
"""Canonical application owners for compare, bulk merge, and redline review."""

from .comparison import build_comparison_table_plan
from .mail_merge import build_mail_merge, inspect_mail_merge_placeholders
from .redline import verify_redline

__all__ = [
    "build_comparison_table_plan",
    "build_mail_merge",
    "inspect_mail_merge_placeholders",
    "verify_redline",
]
