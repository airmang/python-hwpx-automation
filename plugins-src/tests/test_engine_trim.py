"""The Claude engine leaves the MCP server layer out and refuses a broken cut.

Core 7.0 + automation 8.0 would put 517 files in the Claude bundle (limit 512).
The chat path never runs the MCP server, so vendor_claude_engine.py leaves that
layer out. These tests pin the guard: a kept module that imports a left-out one
fails the build instead of failing later inside a chat sandbox.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("vendor_claude_engine", ROOT / "scripts" / "vendor_claude_engine.py")
assert _spec and _spec.loader
vendor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vendor)


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_server_layer_and_entry_points_are_left_out() -> None:
    for member in (
        "hwpx_automation/handlers/read_export.py",
        "hwpx_automation/ops_services/tables.py",
        "hwpx_automation/server.py",
        "hwpx_automation/integrations/langchain.py",
        "hwpx/tools/text_extract_cli.py",
    ):
        assert vendor.is_excluded(member), member
    for member in ("hwpx/__init__.py", "hwpx_automation/api.py", "hwpx_automation/tool_contract.py"):
        assert not vendor.is_excluded(member), member


def test_guard_refuses_a_kept_module_that_imports_a_left_out_one(tmp_path: Path) -> None:
    _write(tmp_path, "hwpx/__init__.py")
    _write(tmp_path, "hwpx_automation/__init__.py")
    _write(tmp_path, "hwpx_automation/api.py", "def f():\n    from .server import main\n")
    problems = vendor.excluded_imports(tmp_path)
    assert problems == ["hwpx_automation.api imports hwpx_automation.server, which the engine leaves out"]


def test_guard_sees_imports_outside_the_chat_entry_points(tmp_path: Path) -> None:
    _write(tmp_path, "hwpx/__init__.py")
    _write(tmp_path, "hwpx_automation/__init__.py")
    _write(tmp_path, "hwpx_automation/visual_qa.py", "import hwpx_automation.handlers.workflow\n")
    assert vendor.excluded_imports(tmp_path) == [
        "hwpx_automation.visual_qa imports hwpx_automation.handlers, which the engine leaves out",
        "hwpx_automation.visual_qa imports hwpx_automation.handlers.workflow, which the engine leaves out",
    ]


def test_clean_cut_passes(tmp_path: Path) -> None:
    _write(tmp_path, "hwpx/__init__.py", "from . import oxml\n")
    _write(tmp_path, "hwpx/oxml/__init__.py")
    _write(tmp_path, "hwpx_automation/__init__.py", "import hwpx\n")
    _write(tmp_path, "hwpx_automation/api.py", "from . import tool_contract\n")
    _write(tmp_path, "hwpx_automation/tool_contract.py")
    assert vendor.excluded_imports(tmp_path) == []
