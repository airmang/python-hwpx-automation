# SPDX-License-Identifier: Apache-2.0
"""Hancom-bound redline verification at the automation application boundary."""

from __future__ import annotations

from os import PathLike
from typing import Any

from hwpx.quality.rendering import RenderBackend
from hwpx.tools.redline import REDLINE_VERIFY_REPORT_VERSION
from hwpx.tools.redline import verify_redline as _core_verify_redline

from ..rendering import resolve_hancom_backend


def verify_redline(
    before_hwpx: str | PathLike[str],
    after_hwpx: str | PathLike[str],
    *,
    oracle: RenderBackend | None = None,
) -> dict[str, Any]:
    """Combine neutral structure evidence with canonical Hancom rendering.

    The judgement itself is core's — structure, degrade rules, and report shape
    live in :func:`hwpx.tools.redline.verify_redline`. What this layer owns is
    finding a renderer, which is why it supplies a backend when the caller does
    not. Previously this function was a line-for-line copy of core's, and the two
    drifted apart the moment one side was patched; there is now one implementation.
    """

    backend = oracle if oracle is not None else resolve_hancom_backend()
    return _core_verify_redline(before_hwpx, after_hwpx, oracle=backend)


__all__ = ["REDLINE_VERIFY_REPORT_VERSION", "verify_redline"]
