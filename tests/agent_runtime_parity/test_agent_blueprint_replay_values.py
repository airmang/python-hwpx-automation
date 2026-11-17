"""Blueprint replay refuses a value python-hwpx would refuse with a contract error naming the node."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from hwpx_automation.office.agent.blueprint import read_blueprint_bundle, repack_blueprint_bundle, replay_document_blueprint

from .test_agent_blueprint_replay import _portable_fixture, _request


def _replay_with(tmp_path: Path, kind: str, name: str, value: object):
    bundle, target, _blueprint_hash, _source = _portable_fixture(tmp_path)
    edited = deepcopy(read_blueprint_bundle(bundle.read_bytes()).manifest)
    node = next(node for node in edited["nodes"] if node["kind"] == kind)
    node["properties"][name] = value
    changed = tmp_path / "changed.hwpxbp"
    repacked = repack_blueprint_bundle(bundle.read_bytes(), changed, edited)
    output = tmp_path / "output.hwpx"
    result = replay_document_blueprint(_request(changed, str(repacked.manifest["blueprintHash"]), target, output))
    return result, node["blueprintId"], output


@pytest.mark.parametrize(
    ("kind", "name", "value", "listed"),
    [
        ("table", "alignment", "JUSTIFY", ["CENTER", "INSIDE", "LEFT", "OUTSIDE", "RIGHT"]),
        ("cell", "verticalAlignment", "MIDDLE", ["BOTTOM", "CENTER", "TOP"]),
    ],
)
def test_alignment_outside_the_values_is_a_contract_error_on_its_node(
    tmp_path: Path, kind: str, name: str, value: str, listed: list[str]
) -> None:
    result, node_id, output = _replay_with(tmp_path, kind, name, value)

    assert result.ok is False
    assert result.rolled_back is True
    assert result.error is not None
    assert result.error.code == "invalid_syntax"
    assert result.error.target == node_id
    assert str(listed) in result.error.message and repr(value) in result.error.message
    assert not output.exists()


@pytest.mark.parametrize(("kind", "name", "value"), [("table", "alignment", "RIGHT"), ("cell", "verticalAlignment", "BOTTOM")])
def test_alignment_among_the_values_is_replayed(tmp_path: Path, kind: str, name: str, value: str) -> None:
    result, _node_id, output = _replay_with(tmp_path, kind, name, value)

    assert result.ok is True
    assert output.exists()
