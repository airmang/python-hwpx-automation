# SPDX-License-Identifier: Apache-2.0
"""Transaction helpers for hardened editing pipeline."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Generic, TypeVar


class TransactionError(RuntimeError):
    """Base error for transaction handling."""


class IdempotentReplayError(TransactionError):
    """Raised when the same idempotency key is replayed."""

    def __init__(self, key: str) -> None:
        super().__init__(f"idempotency key '{key}' has already been processed")
        self.key = key


T = TypeVar("T")


class TransactionManager(Generic[T]):
    """Provide atomic execution and idempotency tracking."""

    def __init__(self) -> None:
        self._idempotency: Dict[str, Dict[str, Any]] = {}

    def ensure_idempotency(self, scope: str, key: str) -> None:
        token = self._token(scope, key)
        if token in self._idempotency:
            raise IdempotentReplayError(key)

    def record_idempotency(self, scope: str, key: str, payload: Dict[str, Any]) -> None:
        token = self._token(scope, key)
        self._idempotency[token] = dict(payload)

    def atomic(self, snapshot: T, mutator: Callable[[T], T], applier: Callable[[T], None]) -> T:
        working_copy = copy.deepcopy(snapshot)
        result = mutator(working_copy)
        applier(result)
        return result

    @staticmethod
    def _token(scope: str, key: str) -> str:
        return f"{scope}::{key}"
