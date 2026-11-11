# SPDX-License-Identifier: Apache-2.0
"""Per-request state kept by a long-lived server is bounded and expires."""

from __future__ import annotations

from pathlib import Path

import pytest

import hwpx_automation.server as server
from hwpx_automation import form_fill, mixed_form
from hwpx_automation.utils.helpers import BoundedExpiringStore


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_store_drops_the_oldest_entry_at_the_limit() -> None:
    store = BoundedExpiringStore(max_entries=3, ttl_seconds=60)

    for index in range(5):
        store[f"k{index}"] = index

    assert list(store) == ["k2", "k3", "k4"]
    assert len(store) == 3
    assert "k0" not in store
    assert store["k4"] == 4


def test_store_entries_expire() -> None:
    clock = _Clock()
    store = BoundedExpiringStore(max_entries=10, ttl_seconds=30, clock=clock)
    store["old"] = 1
    clock.now += 20
    store["new"] = 2
    clock.now += 15

    assert "old" not in store
    assert store.get("old") is None
    assert store["new"] == 2
    with pytest.raises(KeyError):
        store["old"]
    clock.now += 100
    assert len(store) == 0


def test_store_behaves_like_a_mapping_for_replay_callers() -> None:
    store = BoundedExpiringStore(max_entries=2, ttl_seconds=60)
    store["a"] = {"requestHash": "h", "result": 1}

    assert "a" in store
    assert store.pop("a")["result"] == 1
    assert store.pop("a", None) is None
    store["b"] = 1
    store.clear()
    assert len(store) == 0


def test_store_rejects_meaningless_limits() -> None:
    with pytest.raises(ValueError):
        BoundedExpiringStore(max_entries=0, ttl_seconds=1)
    with pytest.raises(ValueError):
        BoundedExpiringStore(max_entries=1, ttl_seconds=0)


def test_process_stores_are_bounded() -> None:
    for store in (form_fill._FORM_FILL_PLANS, mixed_form._IDEMPOTENCY_STORE):
        assert isinstance(store, BoundedExpiringStore)
        assert store.max_entries <= 512
        assert store.ttl_seconds <= 24 * 60 * 60


def test_repeated_analysis_does_not_grow_without_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "form.hwpx"
    server.create_document(str(source))
    bounded = BoundedExpiringStore(max_entries=2, ttl_seconds=60)
    monkeypatch.setattr(form_fill, "_FORM_FILL_PLANS", bounded)

    plan_ids = [
        form_fill.analyze_form_fill_workflow(
            source_filename=str(source), input_json={"fields": []}
        )["plan_id"]
        for _ in range(4)
    ]

    assert len(bounded) == 2
    assert list(bounded) == plan_ids[-2:]
    with pytest.raises(ValueError, match="unknown or expired"):
        form_fill._resolve_analysis(plan_id=plan_ids[0], analysis=None)
    assert form_fill._resolve_analysis(plan_id=plan_ids[-1], analysis=None)["plan_id"] == plan_ids[-1]
