# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any

from ..configuration import env_int
from ..workspace import WorkspaceResolver


class BoundedExpiringStore(MutableMapping[str, Any]):
    """A process-local mapping with an entry limit and a time-to-live.

    Long-lived servers keep per-request state here (analysis plans, replay
    results). Without a bound that state grows with every call. The oldest
    entry is dropped when the limit is reached, and an entry older than
    ``ttl_seconds`` behaves as if it had never been stored.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    def _purge(self) -> None:
        deadline = self._clock() - self.ttl_seconds
        while self._items:
            key, (stored_at, _) = next(iter(self._items.items()))
            if stored_at > deadline:
                break
            del self._items[key]

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            self._purge()
            return self._items[key][1]

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._purge()
            self._items.pop(key, None)
            self._items[key] = (self._clock(), value)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._items[key]

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            self._purge()
            return iter(list(self._items))

    def __len__(self) -> int:
        with self._lock:
            self._purge()
            return len(self._items)


def default_max_chars() -> int:
    return max(1, env_int("MAX_CHARS", 10000))


MAX_CHARS = default_max_chars()


def resolve_path(filename: str) -> str:
    return str(WorkspaceResolver.from_environment().resolve(filename, must_exist=False))


def truncate_response(text: str, max_chars: int = None) -> dict:
    if max_chars is None:
        max_chars = default_max_chars()
    total = len(text)
    if total <= max_chars:
        return {"text": text, "total_chars": total, "truncated": False}
    return {
        "text": text[:max_chars],
        "total_chars": total,
        "truncated": True,
    }
