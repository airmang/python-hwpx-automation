# SPDX-License-Identifier: Apache-2.0
"""Helpers for generating stable handles for logical nodes."""

from __future__ import annotations

import hashlib
from typing import Iterable, Tuple


def _normalize_parts(parts: Iterable[str | int]) -> Tuple[str, ...]:
    normalized: list[str] = []
    for part in parts:
        text = str(part)
        normalized.append(text)
    return tuple(normalized)


def stable_node_id(parts: Iterable[str | int]) -> str:
    """Return a deterministic identifier for the provided structural path."""

    normalized = _normalize_parts(parts)
    joined = "::".join(normalized)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"n_{digest}"
