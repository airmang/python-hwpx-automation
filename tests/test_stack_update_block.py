# SPDX-License-Identifier: Apache-2.0
"""mcp_server_health surfaces the launcher-managed runtime update state (Feature 066 D3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpx_automation.server import mcp_server_health
from hwpx_automation.tool_contract import contract_hash

STATE = {
    "schemaVersion": "hwpx.stack-update-state.v1",
    "checkedAt": "2026-09-04T09:00:00+0900",
    "autoUpdate": True,
    "channel": "floor",
    "runtime": {
        "installed": {"python-hwpx": "6.3.0", "python-hwpx-automation": "7.0.3"},
        "latestAvailable": {"python-hwpx": "6.3.0", "python-hwpx-automation": "7.1.0"},
    },
    "pluginBundle": {"installed": "2.1.0", "latestKnown": "2.1.1"},
    "lastError": None,
}


def test_health_reports_not_managed_without_the_state_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HWPX_STACK_UPDATE_STATE", raising=False)
    assert mcp_server_health()["stackUpdate"] == {"available": False, "reason": "NOT_MANAGED"}


def test_health_surfaces_the_launcher_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "update-state.json"
    path.write_text(json.dumps(STATE), encoding="utf-8")
    monkeypatch.setenv("HWPX_STACK_UPDATE_STATE", str(path))
    block = mcp_server_health()["stackUpdate"]
    assert block["available"] is True and block["path"] == str(path)
    assert block["pluginBundle"] == {"installed": "2.1.0", "latestKnown": "2.1.1"}
    assert block["runtime"]["latestAvailable"]["python-hwpx-automation"] == "7.1.0"
    assert block["lastError"] is None and block["channel"] == "floor" and block["autoUpdate"] is True


def test_health_reports_missing_unreadable_and_unknown_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWPX_STACK_UPDATE_STATE", str(tmp_path / "absent.json"))
    assert mcp_server_health()["stackUpdate"]["reason"] == "STATE_MISSING"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("HWPX_STACK_UPDATE_STATE", str(bad))
    assert mcp_server_health()["stackUpdate"]["reason"] == "STATE_UNREADABLE"
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"schemaVersion": "something-else"}), encoding="utf-8")
    monkeypatch.setenv("HWPX_STACK_UPDATE_STATE", str(other))
    assert mcp_server_health()["stackUpdate"]["reason"] == "STATE_SCHEMA_UNKNOWN"


def test_additive_health_field_leaves_the_contract_hash_unchanged() -> None:
    assert contract_hash() == "8c278ebd5becba08"
