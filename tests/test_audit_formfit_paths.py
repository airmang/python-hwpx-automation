# SPDX-License-Identifier: Apache-2.0
"""apply_template_formfit keeps every path inside the workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hwpx_automation.server as server
from hwpx_automation.workspace import WorkspacePathError


def _narrow_roots(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(root)]))


def _document(path: Path, text: str = "본문") -> None:
    server.create_document(str(path))
    server.add_paragraph(str(path), text)


def _analysis(source: Path, destination: Path) -> dict:
    return {
        "source": {"path": str(source)},
        "destination": {"path": str(destination)},
        "resolved": [],
        "unresolved": [],
    }


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    _document(workspace / "inside.hwpx")
    _document(outside / "private.hwpx", "밖의 문서")
    _narrow_roots(monkeypatch, workspace)
    return workspace, outside


def test_analysis_source_outside_workspace_is_refused(boundary) -> None:
    workspace, outside = boundary
    copied = workspace / "copied.hwpx"

    with pytest.raises(WorkspacePathError):
        server.apply_template_formfit(
            analysis=_analysis(outside / "private.hwpx", copied), confirm=True
        )

    assert not copied.exists()


def test_analysis_destination_outside_workspace_is_refused(boundary) -> None:
    workspace, outside = boundary
    victim = outside / "victim.cfg"
    victim.write_bytes(b"ORIGINAL")
    planted = outside / "newdir" / "sub" / "planted.hwpx"

    for target in (victim, planted):
        with pytest.raises(WorkspacePathError):
            server.apply_template_formfit(
                analysis=_analysis(workspace / "inside.hwpx", target), confirm=True
            )

    assert victim.read_bytes() == b"ORIGINAL"
    assert not (outside / "newdir").exists()


def test_existing_destination_is_not_overwritten(boundary) -> None:
    workspace, _ = boundary
    existing = workspace / "existing.hwpx"
    existing.write_bytes(b"KEEP")

    result = server.apply_template_formfit(
        analysis=_analysis(workspace / "inside.hwpx", existing), confirm=True
    )

    assert result["handoff_status"] == "blocked"
    assert "exists" in result["reason"]
    assert existing.read_bytes() == b"KEEP"
    assert [p.name for p in workspace.iterdir() if p.suffix == ".tmp"] == []


def test_existing_destination_argument_is_not_overwritten(boundary) -> None:
    workspace, _ = boundary
    existing = workspace / "existing.hwpx"
    existing.write_bytes(b"KEEP")

    result = server.apply_template_formfit(
        analysis=_analysis(workspace / "inside.hwpx", workspace / "unused.hwpx"),
        destination_filename=str(existing),
        confirm=True,
    )

    assert result["handoff_status"] == "blocked"
    assert existing.read_bytes() == b"KEEP"


def test_malformed_analysis_paths_are_rejected(boundary) -> None:
    workspace, _ = boundary

    with pytest.raises(ValueError):
        server.apply_template_formfit(
            analysis={"source": "inside.hwpx", "destination": {"path": "out.hwpx"}},
            confirm=True,
        )


def test_inside_workspace_copy_still_works(boundary) -> None:
    workspace, _ = boundary
    destination = workspace / "nested" / "filled.hwpx"

    result = server.apply_template_formfit(
        analysis=_analysis(workspace / "inside.hwpx", destination), confirm=True
    )

    assert result["handoff_status"] == "ready"
    assert destination.is_file()
