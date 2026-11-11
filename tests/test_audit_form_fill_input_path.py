# SPDX-License-Identifier: Apache-2.0
"""The input_json string form reads files only inside the workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hwpx_automation.server as server
from hwpx_automation import form_fill
from hwpx_automation.workspace import WorkspacePathError

MARKER = "OUTSIDE-MARKER-VALUE"


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    server.create_document(str(workspace / "form.hwpx"))
    (outside / "settings.json").write_text(
        json.dumps({"token": MARKER}), encoding="utf-8"
    )
    (workspace / "input.json").write_text(
        json.dumps({"fields": []}), encoding="utf-8"
    )
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(workspace)]))
    return workspace, outside


def test_input_json_path_outside_workspace_is_refused(boundary) -> None:
    workspace, outside = boundary

    with pytest.raises(WorkspacePathError):
        form_fill.analyze_form_fill_workflow(
            source_filename=str(workspace / "form.hwpx"),
            input_json=str(outside / "settings.json"),
        )


def test_apply_canonical_input_path_outside_workspace_is_refused(boundary) -> None:
    _, outside = boundary

    with pytest.raises(WorkspacePathError):
        form_fill._load_canonical_input(input_json=str(outside / "settings.json"))


def test_input_json_path_inside_workspace_still_loads(boundary) -> None:
    workspace, _ = boundary

    by_path = form_fill._load_canonical_input(input_json=str(workspace / "input.json"))
    relative = form_fill._load_canonical_input(input_json="input.json")
    inline = form_fill._load_canonical_input(input_json='{"fields": []}')

    assert by_path["fields"] == relative["fields"] == inline["fields"] == []


def test_inline_json_is_never_treated_as_a_path(boundary) -> None:
    payload = form_fill._load_canonical_input(
        input_json='{"fields": [], "note": "a.json"}'
    )
    assert payload["note"] == "a.json"
