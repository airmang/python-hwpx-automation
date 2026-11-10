# SPDX-License-Identifier: Apache-2.0
"""Audit ARC-06 (2): the ``mutates`` flag says what the handler really does.

The hand-kept ``_MUTATING_TOOLS`` set marked five pure plan/table builders as
writers (they then queued behind the process-wide write lock) and missed two
tools that can write a file.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

import hwpx_automation.server as server
from hwpx_automation.capabilities import build_capability_report
from hwpx_automation.fastmcp_adapter import snapshot_runtime_tools
from hwpx_automation.tool_contract import TOOL_SPECS, bound_tool_registry

_SPECS = {spec.name: spec for spec in TOOL_SPECS}
_PATH_ARGUMENTS = {
    "filename", "output", "output_filename", "output_path", "source_filename",
    "destination_filename", "source_path", "path",
}
PURE_BUILDERS = (
    "build_image_grid",
    "build_meeting_nameplates",
    "build_organization_chart",
    "table_compute",
    "apply_style_profile_to_plan",
)
WRITERS = ("dump_document_blueprint", "verify_toc")


def _parameters(name: str) -> set[str]:
    return set(inspect.signature(bound_tool_registry().by_name()[name].function).parameters)


@pytest.mark.parametrize("name", PURE_BUILDERS)
def test_pure_builders_are_not_marked_as_writers(name: str) -> None:
    assert _SPECS[name].mutates is False
    # They cannot write a document: no argument names an output location.
    assert not (_parameters(name) & (_PATH_ARGUMENTS - {"reference_filename"}))


def test_writers_missed_by_the_hand_list_are_marked() -> None:
    assert "output" in _parameters("dump_document_blueprint")
    assert _SPECS["dump_document_blueprint"].mutates is True
    assert "refresh" in _parameters("verify_toc")
    assert _SPECS["verify_toc"].mutates is True


def test_live_registry_and_capability_map_carry_the_corrected_flags() -> None:
    live = snapshot_runtime_tools(server.mcp)
    for name in PURE_BUILDERS:
        if name in live:
            assert live[name].meta["hwpxMutates"] is False, name
    for name in WRITERS:
        if name in live:
            assert live[name].meta["hwpxMutates"] is True, name

    flags = {
        detail["name"]: detail["mutates"]
        for domain in build_capability_report(advanced=True)["domains"]
        for detail in domain["toolDetails"]
    }
    for name in PURE_BUILDERS:
        assert flags.get(name, False) is False, name
    for name in WRITERS:
        if name in flags:
            assert flags[name] is True, name


def test_pure_builders_really_write_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    nameplates = server.build_meeting_nameplates(["홍길동", "김철수"])
    chart = server.build_organization_chart({"name": "교장", "children": [{"name": "교감"}]})
    table = server.table_compute(
        {
            "type": "table",
            "columns": [{"key": "name", "label": "항목"}, {"key": "amount", "label": "금액"}],
            "rows": [{"name": "가", "amount": "1"}, {"name": "나", "amount": "2"}],
        },
        value_columns=["amount"],
        operations=["sum"],
    )

    assert nameplates["next_tool"] == chart["next_tool"] == "create_document_from_plan"
    assert isinstance(table, dict)
    assert os.listdir(tmp_path) == []
