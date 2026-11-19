# SPDX-License-Identifier: Apache-2.0
"""Where an object or text lands in a paragraph, and what a request that names no version means.

A request whose commands name no ``schemaVersion`` (the MCP tool builds the batch itself) is not
silently given another meaning than it had in 7.x: where agent-command v1 and v2 put the same
command in different places, it is refused with ``contract_changed`` and told to name a version.
v1 ``append`` put an object at the end of the paragraph's text, as v2 does; v1 ``prepend`` put it
before the first object of its kind (or, with none, at the end), v2 puts it at offset 0 — measured
against hwpx-automation 7.5.0 with python-hwpx 6.12.0.

``before``/``after`` an object keep their meaning when several objects share its character offset:
the new table or text goes right before / right after that object, not after all of them.
"""

from __future__ import annotations

import json
import re
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from hwpx import HwpxDocument
from lxml import etree

from hwpx_automation.handlers.agent_document import apply_document_commands
from hwpx_automation.office.agent import HwpxAgentDocument

V1 = "hwpx.agent-command/v1"
V2 = "hwpx.agent-command/v2"


def _source(path: Path) -> dict[str, Any]:
    """Paragraph 1: "AB", a one-row table, "CD". Paragraph 2: "EF"."""

    with HwpxDocument.new() as document:
        first = document.paragraphs[0]
        first.text = "AB"
        first.add_table(1, 1)
        first.add_run("CD")
        document.add_paragraph("EF")
        document.save(path)
    with HwpxAgentDocument.open(path) as view:
        paragraphs = [r.path for r in view.records if r.parent_path == "/section[1]" and r.kind == "paragraph"]
        table = next(r.path for r in view.records if r.kind == "table")
    return {"one": paragraphs[0], "none": paragraphs[1], "table": table}


def _neighbours(path: Path) -> dict[str, Any]:
    """Paragraph "A" with a one-row and a two-row table, both at offset 1."""

    with HwpxDocument.new() as document:
        paragraph = document.add_paragraph("A")
        paragraph.add_table(1, 1)
        paragraph.add_table(2, 1)
        document.save(path)
    with HwpxAgentDocument.open(path) as view:
        paragraph_path = next(
            r.path for r in view.records if r.kind == "paragraph" and r.parent_path == "/section[1]" and r.summary.get("text") == "A"
        )
        tables = [r.path for r in view.records if r.kind == "table" and r.parent_path == paragraph_path]
    return {"paragraph": paragraph_path, "tables": tables}


def _layout(path: Path) -> list[list[str]]:
    """Each body paragraph's runs' content in order: texts, and tables as T<rows>."""

    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
    layout = []
    for paragraph in root:
        if etree.QName(paragraph).localname != "p":
            continue
        order: list[tuple[str, str]] = []  # (kind, value): neighbouring text is one stretch
        for element in paragraph.xpath('./*[local-name()="run"]/*'):
            name = etree.QName(element).localname
            if name == "tbl":
                order.append(("table", "T" + element.get("rowCnt")))
            elif name == "t" and element.text:
                if order and order[-1][0] == "text":
                    order[-1] = ("text", order[-1][1] + element.text)
                else:
                    order.append(("text", element.text))
        if order:
            layout.append([value for _kind, value in order])
    return layout


def _call(source: Path, output: Path, command: dict[str, Any], version: str | None = None) -> dict[str, Any]:
    command = {"commandId": "c", **command}
    if version is not None:
        command["schemaVersion"] = version
    return apply_document_commands(
        str(source),
        str(output),
        [command],
        expected_revision="sha256:" + sha256(source.read_bytes()).hexdigest(),
        overwrite=True,
    )


def _table(parent: str, position: dict[str, Any], rows: int = 2) -> dict[str, Any]:
    return {"op": "add", "kind": "table", "parent": parent, "position": position,
            "properties": {"rowCount": rows, "columnCount": 1}}


def _text(parent: str, position: dict[str, Any], text: str = "X") -> dict[str, Any]:
    return {"op": "add", "kind": "text", "parent": parent, "position": position, "properties": {"text": text}}


def _suggested_positions(suggestion: str) -> list[dict[str, Any]]:
    """Every {"mode": ...} object in a suggestion, read as JSON (so a path's quotes must be escaped)."""

    found = []
    for match in re.finditer(r'\{"mode": ', suggestion):
        decoder = json.JSONDecoder()
        value, _end = decoder.raw_decode(suggestion[match.start():])
        found.append(value)
    return found


# --- a request that names no version ---------------------------------------------------------


def test_versionless_prepend_whose_v1_place_differs_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _source(source)
    for parent in ("one", "none"):
        output = tmp_path / f"{parent}.hwpx"
        result = _call(source, output, _table(paths[parent], {"mode": "prepend"}))
        assert result["ok"] is False, parent
        assert result["error"]["code"] == "contract_changed"
        assert "schemaVersion" in result["error"]["suggestion"]
        assert not output.exists()


def test_versionless_append_means_the_same_in_v1_and_v2_and_is_taken(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _source(source)
    one, none = tmp_path / "one.hwpx", tmp_path / "none.hwpx"
    assert _call(source, one, _table(paths["one"], {"mode": "append"}))["ok"]
    assert _call(source, none, _table(paths["none"], {"mode": "append"}))["ok"]
    assert _layout(one) == [["AB", "T1", "CD", "T2"], ["EF"]]  # 7.5.0: the end of the text
    assert _layout(none) == [["AB", "T1", "CD"], ["EF", "T2"]]


def test_versionless_text_and_declared_versions_keep_their_meaning(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _source(source)
    text, v2, v1 = tmp_path / "text.hwpx", tmp_path / "v2.hwpx", tmp_path / "v1.hwpx"
    assert _call(source, text, _text(paths["none"], {"mode": "prepend"}))["ok"]  # text is v2 only
    assert _layout(text)[-1] == ["XEF"]
    assert _call(source, v2, _table(paths["none"], {"mode": "prepend"}), V2)["ok"]
    assert _layout(v2)[-1] == ["T2", "EF"]
    # v1 append went to the end of the text, as v2: taken, not refused
    assert _call(source, v1, _table(paths["one"], {"mode": "append"}), V1)["ok"]
    assert _layout(v1)[0] == ["AB", "T1", "CD", "T2"]


def test_the_suggestion_reproduces_the_v1_place_and_is_json(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _source(source)
    expected = {"one": ["AB", "T2", "T1", "CD"], "none": ["EF", "T2"]}  # what 7.5.0 wrote
    for parent, line in (("one", 0), ("none", 1)):
        refused = _call(source, tmp_path / "x.hwpx", _table(paths[parent], {"mode": "prepend"}), V1)
        assert refused["error"]["code"] == "contract_changed"
        positions = _suggested_positions(refused["error"]["suggestion"])
        assert positions, refused["error"]["suggestion"]
        retried = tmp_path / f"{parent}-retry.hwpx"
        assert _call(source, retried, _table(paths[parent], positions[0]), V2)["ok"]
        assert _layout(retried)[line] == expected[parent], positions[0]


# --- several objects at one character offset ------------------------------------------------


def test_after_an_object_goes_right_after_it_among_objects_at_the_same_offset(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _neighbours(source)
    first, second = paths["tables"]
    cases = {
        "after-first": (_table(paths["paragraph"], {"mode": "after", "path": first}, rows=3), ["A", "T1", "T3", "T2"]),
        "before-second": (_table(paths["paragraph"], {"mode": "before", "path": second}, rows=3), ["A", "T1", "T3", "T2"]),
        "after-second": (_table(paths["paragraph"], {"mode": "after", "path": second}, rows=3), ["A", "T1", "T2", "T3"]),
        "text-before-first": (_text(paths["paragraph"], {"mode": "before", "path": first}), ["AX", "T1", "T2"]),
        "text-after-first": (_text(paths["paragraph"], {"mode": "after", "path": first}), ["A", "T1", "X", "T2"]),
        "text-after-second": (_text(paths["paragraph"], {"mode": "after", "path": second}), ["A", "T1", "T2", "X"]),
    }
    for name, (command, expected) in cases.items():
        output = tmp_path / f"{name}.hwpx"
        result = _call(source, output, command, V2)
        assert result["ok"], (name, result.get("error"))
        assert _layout(output)[-1] == expected, name


# --- over stdio ------------------------------------------------------------------------------


def test_versionless_prepend_is_refused_over_stdio(mcp_server_factory, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "in.hwpx"
    paths = _source(source)
    client = mcp_server_factory(cwd=workspace)
    revision = "sha256:" + sha256(source.read_bytes()).hexdigest()

    def call(command: dict[str, Any], output: str) -> dict[str, Any]:
        raw = client.call_tool_raw(
            "apply_document_commands",
            {"filename": "in.hwpx", "output": output, "commands": [{"commandId": "w", **command}],
             "expected_revision": revision, "overwrite": True},
        )
        if "error" in raw:
            return {"ok": False, "error": raw["error"]["data"]["error"]}
        return client.parse_tool_result_payload(raw["result"])

    refused = call(_table(paths["none"], {"mode": "prepend"}), "implicit.hwpx")
    assert refused["ok"] is False and refused["error"]["code"] == "contract_changed"
    assert not (workspace / "implicit.hwpx").exists()
    taken = call({**_table(paths["none"], {"mode": "prepend"}), "schemaVersion": V2}, "explicit.hwpx")
    assert taken["ok"] is True
    assert _layout(workspace / "explicit.hwpx")[-1] == ["T2", "EF"]


# --- the hints of the run forms v2 replaced ---------------------------------------------------


def test_run_remove_copy_and_anchor_hints_name_their_own_form(tmp_path: Path) -> None:
    source = tmp_path / "in.hwpx"
    paths = _source(source)
    with HwpxAgentDocument.open(source) as view:
        run = next(r.path for r in view.records if r.kind == "run" and r.parent_path == paths["one"] and r.summary.get("text") == "CD")
    hints = {}
    for name, command in {
        "remove": {"op": "remove", "path": run},
        "copy": {"op": "copy", "path": run, "parent": paths["none"]},
        "before": _table(paths["one"], {"mode": "before", "path": run}),
        "after": _table(paths["one"], {"mode": "after", "path": run}),
    }.items():
        result = _call(source, tmp_path / f"{name}.hwpx", command, V1)
        assert result["error"]["code"] == "contract_changed", name
        hints[name] = result["error"]["suggestion"]
    assert '"op": "remove"' in hints["remove"] and "text[s:e]" in hints["remove"]
    assert '"op": "copy"' in hints["copy"] and "text[s:e]" in hints["copy"]
    assert "s + length" in hints["after"] and "s + length" in hints["before"]
