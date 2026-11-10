# SPDX-License-Identifier: Apache-2.0
"""The default template registry lives inside the workspace, not the home folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hwpx_automation.server as server


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(workspace)]))
    server.create_document(str(workspace / "template.hwpx"))
    server.add_paragraph(str(workspace / "template.hwpx"), "{{student}} 귀하")
    return workspace, home


def test_default_registry_is_written_inside_workspace(sandbox) -> None:
    workspace, home = sandbox

    server.register_template("notice", str(workspace / "template.hwpx"))

    registry = workspace / ".hwpx" / "template_registry.json"
    assert registry.is_file()
    assert "notice" in json.loads(registry.read_text(encoding="utf-8"))["templates"]
    assert not (home / ".hwpx").exists()
    assert [item["name"] for item in server.list_templates()["templates"]] == ["notice"]
    assert server.describe_template("notice")["name"] == "notice"


def test_home_registry_is_not_read_by_default(sandbox) -> None:
    _, home = sandbox
    legacy = home / ".hwpx" / "template_registry.json"
    legacy.parent.mkdir()
    legacy.write_text(
        json.dumps({"templates": {"old": {"name": "old", "source": "C:/elsewhere/a.hwpx"}}}),
        encoding="utf-8",
    )

    assert server.list_templates()["templates"] == []
