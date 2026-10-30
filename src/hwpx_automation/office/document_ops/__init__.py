# SPDX-License-Identifier: Apache-2.0
"""Canonical application owners for compare, bulk merge, and redline review."""

from .comparison import build_comparison_table_plan
from .mail_merge import build_mail_merge, inspect_mail_merge_placeholders
from .redline import verify_redline
from .sources import paragraph_plan_to_paragraphs

__all__ = [
    "build_comparison_table_plan",
    "build_mail_merge",
    "inspect_mail_merge_placeholders",
    "paragraph_plan_to_paragraphs",
    "verify_redline",
]
