# SPDX-License-Identifier: Apache-2.0
"""Workflow source and output paths stay inside the workspace."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpx_automation.workflow import WorkflowStore
from hwpx_automation.workflow.models import WorkFamily, WorkOrder
from hwpx_automation.workflow.service import WorkflowService
from hwpx_automation.workspace import WorkspacePathError


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "source.hwpx").write_bytes(b"inside")
    (outside / "key.txt").write_bytes(b"outside-content")
    monkeypatch.setenv("HWPX_AUTOMATION_WORKSPACE_ROOTS", json.dumps([str(workspace)]))
    return workspace, outside


def _service(tmp_path: Path) -> WorkflowService:
    return WorkflowService({}, store=WorkflowStore(tmp_path / "store.sqlite3"))


@pytest.mark.parametrize("argument", ["source_path", "output_path"])
def test_start_refuses_paths_outside_workspace(boundary, tmp_path, argument) -> None:
    workspace, outside = boundary
    arguments = {
        "source_path": str(workspace / "source.hwpx"),
        "output_path": str(workspace / "out.hwpx"),
    }
    arguments[argument] = str(outside / "key.txt")

    with pytest.raises(WorkspacePathError):
        _service(tmp_path).start(
            family="must_abstain", idempotency_key="audit-outside-path", **arguments
        )


def test_start_refuses_new_file_outside_workspace(boundary, tmp_path) -> None:
    workspace, outside = boundary

    with pytest.raises(WorkspacePathError):
        _service(tmp_path).start(
            family="transactional_edit",
            idempotency_key="audit-outside-new",
            source_path=str(workspace / "source.hwpx"),
            output_path=str(outside / "startup" / "dropped.hwpx"),
            parameters={"operations": []},
        )

    assert not (outside / "startup").exists()


def test_stored_record_with_outside_path_is_not_acted_on(boundary, tmp_path) -> None:
    """A record written before the boundary existed must not be continued."""

    _, outside = boundary
    store = WorkflowStore(tmp_path / "store.sqlite3")
    order = WorkOrder(
        family=WorkFamily.TRANSACTIONAL_EDIT,
        idempotency_key="audit-stored-record",
        source_path=str(outside / "key.txt"),
        output_path=str(outside / "copy.hwpx"),
        expected_revision="sha256:unused",
        parameters={"operations": []},
    )
    record, _ = store.create(order, original_content_hash=None)
    service = WorkflowService({}, store=store)

    receipt = service.get(record.workflow_id)
    assert all(item["contentHash"] is None for item in receipt["artifacts"])
    with pytest.raises(WorkspacePathError):
        service.continue_workflow(record.workflow_id)
    assert not (outside / "copy.hwpx").exists()


def test_inside_paths_are_accepted_and_normalized(boundary, tmp_path) -> None:
    workspace, _ = boundary

    receipt = _service(tmp_path).start(
        family="must_abstain",
        idempotency_key="audit-inside-path",
        source_path=str(workspace / "source.hwpx"),
        output_path="relative-out.hwpx",
    )

    paths = {item["role"]: Path(item["path"]) for item in receipt["artifacts"]}
    assert paths["source"] == (workspace / "source.hwpx").resolve()
    assert paths["output"] == (workspace / "relative-out.hwpx").resolve()
