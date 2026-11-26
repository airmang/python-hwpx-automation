# SPDX-License-Identifier: Apache-2.0
"""``apply_form_fill(plan=)`` works wherever the documents sit inside the workspace.

The plan's publisher writes through the environment's workspace, whose root is the workspace
root; the request then read the published file back through a workspace rooted at the document's
own folder. The two only agreed when the document sat directly under the root, so every apply in a
subfolder ended ``verification_failed`` and was rolled back (8.0.0 too).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from test_mixed_form_mcp import _build_fixture, _plan

import hwpx_automation.server as server
from hwpx_automation.office.agent import _batch_publication


def _folder(tmp_path: Path, sub: str) -> Path:
    folder = tmp_path / sub if sub else tmp_path
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _contents(folder: Path) -> dict[str, bytes]:
    return {entry.name: entry.read_bytes() for entry in folder.iterdir() if entry.is_file()}


@pytest.mark.parametrize("sub", ["", "documents", "a/b"])
def test_a_plan_is_applied_wherever_the_documents_sit(sub: str, tmp_path: Path) -> None:
    folder = _folder(tmp_path, sub)
    source, output = folder / "source.hwpx", folder / "out.hwpx"
    _build_fixture(source)
    before = source.read_bytes()

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is True
    assert output.is_file() and output.read_bytes() != before
    assert source.read_bytes() == before
    assert sorted(_contents(folder)) == ["out.hwpx", "source.hwpx"]


@pytest.mark.parametrize("sub", ["", "documents"])
def test_the_output_may_sit_in_another_folder_than_the_source(sub: str, tmp_path: Path) -> None:
    folder = _folder(tmp_path, sub)
    results = tmp_path / "results"
    results.mkdir()
    source, output = folder / "source.hwpx", results / "out.hwpx"
    _build_fixture(source)

    result = server.apply_form_fill(plan=_plan(source, output))

    assert result["ok"] is True
    assert output.is_file()


@pytest.mark.parametrize("sub", ["", "documents"])
def test_a_failure_after_publishing_takes_the_output_back(
    sub: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path, sub)
    source, output = folder / "source.hwpx", folder / "out.hwpx"
    _build_fixture(source)
    before = _contents(folder)

    original = _batch_publication.BatchPublication.assert_current_source
    calls = {"n": 0}

    def fail_after_publishing(self) -> None:  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if self.publication_attempted and self.publisher is not None and self.publisher.publication is not None:
            raise _batch_publication.AgentContractError(
                "stale_revision", "synthetic failure after publishing", target="batch.input.filename"
            )
        original(self)

    monkeypatch.setattr(_batch_publication.BatchPublication, "assert_current_source", fail_after_publishing)

    result = server.apply_form_fill(plan=_plan(source, output))

    assert calls["n"] >= 2
    assert result["ok"] is False
    assert not output.exists()
    assert _contents(folder) == before
