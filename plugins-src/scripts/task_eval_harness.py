#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay HWPX natural-language task specs and score automatic oracles."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "examples" / "eval_tasks" / "tasks.json"
DEFAULT_PROFILES = [
    ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.1.6.json",
    ROOT / "examples" / "eval_tasks" / "profiles" / "baseline-0.1.5.json",
]
DEFAULT_OUTPUT = ROOT / "examples" / "out" / "task_eval_report.json"

FAIL_TOOL_ABSENT = "tool_absent"
FAIL_TOOL_MISBEHAVIOR = "tool_misbehavior"
FAIL_SKILL_GUIDANCE_GAP = "skill_guidance_gap"

logging.basicConfig(level=logging.ERROR)


@dataclass
class Profile:
    profile_id: str
    label: str
    plugin_version: str
    available_tools: set[str] | None
    broken_tools: set[str]
    guidance_tags: set[str]

    @classmethod
    def from_path(cls, path: Path) -> "Profile":
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = data.get("availableTools", ["*"])
        available = None if "*" in tools else set(tools)
        return cls(
            profile_id=data["id"],
            label=data.get("label", data["id"]),
            plugin_version=data.get("pluginVersion", "unknown"),
            available_tools=available,
            broken_tools=set(data.get("brokenTools", [])),
            guidance_tags=set(data.get("guidanceTags", [])),
        )

    def has_tool(self, name: str) -> bool:
        return self.available_tools is None or name in self.available_tools


def _ensure_stack_imports() -> None:
    candidates = []
    env_repo = os.environ.get("HWPX_MCP_SERVER_REPO")
    if env_repo:
        candidates.append(Path(env_repo) / "src")
    candidates.append(ROOT.parent / "hwpx-mcp-server" / "src")
    env_hwpx = os.environ.get("PYTHON_HWPX_REPO")
    if env_hwpx:
        candidates.append(Path(env_hwpx) / "src")
    candidates.append(ROOT.parent / "python-hwpx" / "src")
    for candidate in candidates:
        if candidate.exists():
            sys.path.insert(0, str(candidate))


class _FallbackServer:
    """Small local adapter used when FastMCP dependencies are not installed."""

    def __init__(self) -> None:
        from hwpx_mcp_server.core.content import (
            add_heading_to_doc,
            add_memo_to_doc,
            add_page_break_to_doc,
            add_paragraph_to_doc,
            add_table_to_doc,
            delete_paragraph_from_doc,
            fill_by_path_in_doc,
            find_cell_by_label_in_doc,
            format_table_in_doc,
            get_table_data,
            get_table_map_in_doc,
            insert_paragraph_to_doc,
            merge_cells_in_table,
            set_cell_text,
            split_cell_in_table,
        )
        from hwpx_mcp_server.core.document import create_blank, open_doc, save_doc
        from hwpx_mcp_server.core.formatting import create_style_in_doc, format_text_range
        from hwpx_mcp_server.core.search import batch_replace_in_doc, find_in_doc, replace_in_doc

        self._add_heading_to_doc = add_heading_to_doc
        self._add_memo_to_doc = add_memo_to_doc
        self._add_page_break_to_doc = add_page_break_to_doc
        self._add_paragraph_to_doc = add_paragraph_to_doc
        self._add_table_to_doc = add_table_to_doc
        self._batch_replace_in_doc = batch_replace_in_doc
        self._create_blank = create_blank
        self._create_style_in_doc = create_style_in_doc
        self._delete_paragraph_from_doc = delete_paragraph_from_doc
        self._fill_by_path_in_doc = fill_by_path_in_doc
        self._find_cell_by_label_in_doc = find_cell_by_label_in_doc
        self._find_in_doc = find_in_doc
        self._format_table_in_doc = format_table_in_doc
        self._format_text_range = format_text_range
        self._get_table_data = get_table_data
        self._get_table_map_in_doc = get_table_map_in_doc
        self._insert_paragraph_to_doc = insert_paragraph_to_doc
        self._merge_cells_in_table = merge_cells_in_table
        self._open_doc = open_doc
        self._replace_in_doc = replace_in_doc
        self._save_doc = save_doc
        self._set_cell_text = set_cell_text
        self._split_cell_in_table = split_cell_in_table

    def _mutate(self, filename: str, callback: Any) -> Any:
        doc = self._open_doc(filename)
        result = callback(doc)
        self._save_doc(doc, filename)
        return result

    def create_document(self, filename: str, title: str | None = None, author: str | None = None) -> dict[str, Any]:
        del title, author
        verification = self._create_blank(filename)
        return {"filename": filename, "created": True, "openSafety": verification.get("openSafety")}

    def add_paragraph(self, filename: str, text: str, style: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        index = self._mutate(filename, lambda doc: self._add_paragraph_to_doc(doc, text, style))
        return {"paragraph_index": index}

    def add_heading(self, filename: str, text: str, level: int = 1, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        index = self._mutate(filename, lambda doc: self._add_heading_to_doc(doc, text, level))
        return {"paragraph_index": index}

    def add_table(self, filename: str, rows: int, cols: int, data: list[list[str]] | None = None, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        index = self._mutate(filename, lambda doc: self._add_table_to_doc(doc, rows, cols, data))
        return {"table_index": index}

    def add_page_break(self, filename: str, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        self._mutate(filename, self._add_page_break_to_doc)
        return {"success": True}

    def search_and_replace(self, filename: str, find_text: str, replace_text: str, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        count = self._mutate(filename, lambda doc: self._replace_in_doc(doc, find_text, replace_text))
        return {"replaced_count": count}

    def batch_replace(self, filename: str, replacements: list[dict[str, str]], dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        return self._mutate(filename, lambda doc: self._batch_replace_in_doc(doc, replacements))

    def insert_paragraph(self, filename: str, paragraph_index: int, text: str, style: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        index = self._mutate(filename, lambda doc: self._insert_paragraph_to_doc(doc, paragraph_index, text, style))
        return {"inserted_index": index}

    def delete_paragraph(self, filename: str, paragraph_index: int, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        remaining = self._mutate(filename, lambda doc: self._delete_paragraph_from_doc(doc, paragraph_index))
        return {"remaining_paragraphs": remaining}

    def replace_in_paragraph(
        self,
        filename: str,
        old_text: str,
        new_text: str,
        paragraph_index: int | None = None,
        count: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        if paragraph_index is None:
            paragraph_index = 0

        def replace(doc: Any) -> int:
            paragraph = doc.paragraphs[paragraph_index]
            original = paragraph.text or ""
            limit = -1 if count is None else count
            paragraph.text = original.replace(old_text, new_text, limit)
            return 0 if paragraph.text == original else 1

        replaced = self._mutate(filename, replace)
        return {"replaced_count": replaced}

    def set_table_cell_text(
        self,
        filename: str,
        table_index: int,
        row: int,
        col: int,
        text: str,
        preserve_format: bool = True,
        split_paragraphs: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        self._mutate(
            filename,
            lambda doc: self._set_cell_text(
                doc,
                table_index,
                row,
                col,
                text,
                preserve_format=preserve_format,
                split_paragraphs=split_paragraphs,
            ),
        )
        return {"ok": True}

    def fill_by_path(self, filename: str, mappings: dict[str, str], dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        return self._mutate(filename, lambda doc: self._fill_by_path_in_doc(doc, mappings))

    def format_text(
        self,
        filename: str,
        paragraph_index: int,
        start_pos: int,
        end_pos: int,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        font_size: float | None = None,
        font_name: str | None = None,
        color: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        self._mutate(
            filename,
            lambda doc: self._format_text_range(
                doc,
                paragraph_index,
                start_pos,
                end_pos,
                bold=bold,
                italic=italic,
                underline=underline,
                font_size=font_size,
                font_name=font_name,
                color=color,
            ),
        )
        return {"formatted": True}

    def create_custom_style(
        self,
        filename: str,
        style_name: str,
        bold: bool | None = None,
        italic: bool | None = None,
        font_size: float | None = None,
        font_name: str | None = None,
        color: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        return self._mutate(
            filename,
            lambda doc: self._create_style_in_doc(
                doc,
                style_name,
                bold=bold,
                italic=italic,
                font_size=font_size,
                font_name=font_name,
                color=color,
            ),
        )

    def format_table(self, filename: str, table_index: int, has_header_row: bool | None = None, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        self._mutate(filename, lambda doc: self._format_table_in_doc(doc, table_index, has_header_row=has_header_row))
        return {"formatted": True}

    def merge_table_cells(
        self,
        filename: str,
        table_index: int,
        start_row: int,
        start_col: int,
        end_row: int,
        end_col: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        self._mutate(filename, lambda doc: self._merge_cells_in_table(doc, table_index, start_row, start_col, end_row, end_col))
        return {"merged": True}

    def split_table_cell(self, filename: str, table_index: int, row: int, col: int, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        span = self._mutate(filename, lambda doc: self._split_cell_in_table(doc, table_index, row, col))
        return {"split": True, "original_span": span}

    def add_memo(self, filename: str, paragraph_index: int | None = None, text: str = "", dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        return self._mutate(filename, lambda doc: self._add_memo_to_doc(doc, paragraph_index, text))

    def find_text(self, filename: str, text_to_find: str, match_case: bool = True, max_results: int = 50) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._find_in_doc(doc, text_to_find=text_to_find, match_case=match_case, max_results=max_results)

    def find_cell_by_label(self, filename: str, label_text: str, direction: str = "right") -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._find_cell_by_label_in_doc(doc, label_text, direction=direction)

    def apply_edits(self, filename: str, operations: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        for operation in operations:
            op_type = operation["type"]
            if op_type == "add_paragraph":
                self.add_paragraph(filename, operation.get("text", ""))
            elif op_type == "replace_text":
                self.search_and_replace(filename, operation["findText"], operation.get("replaceText", ""))
            elif op_type == "add_table":
                self.add_table(filename, int(operation["rows"]), int(operation["cols"]), operation.get("data"))
            elif op_type == "set_table_cell_text":
                self.set_table_cell_text(
                    filename,
                    int(operation.get("tableIndex", 0)),
                    int(operation["row"]),
                    int(operation["col"]),
                    str(operation.get("text", "")),
                )
            else:
                raise ValueError(f"fallback apply_edits does not support {op_type}")
        return {"ok": True, "operationsApplied": len(operations)}

    def render_preview(
        self,
        filename: str,
        output_dir: str | None = None,
        mode: str = "pages",
        screenshot: str = "off",
        max_pages: int | None = None,
    ) -> dict[str, Any]:
        del mode, screenshot, max_pages
        out = Path(output_dir or Path(filename).with_suffix(".preview"))
        out.mkdir(parents=True, exist_ok=True)
        html_path = out / "preview.html"
        manifest_path = out / "manifest.json"
        html_path.write_text("<!doctype html><meta charset='utf-8'><p>fallback preview</p>\n", encoding="utf-8")
        manifest_path.write_text(json.dumps({"status": "html_only", "sourcePath": filename}) + "\n", encoding="utf-8")
        return {"status": "html_only", "htmlPath": str(html_path), "manifestPath": str(manifest_path)}

    def get_document_text(self, filename: str) -> dict[str, Any]:
        doc = self._open_doc(filename)
        try:
            text = doc.export_text()
        except Exception:
            text = "\n".join(paragraph.text or "" for paragraph in doc.paragraphs)
        return {"text": text}

    def get_paragraphs_text(self, filename: str, start_index: int = 0, end_index: int | None = None, max_chars: int | None = None) -> dict[str, Any]:
        del max_chars
        doc = self._open_doc(filename)
        paragraphs = doc.paragraphs[start_index:end_index]
        return {"paragraphs": [{"index": start_index + index, "text": paragraph.text or ""} for index, paragraph in enumerate(paragraphs)]}

    def get_table_map(self, filename: str) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._get_table_map_in_doc(doc)

    def get_table_text(self, filename: str, table_index: int = 0) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._get_table_data(doc, table_index)


def _load_server_module() -> Any:
    _ensure_stack_imports()
    try:
        import hwpx_mcp_server.server as server
    except Exception as exc:  # pragma: no cover - environment diagnostic
        try:
            return _FallbackServer()
        except Exception as fallback_exc:  # pragma: no cover - environment diagnostic
            raise RuntimeError(
                "hwpx_mcp_server is unavailable. Set HWPX_MCP_SERVER_REPO to a local "
                "checkout or install hwpx-mcp-server in this interpreter. "
                f"FastMCP import error: {exc}; fallback error: {fallback_exc}"
            ) from fallback_exc
    return server


def _render_value(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for name, replacement in variables.items():
            rendered = rendered.replace("{" + name + "}", replacement)
        return rendered
    if isinstance(value, list):
        return [_render_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, variables) for key, item in value.items()}
    return value


def _available_server_tools(server: Any) -> dict[str, Any]:
    names = [
        "add_heading",
        "add_memo",
        "add_page_break",
        "add_paragraph",
        "add_table",
        "apply_edits",
        "batch_replace",
        "create_custom_style",
        "create_document",
        "delete_paragraph",
        "fill_by_path",
        "find_cell_by_label",
        "find_text",
        "format_table",
        "format_text",
        "get_document_text",
        "get_paragraphs_text",
        "get_table_map",
        "get_table_text",
        "insert_paragraph",
        "merge_table_cells",
        "render_preview",
        "replace_in_paragraph",
        "search_and_replace",
        "set_table_cell_text",
        "split_table_cell",
    ]
    return {name: getattr(server, name) for name in names if hasattr(server, name)}


def _seed_document(server: Any, task: dict[str, Any], document: Path) -> None:
    seed = task.get("startDocument", {"kind": "blank"})
    kind = seed.get("kind", "blank")
    server.create_document(str(document))
    for paragraph in seed.get("paragraphs", []):
        server.add_paragraph(str(document), paragraph)
    for table in seed.get("tables", []):
        rows = int(table.get("rows", len(table.get("data", [])) or 1))
        cols = int(table.get("cols", max((len(row) for row in table.get("data", [])), default=1)))
        server.add_table(str(document), rows, cols, table.get("data"))
    if kind == "form":
        if not seed.get("tables"):
            server.add_table(
                str(document),
                4,
                2,
                [["Name", ""], ["Department", ""], ["Date", ""], ["Total", ""]],
            )
    elif kind not in {"blank", "text", "table", "form"}:
        raise ValueError(f"unknown startDocument kind: {kind}")


def _tool_required_by_task(task: dict[str, Any]) -> set[str]:
    required = set(task.get("requiredTools", []))
    for call in task.get("toolCalls", []):
        required.add(call["tool"])
    return required


def _preflight(task: dict[str, Any], profile: Profile) -> dict[str, Any] | None:
    missing_guidance = sorted(set(task.get("requiredGuidance", [])) - profile.guidance_tags)
    if missing_guidance:
        return {
            "classification": FAIL_SKILL_GUIDANCE_GAP,
            "reason": "profile is missing required skill guidance tags",
            "missingGuidance": missing_guidance,
        }

    required_tools = _tool_required_by_task(task)
    missing_tools = sorted(tool for tool in required_tools if not profile.has_tool(tool))
    if missing_tools:
        return {
            "classification": FAIL_TOOL_ABSENT,
            "reason": "profile does not expose required tools",
            "missingTools": missing_tools,
        }

    broken_tools = sorted(required_tools & profile.broken_tools)
    if broken_tools:
        return {
            "classification": FAIL_TOOL_MISBEHAVIOR,
            "reason": "profile marks required tools as known-broken",
            "brokenTools": broken_tools,
        }
    return None


def _document_text(server: Any, document: Path) -> str:
    return server.get_document_text(str(document)).get("text", "")


def _check_open_safety(document: Path) -> tuple[bool, str]:
    try:
        from hwpx.tools.package_validator import validate_editor_open_safety
    except Exception as exc:  # pragma: no cover - dependency diagnostic
        return False, f"validate_editor_open_safety unavailable: {exc}"
    report = validate_editor_open_safety(document)
    return bool(report.ok), getattr(report, "summary", "")


def _evaluate_oracle(server: Any, document: Path, oracle: dict[str, Any]) -> tuple[bool, str]:
    oracle_type = oracle["type"]
    if oracle_type == "text_contains":
        value = str(oracle["value"])
        return value in _document_text(server, document), f"text contains {value!r}"
    if oracle_type == "text_not_contains":
        value = str(oracle["value"])
        return value not in _document_text(server, document), f"text does not contain {value!r}"
    if oracle_type == "paragraph_count_min":
        paragraphs = server.get_paragraphs_text(str(document)).get("paragraphs", [])
        expected = int(oracle["value"])
        return len(paragraphs) >= expected, f"paragraph count >= {expected}"
    if oracle_type == "table_count_min":
        tables = server.get_table_map(str(document)).get("count", 0)
        expected = int(oracle["value"])
        return int(tables) >= expected, f"table count >= {expected}"
    if oracle_type == "table_cell_equals":
        table_index = int(oracle.get("tableIndex", 0))
        row = int(oracle["row"])
        col = int(oracle["col"])
        expected = str(oracle["value"])
        data = server.get_table_text(str(document), table_index).get("data", [])
        actual = data[row][col] if row < len(data) and col < len(data[row]) else None
        return actual == expected, f"table {table_index} cell ({row}, {col}) == {expected!r}"
    if oracle_type == "file_exists":
        path = Path(str(oracle["path"]).replace("{workDir}", str(document.parent)))
        return path.exists(), f"file exists: {path}"
    if oracle_type == "open_safety":
        return _check_open_safety(document)
    raise ValueError(f"unknown oracle type: {oracle_type}")


def _run_task(server: Any, tools: dict[str, Any], task: dict[str, Any], profile: Profile, work_dir: Path) -> dict[str, Any]:
    preflight = _preflight(task, profile)
    if preflight:
        return {
            "taskId": task["id"],
            "family": task["family"],
            "passed": False,
            **preflight,
        }

    task_dir = work_dir / profile.profile_id / task["id"]
    task_dir.mkdir(parents=True, exist_ok=True)
    document = task_dir / "document.hwpx"
    output_dir = task_dir / "preview"
    variables = {"document": str(document), "workDir": str(task_dir), "outputDir": str(output_dir)}

    try:
        _seed_document(server, task, document)
        call_results: list[dict[str, Any]] = []
        for call in task.get("toolCalls", []):
            tool_name = call["tool"]
            tool = tools.get(tool_name)
            if tool is None:
                return {
                    "taskId": task["id"],
                    "family": task["family"],
                    "passed": False,
                    "classification": FAIL_TOOL_ABSENT,
                    "reason": f"local harness does not know tool {tool_name}",
                }
            args = _render_value(call.get("arguments", {}), variables)
            result = tool(**args)
            call_results.append({"tool": tool_name, "ok": True, "resultKeys": sorted(result.keys()) if isinstance(result, dict) else []})

        oracle_results = []
        for oracle in task.get("oracles", []):
            rendered_oracle = _render_value(oracle, variables)
            ok, detail = _evaluate_oracle(server, document, rendered_oracle)
            oracle_results.append({"ok": ok, "detail": detail, "type": oracle["type"]})
            if not ok:
                return {
                    "taskId": task["id"],
                    "family": task["family"],
                    "passed": False,
                    "classification": FAIL_TOOL_MISBEHAVIOR,
                    "reason": f"oracle failed: {detail}",
                    "calls": call_results,
                    "oracles": oracle_results,
                }

        return {
            "taskId": task["id"],
            "family": task["family"],
            "passed": True,
            "classification": None,
            "reason": "",
            "calls": call_results,
            "oracles": oracle_results,
        }
    except Exception as exc:
        return {
            "taskId": task["id"],
            "family": task["family"],
            "passed": False,
            "classification": FAIL_TOOL_MISBEHAVIOR,
            "reason": str(exc),
        }


def _summarize_profile(profile: Profile, task_results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in task_results if result["passed"])
    total = len(task_results)
    families: dict[str, dict[str, int]] = {}
    failures_by_class: dict[str, int] = {}
    for result in task_results:
        family = result["family"]
        families.setdefault(family, {"passed": 0, "failed": 0})
        families[family]["passed" if result["passed"] else "failed"] += 1
        classification = result.get("classification")
        if classification:
            failures_by_class[classification] = failures_by_class.get(classification, 0) + 1
    return {
        "profileId": profile.profile_id,
        "label": profile.label,
        "pluginVersion": profile.plugin_version,
        "score": round(passed / total, 4) if total else 0,
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "families": families,
        "failuresByClassification": failures_by_class,
        "results": task_results,
    }


def _comparison(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    if len(summaries) < 2:
        return {}
    baseline = summaries[-1]
    current = summaries[0]
    return {
        "baselineProfileId": baseline["profileId"],
        "currentProfileId": current["profileId"],
        "scoreDelta": round(current["score"] - baseline["score"], 4),
        "passedDelta": current["passed"] - baseline["passed"],
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# HWPX Task Evaluation Report",
        "",
        f"- Generated: {report['generatedAt']}",
        f"- Tasks: {report['taskCount']}",
        "",
        "| Profile | Version | Score | Passed | Failed |",
        "|---|---:|---:|---:|---:|",
    ]
    for profile in report["profiles"]:
        lines.append(
            f"| {profile['profileId']} | {profile['pluginVersion']} | "
            f"{profile['score']:.2%} | {profile['passed']} | {profile['failed']} |"
        )
    lines.extend(["", "## Failure Classification", ""])
    for profile in report["profiles"]:
        lines.append(f"### {profile['profileId']}")
        failures = profile["failuresByClassification"]
        if not failures:
            lines.append("- none")
        else:
            for key, count in sorted(failures.items()):
                lines.append(f"- {key}: {count}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(tasks_path: Path, profile_paths: list[Path], output: Path, markdown: Path | None, work_dir: Path | None) -> dict[str, Any]:
    server = _load_server_module()
    tools = _available_server_tools(server)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload["tasks"]
    profiles = [Profile.from_path(path) for path in profile_paths]
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="hwpx_task_eval_")
        work_dir = Path(temp_dir.name)
    else:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)

    try:
        summaries = []
        for profile in profiles:
            results = [_run_task(server, tools, task, profile, work_dir) for task in tasks]
            summaries.append(_summarize_profile(profile, results))
        report = {
            "schemaVersion": "hwpx.task-eval-report.v1",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "taskSpec": str(tasks_path),
            "taskCount": len(tasks),
            "families": sorted({task["family"] for task in tasks}),
            "profiles": summaries,
            "comparison": _comparison(summaries),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if markdown is not None:
            markdown.parent.mkdir(parents=True, exist_ok=True)
            _write_markdown(report, markdown)
        return report
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay and score HWPX task evaluation specs")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--profile", type=Path, action="append", dest="profiles")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    profile_paths = args.profiles or DEFAULT_PROFILES
    report = run(args.tasks, profile_paths, args.output, args.markdown, args.work_dir)
    current = report["profiles"][0]
    print(
        f"[OK] evaluated {report['taskCount']} tasks for {len(report['profiles'])} profiles; "
        f"{current['profileId']} score={current['score']:.2%}"
    )
    print(f"[OK] report: {args.output}")
    if args.markdown:
        print(f"[OK] markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
