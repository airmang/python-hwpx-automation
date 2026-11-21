# SPDX-License-Identifier: Apache-2.0
"""Canonical office document-quality policy owners."""

from .page_guard import (
    DocumentMetrics,
    collect_metrics,
    compare_metrics,
)

__all__ = [
    "DocumentMetrics",
    "collect_metrics",
    "compare_metrics",
]
