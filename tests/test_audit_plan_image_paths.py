# SPDX-License-Identifier: Apache-2.0
"""Images named by a document plan must be real images inside the workspace."""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest

import hwpx_automation.server as server
from hwpx_automation.office.authoring.builder import core as builder_core
from hwpx_automation.workspace import WorkspacePathError

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
MARKER = b"OUTSIDE-FILE-CONTENT-MARKER"


def _plan(*blocks: dict) -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v2",
        "title": "그림 시험",
        "sections": [{"blocks": [{"type": "paragraph", "text": "본문"}, *blocks]}],
    }


def _package_contains(path: Path, needle: bytes) -> bool:
    with zipfile.ZipFile(path) as archive:
        return any(needle in archive.read(name) for name in archive.namelist())


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "key.png").write_bytes(MARKER)
    (outside / "real.png").write_bytes(_PNG_1X1)
    (workspace / "real.png").write_bytes(_PNG_1X1)
    (workspace / "notes.png").write_bytes(MARKER)
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(workspace)]))
    return workspace, outside


def _create(target: Path, *blocks: dict) -> dict:
    return server.create_document_from_plan(str(target), _plan(*blocks))


def _assert_not_embedded(target: Path, needle: bytes) -> None:
    assert not target.exists() or not _package_contains(target, needle)


@pytest.mark.parametrize("name", ["key.png", "real.png"])
def test_image_block_outside_workspace_is_refused(boundary, name: str) -> None:
    workspace, outside = boundary
    target = workspace / "out.hwpx"

    with pytest.raises(WorkspacePathError):
        _create(target, {"type": "image", "path": str(outside / name)})

    _assert_not_embedded(target, MARKER)


def test_image_grid_outside_workspace_is_refused(boundary) -> None:
    workspace, outside = boundary
    target = workspace / "out.hwpx"

    with pytest.raises(WorkspacePathError):
        _create(
            target,
            {
                "type": "image_grid",
                "images": [{"path": str(outside / "key.png"), "caption": "가"}],
            },
        )

    _assert_not_embedded(target, MARKER)


def test_non_image_file_inside_workspace_is_refused(boundary) -> None:
    workspace, _ = boundary
    target = workspace / "out.hwpx"

    with pytest.raises(ValueError):
        _create(target, {"type": "image", "path": str(workspace / "notes.png")})

    _assert_not_embedded(target, MARKER)


def test_oversized_image_is_refused(boundary, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _ = boundary
    monkeypatch.setattr(builder_core, "MAX_IMAGE_BYTES", len(_PNG_1X1) - 1)

    with pytest.raises(ValueError):
        _create(workspace / "out.hwpx", {"type": "image", "path": "real.png"})


def test_builder_rejects_bytes_that_are_not_an_image() -> None:
    with pytest.raises(ValueError):
        builder_core.validate_image_bytes(MARKER, "png")
    builder_core.validate_image_bytes(_PNG_1X1, "png")


def test_real_image_inside_workspace_is_embedded(boundary) -> None:
    workspace, _ = boundary
    target = workspace / "out.hwpx"

    _create(target, {"type": "image", "path": str(workspace / "real.png")})

    assert target.is_file()
    assert _package_contains(target, _PNG_1X1)
