# SPDX-License-Identifier: Apache-2.0
"""Proxy checks for layout drift between a reference and an output HWPX.

The structural metrics are core's: ``hwpx.tools.page_guard`` is the one
implementation, re-exported here under the existing import path with the same
names, dataclass, signatures, defaults, comparison messages and CLI (#177).
Which threshold a workflow uses, and what it does with a drift, stays with the
workflow that calls these.

This module does not calculate rendered page counts. It compares structural and
textual metrics that often correlate with page-layout drift.

Invalid section XML raises ``xml.etree.ElementTree.ParseError`` (core reads with
the standard library); the copy this replaced raised
``lxml.etree.XMLSyntaxError``. Both are ``SyntaxError`` subclasses.
"""

from __future__ import annotations

from hwpx.tools.page_guard import (
    DocumentMetrics,
    collect_metrics,
    compare_metrics,
    main,
)

__all__ = [
    "DocumentMetrics",
    "collect_metrics",
    "compare_metrics",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    raise SystemExit(main())
