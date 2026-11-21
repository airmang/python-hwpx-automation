# SPDX-License-Identifier: Apache-2.0
"""The chat guides' W blocks: a refused or failed run leaves the input byte for byte and no files.

Both hosts run the same blocks (the ChatGPT ``web-workflows.md`` and the Claude ``chat-engine.md``
generated from it), so the blocks are read from the canonical source. Each case builds a small
document, runs one block in this interpreter with ``AUTOMATION`` set, and checks what is on disk:

- a refusal (``SystemExit``) or a failed save: the input bytes are unchanged, the output does not
  exist and no intermediate ``*.checking*`` file is left;
- a success: the input bytes are unchanged and only the output was added.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import os
from pathlib import Path

import pytest

hwpx = pytest.importorskip("hwpx")
pytest.importorskip("hwpx_automation")
from hwpx import HwpxDocument  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "packaging" / "chatgpt" / "skill" / "references" / "web-workflows.md"


def _sim():
    spec = importlib.util.spec_from_file_location("chatgpt_sandbox_sim_for_failures", ROOT / "scripts" / "chatgpt_sandbox_sim.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SIM = _sim()
BLOCKS = SIM.workflow_blocks(GUIDE.read_text(encoding="utf-8"))


def _source(path: Path, *, field: str | None = None) -> bytes:
    """A paragraph "abc", a 1x2 table with label "K", and a click-here field where *field* says."""

    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("abc")
    table = doc.add_table(1, 2)
    table.cell(0, 0).text = "K"
    if field == "in-target":
        table.cell(0, 1).paragraphs[0].add_form_field("F", prompt="")
    elif field == "outside":
        paragraph.add_form_field("F", prompt="K")
    elif field is not None:
        paragraph.add_form_field("F", prompt="Z")
    doc.save(path)
    doc.close()
    return path.read_bytes()


def _inject(code: str, params: dict) -> str:
    """Put ``P.update(...)`` after the block's ``P = {...}``, keeping int keys (W4 numbers) as ints."""

    tree = ast.parse(code)
    end = next(
        node.end_lineno
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "P" for t in node.targets)
    )
    lines = code.splitlines()
    return "\n".join(lines[:end] + [f"P.update({params!r})"] + lines[end:]) + "\n"


def _run(block: str, params: dict, *, automation: bool = True) -> str:
    code = _inject(BLOCKS[block], params)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, f"<{block}>", "exec"), {"AUTOMATION": automation, "__name__": "__w__"})
    except SystemExit as exc:
        return f"refused: {exc}"
    return "ok"


def _leftovers(directory: Path, *keep: Path) -> list[str]:
    kept = {path.name for path in keep}
    return sorted(p.name for p in directory.iterdir() if ".checking" in p.name and p.name not in kept)


def _assert_untouched(directory: Path, src: Path, original: bytes, out: Path) -> None:
    assert src.read_bytes() == original
    assert not out.exists()
    assert _leftovers(directory, src) == []


REFUSALS = [
    ("W2", None, {"replacements": {"없는말": "x"}}, "찾지 못한 문구"),
    ("W2", None, {"replacements": {"a": "b", "b": "c"}}, "순서에 따라"),
    ("W2", None, {"replacements": {"": "x"}}, "빈 원문"),
    ("W3", None, {"values": {"없는라벨": "1"}}, "라벨을 찾지 못했다"),
    ("W3", "row", {"values": {"K": "1"}}, None),
    ("W4", "plain", {"values": {-1: "x"}}, "목록 번호는 0~0"),
    ("W4", "plain", {"values": {3: "x"}}, "목록 번호는 0~0"),
    ("W4", "plain", {"values": {"F": "first", 0: "second"}}, "같은 누름틀 [0]"),
    ("W4", "plain", {"values": {"없는이름": "x"}}, "없는 이름"),
    ("W4", None, {"values": {0: "x"}}, "목록 번호는 0~-1"),
]


@pytest.mark.parametrize(("block", "field", "params", "reason"), REFUSALS)
def test_a_refused_block_leaves_the_input_and_writes_nothing(tmp_path, block, field, params, reason) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    if field == "row":
        original = _source(src)
        doc = HwpxDocument.open(src)
        # A click-here field in the row of the value cell (not the value cell itself).
        table = doc.tables.all[0]
        table.cell(0, 0).paragraphs[0].add_form_field("G", prompt="")
        doc.save(src)
        doc.close()
        original = src.read_bytes()
        reason = "이 줄에는 누름틀이 있다"
    else:
        original = _source(src, field=field)
    result = _run(block, {**params, "src": str(src), "out": str(out)})
    assert result.startswith("refused") and reason in result, result
    _assert_untouched(tmp_path, src, original, out)


@pytest.mark.parametrize("block", ["W2", "W3", "W4"])
def test_the_same_file_under_another_spelling_is_refused(tmp_path, monkeypatch, block) -> None:
    src = tmp_path / "input.hwpx"
    original = _source(src, field="plain")
    monkeypatch.chdir(tmp_path)
    params = {"replacements": {"abc": "xyz"}, "values": {"K": "1"} if block == "W3" else {0: "1"}}
    result = _run(block, {**params, "src": str(src), "out": os.path.join(".", "sub", "..", "input.hwpx")})
    assert result.startswith("refused") and "같은 파일" in result, result
    assert src.read_bytes() == original
    assert _leftovers(tmp_path, src) == []


@pytest.mark.parametrize("block", ["W2", "W3", "W4"])
def test_an_input_named_like_the_intermediate_file_is_kept(tmp_path, block) -> None:
    out = tmp_path / "out.hwpx"
    src = tmp_path / "out.checking.hwpx"
    original = _source(src, field="plain" if block == "W4" else None)
    params = {"replacements": {"abc": "xyz"}, "values": {"K": "1"} if block == "W3" else {0: "1"}}
    assert _run(block, {**params, "src": str(src), "out": str(out)}) == "ok"
    assert src.read_bytes() == original
    assert out.exists()
    assert _leftovers(tmp_path, src) == []


@pytest.mark.parametrize("block", ["W2", "W3", "W4", "W5"])
def test_a_failed_save_leaves_the_input_and_no_intermediate_file(tmp_path, monkeypatch, block) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    original = _source(src, field="plain" if block == "W4" else None)
    real_save = HwpxDocument.save

    def failing_save(self, target, *args, **kwargs):
        real_save(self, target, *args, **kwargs)  # the intermediate file is written ...
        raise OSError("disk full")  # ... and then the save fails

    monkeypatch.setattr(HwpxDocument, "save", failing_save)
    params = {"replacements": {"abc": "xyz"}, "values": {"K": "1"} if block == "W3" else {0: "1"}}
    if block != "W5":
        params["src"] = str(src)
    with pytest.raises(OSError, match="disk full"):
        _run(block, {**params, "out": str(out)})
    _assert_untouched(tmp_path, src, original, out)


def test_w2_deleting_text_is_checked_and_saved(tmp_path) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    original = _source(src)
    assert _run("W2", {"src": str(src), "out": str(out), "replacements": {"abc": ""}}) == "ok"
    assert src.read_bytes() == original
    with HwpxDocument.open(out) as saved:
        assert "abc" not in saved.text.plain()
    assert _leftovers(tmp_path) == []


def test_w3_fills_the_click_here_field_that_is_the_value_cell(tmp_path) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    original = _source(src, field="in-target")
    assert _run("W3", {"src": str(src), "out": str(out), "values": {"K": "123"}}) == "ok"
    assert src.read_bytes() == original
    with HwpxDocument.open(out) as saved:
        assert saved.tables.all[0].cell(0, 1).text == "123"
        assert [f.value for f in saved.fields.all] == ["123"]


def test_w3_is_not_stopped_by_a_field_outside_the_table(tmp_path) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    _source(src, field="outside")  # its prompt equals the label
    with HwpxDocument.open(src) as before:
        field_values = [f.value for f in before.fields.all]
    assert _run("W3", {"src": str(src), "out": str(out), "values": {"K": "123"}}) == "ok"
    with HwpxDocument.open(out) as saved:
        assert saved.tables.all[0].cell(0, 1).text == "123"
        assert [f.value for f in saved.fields.all] == field_values


def test_w4_fills_one_of_two_fields_with_the_same_name_by_number(tmp_path) -> None:
    src, out = tmp_path / "input.hwpx", tmp_path / "out.hwpx"
    doc = HwpxDocument.new()
    doc.add_paragraph("a").add_form_field("F", prompt="")
    doc.add_paragraph("b").add_form_field("F", prompt="")
    doc.save(src)
    doc.close()
    assert _run("W4", {"src": str(src), "out": str(out), "values": {1: "second"}}) == "ok"
    with HwpxDocument.open(out) as saved:
        assert [f.value for f in saved.fields.all] == ["", "second"]
    refused = _run("W4", {"src": str(src), "out": str(tmp_path / "o2.hwpx"), "values": {"F": "x"}})
    assert "여러 개인 이름" in refused


def _hwp_source(path: Path) -> bytes:
    """The same small document written as HWP 5.0 (``.hwp``) — an input the blocks only read."""

    import warnings

    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("abc")
    table = doc.add_table(1, 2)
    table.cell(0, 0).text = "K"
    paragraph.add_form_field("F", prompt="Z")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the experimental HWP 5.0 writer warns
        doc.save(path)
    doc.close()
    return path.read_bytes()


@pytest.mark.parametrize("block", ["W1", "W2", "W3", "W4"])
def test_an_hwp_input_is_read_only_and_the_result_is_hwpx(tmp_path, block) -> None:
    src = tmp_path / "input.hwp"
    original = _hwp_source(src)
    asked = tmp_path / "out.hwp"  # asked for .hwp; the block writes .hwpx next to it
    params = {"src": str(src), "out": str(asked), "replacements": {"abc": "xyz"},
              "values": {"K": "1"} if block == "W3" else {0: "1"}}
    assert _run(block, params) == "ok"
    assert src.read_bytes() == original
    assert not asked.exists()
    written = tmp_path / "out.hwpx"
    assert written.exists() == (block != "W1")
    if block != "W1":
        with HwpxDocument.open(written) as saved:
            assert saved.package.part_names()  # opens as HWPX
    assert _leftovers(tmp_path) == []
