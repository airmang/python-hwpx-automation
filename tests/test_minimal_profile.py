# SPDX-License-Identifier: Apache-2.0
"""The ``minimal`` MCP profile and the compact operations behind it (#198, #199)."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from hwpx import HwpxDocument
from hwpx_automation.office import compact
from hwpx_automation.office.compact import DraftStore

pytest.importorskip("mcp")
if not hasattr(HwpxDocument.new().text, "outline"):  # pragma: no cover - older core
    pytest.skip("python-hwpx without doc.text.outline/apply_changes", allow_module_level=True)

_needs_markdown_import = pytest.mark.skipif(
    __import__("importlib").util.find_spec("hwpx.tools.markdown_import") is None,
    reason="python-hwpx without hwpx.tools.markdown_import",
)


def _core_writes_bylines() -> bool:
    try:
        from hwpx.tools.markdown_import import from_markdown
    except ImportError:
        return False
    return "byline" in inspect.signature(from_markdown).parameters


_needs_byline = pytest.mark.skipif(
    not _core_writes_bylines(), reason="python-hwpx whose from_markdown has no byline"
)


def _form(path: Path) -> Path:
    doc = HwpxDocument.new()
    doc.add_paragraph("수행평가 학습지")
    table = doc.add_table(2, 2)
    table.set_cell_text(0, 0, "문항")
    table.set_cell_text(0, 1, "1. 다음 글을 읽고 답하시오.")
    table.set_cell_text(1, 0, "답")
    table.set_cell_text(1, 1, "")
    doc.save_to_path(path)
    return path


def _id_of(outline: str, text: str) -> str:
    line = next(line for line in outline.splitlines() if line.endswith(text))
    return line[1 : line.index("]")]


# --------------------------------------------------------------------------- compact operations


def test_read_outline_is_a_short_id_tagged_list(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    result = compact.read_outline(str(source))
    assert result["ok"] is True and result["complete"] is True
    assert result["outline"].splitlines()[0].endswith("수행평가 학습지")
    assert result["listed"] == result["total"] == 4
    assert compact.read_outline(str(source), after="s9p9")["error"]["code"] == "OUTLINE_CURSOR_UNKNOWN"
    assert compact.read_outline(str(tmp_path / "none.hwpx"))["error"]["code"] == "FILE_NOT_FOUND"


def test_apply_text_changes_writes_a_sibling_file_and_keeps_the_original(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    outline = compact.read_outline(str(source))["outline"]
    question = _id_of(outline, "1. 다음 글을 읽고 답하시오.")

    result = compact.apply_text_changes(str(source), {question: "1. 바뀐 문항", "s9p9": "x"})

    assert result["changed"] == 1 and result["unknownIds"] == ["s9p9"]
    assert result["ok"] is False  # an unknown id is reported, the rest applied
    assert result["openSafe"] is True
    output = Path(result["output"])
    assert output.name == "form.edited.hwpx"
    assert "1. 바뀐 문항" in compact.read_outline(str(output))["outline"]
    assert "1. 다음 글을 읽고 답하시오." in compact.read_outline(str(source))["outline"]


def test_apply_text_changes_reports_a_cell_that_would_grow(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    question = _id_of(compact.read_outline(str(source))["outline"], "1. 다음 글을 읽고 답하시오.")
    result = compact.apply_text_changes(str(source), {question: "아주 긴 문항 내용입니다 " * 40}, output=str(tmp_path / "out.hwpx"))
    (entry,) = result["overflow"]
    assert entry["id"] == question and entry["lines"] > entry["lineBudget"]


def test_nothing_is_written_when_nothing_changes(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    result = compact.apply_text_changes(str(source), {"s9p9": "x"})
    assert result["output"] is None and result["changed"] == 0
    assert not (tmp_path / "form.edited.hwpx").exists()
    assert compact.apply_text_changes(str(source), ["not", "a", "mapping"])["error"]["code"] == "CHANGES_INVALID"  # type: ignore[arg-type]


def test_replace_text(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    result = compact.replace_text(str(source), "학습지", "활동지", output=str(tmp_path / "r.hwpx"))
    assert result == {"ok": True, "replaced": 1, "output": str((tmp_path / "r.hwpx").resolve()), "openSafe": True}
    assert compact.replace_text(str(source), "", "x")["error"]["code"] == "TEXT_EMPTY"


def test_validate_document(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")
    assert compact.validate_document(str(source)) == {"ok": True, "reopens": True, "issues": [], "moreIssues": 0, "warnings": 0}
    broken = tmp_path / "broken.hwpx"
    broken.write_bytes(b"not a zip")
    result = compact.validate_document(str(broken))
    assert result["ok"] is False and result["issues"]


# --------------------------------------------------------------------------- drafts (#199)


def test_drafts_append_chunks_and_expire() -> None:
    now = [0.0]
    store = DraftStore(max_chars=20, max_drafts=2, ttl_seconds=10, clock=lambda: now[0])
    first = store.stage("# 제목\n")
    draft = first["draftId"]
    assert store.stage("본문", draft) == {"ok": True, "draftId": draft, "chars": 7, "chunks": 2}
    assert store.text(draft) == "# 제목\n본문"
    assert store.stage("x" * 20, draft)["error"]["code"] == "DRAFT_TOO_LONG"
    assert store.stage("x", "dmissing")["error"]["code"] == "DRAFT_UNKNOWN"
    now[0] = 11
    assert store.text(draft) is None


def test_the_oldest_draft_makes_room() -> None:
    now = [0.0]
    store = DraftStore(max_drafts=2, clock=lambda: now[0])
    ids = []
    for index in range(3):
        now[0] = index
        ids.append(store.stage(str(index))["draftId"])
    assert store.text(ids[0]) is None and store.text(ids[2]) == "2"


@_needs_markdown_import
def test_create_from_markdown_by_draft_id(tmp_path: Path) -> None:
    draft = compact.stage_text("# 체험학습 보고서\n\n")["draftId"]
    compact.stage_text("- 일시: 11월 6일\n- 장소: 과학관\n\n| 항목 | 내용 |\n|---|---|\n| 준비물 | 필기구 |\n", draft)

    result = compact.create_from_markdown(str(tmp_path / "report.hwpx"), draft_id=draft)

    assert result["ok"] is True and result["openSafe"] is True
    outline = compact.read_outline(result["output"])["outline"]
    assert "체험학습 보고서" in outline and "준비물" in outline
    assert compact.stage_text("x", draft)["error"]["code"] == "DRAFT_UNKNOWN"  # used up


@_needs_markdown_import
def test_create_from_markdown_from_a_workspace_file(tmp_path: Path) -> None:
    source = tmp_path / "plan.md"
    source.write_text("# 계획\n\n본문", encoding="utf-8")
    result = compact.create_from_markdown(str(tmp_path / "plan.hwpx"), markdown_path=str(source))
    assert result["ok"] is True


def test_create_from_markdown_needs_exactly_one_source(tmp_path: Path) -> None:
    out = str(tmp_path / "x.hwpx")
    assert compact.create_from_markdown(out)["error"]["code"] == "MARKDOWN_SOURCE"
    assert compact.create_from_markdown(out, markdown="a", draft_id="d1")["error"]["code"] == "MARKDOWN_SOURCE"
    assert compact.create_from_markdown(out, draft_id="dmissing")["error"]["code"] == "DRAFT_UNKNOWN"


def _core_without_byline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stand in a python-hwpx whose ``from_markdown`` has no ``byline``; return the texts it is given."""

    from hwpx.tools import markdown_import

    real = markdown_import.from_markdown
    texts: list[str] = []

    def from_markdown(markdown: str, *, style: None = None) -> HwpxDocument:  # python-hwpx 6.12.0's parameters
        assert style is None
        texts.append(markdown)
        return real(markdown)

    monkeypatch.setattr(markdown_import, "from_markdown", from_markdown)
    return texts


@_needs_markdown_import
def test_create_from_markdown_without_a_byline_calls_the_core_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    texts = _core_without_byline(monkeypatch)
    text = "# 계획\n\n본문"

    results = [compact.create_from_markdown(str(tmp_path / "plain.hwpx"), markdown=text)]
    for index, blank in enumerate((None, "", "  \n ")):
        results.append(compact.create_from_markdown(str(tmp_path / f"blank{index}.hwpx"), markdown=text, byline=blank))

    assert texts == [text] * 4
    for result in results:
        assert result == {"ok": True, "output": result["output"], "chars": len(text), "openSafe": True}
        assert "계획" in compact.read_outline(result["output"])["outline"]


@_needs_markdown_import
def test_a_byline_is_refused_when_the_core_cannot_write_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _core_without_byline(monkeypatch)
    draft = compact.stage_text("# 계획\n\n본문")["draftId"]
    target = tmp_path / "plan.hwpx"

    result = compact.create_from_markdown(str(target), draft_id=draft, byline="교무기획부")

    assert result["ok"] is False and result["error"]["code"] == "DEPENDENCY_MISSING"
    assert "byline" in result["error"]["message"] and "upgrade python-hwpx" in result["error"]["message"]
    assert texts == [] and not target.exists()
    assert compact.DRAFTS.text(draft) == "# 계획\n\n본문"  # kept for another try


@_needs_markdown_import
@_needs_byline
def test_create_from_markdown_writes_the_byline(tmp_path: Path) -> None:
    result = compact.create_from_markdown(
        str(tmp_path / "report.hwpx"), markdown="# 체험학습 보고서\n\n본문입니다.", byline="교무기획부 (2026. 11. 13.)"
    )

    assert result["ok"] is True and result["openSafe"] is True
    assert set(result) == {"ok", "output", "chars", "openSafe"}
    outline = compact.read_outline(result["output"])["outline"]
    assert "체험학습 보고서" in outline and "교무기획부 (2026. 11. 13.)" in outline


# --------------------------------------------------------------------------- the MCP profile (#198)


def _session_run(probe):
    from mcp.shared.memory import create_connected_server_and_client_session

    from hwpx_automation import __version__
    from hwpx_automation.minimal_profile import build_minimal_server

    async def run():
        async with create_connected_server_and_client_session(build_minimal_server(__version__)) as client:
            await client.initialize()
            return await probe(client)

    return asyncio.run(run())


def test_the_profile_lists_exactly_its_frozen_tools_in_a_small_budget() -> None:
    from hwpx_automation.minimal_profile import MINIMAL_INSTRUCTIONS, MINIMAL_TOOL_NAMES

    async def probe(client):
        return (await client.list_tools()).tools

    tools = _session_run(probe)
    assert tuple(tool.name for tool in tools) == MINIMAL_TOOL_NAMES
    # What a small model must read before its first call: names, descriptions and
    # input schemas of all six tools, plus the server instructions.
    listing = json.dumps(
        [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert len(listing) + len(MINIMAL_INSTRUCTIONS) < 5000, len(listing)
    assert all(len(tool.description or "") <= 200 for tool in tools)


def test_tool_results_are_compact_json_without_the_document_body(tmp_path: Path) -> None:
    source = _form(tmp_path / "form.hwpx")

    async def probe(client):
        outline = await client.call_tool("read_outline", {"path": str(source)})
        staged = await client.call_tool("stage_text", {"text": "# 제목\n"})
        missing = await client.call_tool("read_outline", {"path": str(tmp_path / "none.hwpx")})
        return outline, staged, missing

    outline, staged, missing = _session_run(probe)
    text = outline.content[0].text
    assert "\n  " not in text and json.loads(text)["ok"] is True
    assert json.loads(staged.content[0].text)["draftId"].startswith("d")
    assert missing.isError is True
    assert json.loads(missing.content[0].text)["error"]["code"] == "FILE_NOT_FOUND"


@_needs_markdown_import
def test_the_profile_tool_passes_a_short_byline_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _core_without_byline(monkeypatch)
    target = tmp_path / "plan.hwpx"
    arguments = {"output": str(target), "markdown": "# 계획\n\n본문"}

    async def probe(client):
        tools = (await client.list_tools()).tools
        refused = await client.call_tool("create_from_markdown", {**arguments, "byline": "교무기획부"})
        too_long = await client.call_tool("create_from_markdown", {**arguments, "byline": "가" * 201})
        return tools, refused, too_long

    tools, refused, too_long = _session_run(probe)
    schema = next(tool for tool in tools if tool.name == "create_from_markdown").inputSchema
    assert {"maxLength": 200, "type": "string"} in schema["properties"]["byline"]["anyOf"]
    assert schema["required"] == ["output"]
    # The stand-in core has no byline, so this answer shows the byline reached the operation.
    assert refused.isError is True
    assert json.loads(refused.content[0].text)["error"]["code"] == "DEPENDENCY_MISSING"
    assert too_long.isError is True
    assert texts == [] and not target.exists()


def test_the_server_cli_accepts_the_profile() -> None:
    from hwpx_automation import server

    seen: dict[str, object] = {}

    class Stop(Exception):
        pass

    def fake_run(self, transport):  # noqa: ANN001
        seen["server"] = self.name
        raise Stop

    from mcp.server.fastmcp import FastMCP

    original = FastMCP.run
    FastMCP.run = fake_run  # type: ignore[method-assign]
    try:
        with pytest.raises(Stop):
            server.main(["--profile", "minimal"])
    finally:
        FastMCP.run = original  # type: ignore[method-assign]
    assert seen["server"] == "python-hwpx-automation-minimal"
    with pytest.raises(SystemExit):
        server.main(["--profile", "tiny"])


def test_an_older_core_gets_a_dependency_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hwpx._document.ns.text import TextNamespace

    source = _form(tmp_path / "form.hwpx")
    monkeypatch.delattr(TextNamespace, "outline")
    assert compact.read_outline(str(source))["error"]["code"] == "DEPENDENCY_MISSING"
    assert compact.apply_text_changes(str(source), {"s0p1": "x"})["error"]["code"] == "DEPENDENCY_MISSING"
