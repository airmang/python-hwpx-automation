#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Deterministically replay preselected HWPX tool calls and score automatic oracles.

This harness does not ask an agent to select tools from natural-language instructions.
It is therefore regression evidence, never live-agent routing or recovery evidence.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
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
    ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.4.0.json",
    ROOT / "examples" / "eval_tasks" / "profiles" / "current-0.1.6.json",
    ROOT / "examples" / "eval_tasks" / "profiles" / "baseline-0.1.5.json",
]
DEFAULT_OUTPUT = ROOT / "examples" / "out" / "deterministic_task_replay_report.json"

FAIL_TOOL_ABSENT = "tool_absent"
FAIL_TOOL_MISBEHAVIOR = "tool_misbehavior"
FAIL_SKILL_GUIDANCE_GAP = "skill_guidance_gap"

# Body-verification keyword groups per guidance tag. A profile claiming a tag is
# not enough: every keyword listed here must literally appear in the skill
# bundle body (SKILL.md + references/*.md), otherwise the task fails with
# skill_guidance_gap. Profile guidanceTags stay as an auxiliary check.
GUIDANCE_BODY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "transaction-edits": (
        "apply_edits",
        "dry_run",
        "expected_revision",
        "idempotency_key",
        "undo_last_edit",
    ),
    "render-preview-review": ("render_preview", "htmlPath", "visualReviewPath"),
    "format-edits": (
        "set_paragraph_format",
        "line_spacing_percent",
        "set_page_setup",
        "set_header_footer",
        "set_page_number",
        "set_list_format",
    ),
    "picture-edits": ("insert_picture", "replace_picture"),
    "doc-compare": ("doc_diff", "create_comparison_table_document"),
    "advanced-generators": (
        "build_image_grid",
        "build_meeting_nameplates",
        "build_organization_chart",
    ),
    "document-map": ("get_document_map", "document_revision"),
    "blueprint-routing": (
        "dump_document_blueprint",
        "replay_document_blueprint",
        "portable",
        "source-bound",
        "unsupported",
        "exact|mapped",
        "hwpx dump --inspect",
        "hwpx dump --repack",
    ),
    "blueprint-refusals": (
        "raw XML",
        "resident session",
        "watch",
        "OfficeCLI adapter",
        "전문 workflow",
        "unverified",
    ),
}


def _load_skill_bundle_text(skill_root: Path) -> str:
    """Load authored guidance, excluding the generated inventory table.

    Tool availability comes from the generated JSON contract. Counting that generated
    name table as authored guidance would make every registered tool look intentionally
    routed even when no user-facing workflow mentions it.
    """
    paths = [skill_root / "SKILL.md"]
    references = skill_root / "references"
    if references.is_dir():
        paths.extend(
            path
            for path in sorted(references.glob("*.md"))
            if path.name != "tool-contract.generated.md"
        )
    chunks = [path.read_text(encoding="utf-8") for path in paths if path.is_file()]
    if not chunks:
        raise FileNotFoundError(f"no skill bundle text found under {skill_root}")
    return "\n".join(chunks)


def _bundle_mentions(bundle_text: str, token: str) -> bool:
    pattern = rf"(?<![0-9A-Za-z_]){re.escape(token)}(?![0-9A-Za-z_])"
    return re.search(pattern, bundle_text) is not None


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
        if isinstance(tools, dict):
            if tools != {"source": "generated-contract", "profile": "default"}:
                raise ValueError(f"unsupported availableTools source in {path}: {tools}")
            contract_path = next(
                (
                    parent / "references" / "tool-contract.generated.json"
                    for parent in path.parents
                    if (parent / "references" / "tool-contract.generated.json").is_file()
                ),
                ROOT / "references" / "tool-contract.generated.json",
            )
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            available = {
                tool["name"] for tool in contract["tools"] if tool["profile"] == "default"
            }
        else:
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
    candidates: list[Path] = []
    env_repo = os.environ.get("HWPX_MCP_SERVER_REPO")
    if env_repo:
        candidates.append(Path(env_repo) / "src")
    env_hwpx = os.environ.get("PYTHON_HWPX_REPO")
    if env_hwpx:
        candidates.append(Path(env_hwpx) / "src")
    candidates.extend(
        [
            ROOT.parent / "hwpx-mcp-server" / "src",
            ROOT.parent / "python-hwpx" / "src",
        ]
    )
    # Insert in reverse so the explicit release-candidate checkouts remain
    # ahead of sibling defaults.  The old forward insert(0) loop silently put
    # the defaults first and could grade a different stack than requested.
    for candidate in reversed(candidates):
        if candidate.exists():
            source = str(candidate.resolve())
            while source in sys.path:
                sys.path.remove(source)
            sys.path.insert(0, source)


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
        from hwpx_mcp_server.core.formatting import (
            create_style_in_doc,
            format_text_range,
        )
        from hwpx_mcp_server.core.search import (
            batch_replace_in_doc,
            find_in_doc,
            replace_in_doc,
        )

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

    def create_document(
        self, filename: str, title: str | None = None, author: str | None = None
    ) -> dict[str, Any]:
        del title, author
        verification = self._create_blank(filename)
        return {
            "filename": filename,
            "created": True,
            "openSafety": verification.get("openSafety"),
        }

    def add_paragraph(
        self, filename: str, text: str, style: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        index = self._mutate(
            filename, lambda doc: self._add_paragraph_to_doc(doc, text, style)
        )
        return {"paragraph_index": index}

    def add_heading(
        self, filename: str, text: str, level: int = 1, dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        index = self._mutate(
            filename, lambda doc: self._add_heading_to_doc(doc, text, level)
        )
        return {"paragraph_index": index}

    def add_table(
        self,
        filename: str,
        rows: int,
        cols: int,
        data: list[list[str]] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        index = self._mutate(
            filename, lambda doc: self._add_table_to_doc(doc, rows, cols, data)
        )
        return {"table_index": index}

    def add_page_break(self, filename: str, dry_run: bool = False) -> dict[str, Any]:
        del dry_run
        self._mutate(filename, self._add_page_break_to_doc)
        return {"success": True}

    def search_and_replace(
        self, filename: str, find_text: str, replace_text: str, dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        count = self._mutate(
            filename, lambda doc: self._replace_in_doc(doc, find_text, replace_text)
        )
        return {"replaced_count": count}

    def batch_replace(
        self, filename: str, replacements: list[dict[str, str]], dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        return self._mutate(
            filename, lambda doc: self._batch_replace_in_doc(doc, replacements)
        )

    def insert_paragraph(
        self,
        filename: str,
        paragraph_index: int,
        text: str,
        style: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        index = self._mutate(
            filename,
            lambda doc: self._insert_paragraph_to_doc(
                doc, paragraph_index, text, style
            ),
        )
        return {"inserted_index": index}

    def delete_paragraph(
        self, filename: str, paragraph_index: int, dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        remaining = self._mutate(
            filename, lambda doc: self._delete_paragraph_from_doc(doc, paragraph_index)
        )
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

    def fill_by_path(
        self, filename: str, mappings: dict[str, str], dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        return self._mutate(
            filename, lambda doc: self._fill_by_path_in_doc(doc, mappings)
        )

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

    def format_table(
        self,
        filename: str,
        table_index: int,
        has_header_row: bool | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        self._mutate(
            filename,
            lambda doc: self._format_table_in_doc(
                doc, table_index, has_header_row=has_header_row
            ),
        )
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
        self._mutate(
            filename,
            lambda doc: self._merge_cells_in_table(
                doc, table_index, start_row, start_col, end_row, end_col
            ),
        )
        return {"merged": True}

    def split_table_cell(
        self, filename: str, table_index: int, row: int, col: int, dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        span = self._mutate(
            filename, lambda doc: self._split_cell_in_table(doc, table_index, row, col)
        )
        return {"split": True, "original_span": span}

    def add_memo(
        self,
        filename: str,
        paragraph_index: int | None = None,
        text: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        del dry_run
        return self._mutate(
            filename, lambda doc: self._add_memo_to_doc(doc, paragraph_index, text)
        )

    def find_text(
        self,
        filename: str,
        text_to_find: str,
        match_case: bool = True,
        max_results: int = 50,
    ) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._find_in_doc(
            doc,
            text_to_find=text_to_find,
            match_case=match_case,
            max_results=max_results,
        )

    def find_cell_by_label(
        self, filename: str, label_text: str, direction: str = "right"
    ) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._find_cell_by_label_in_doc(doc, label_text, direction=direction)

    def apply_edits(
        self, filename: str, operations: list[dict[str, Any]], dry_run: bool = False
    ) -> dict[str, Any]:
        del dry_run
        for operation in operations:
            op_type = operation["type"]
            if op_type == "add_paragraph":
                self.add_paragraph(filename, operation.get("text", ""))
            elif op_type == "replace_text":
                self.search_and_replace(
                    filename, operation["findText"], operation.get("replaceText", "")
                )
            elif op_type == "add_table":
                self.add_table(
                    filename,
                    int(operation["rows"]),
                    int(operation["cols"]),
                    operation.get("data"),
                )
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
        html_path.write_text(
            "<!doctype html><meta charset='utf-8'><p>fallback preview</p>\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps({"status": "html_only", "sourcePath": filename}) + "\n",
            encoding="utf-8",
        )
        return {
            "status": "html_only",
            "htmlPath": str(html_path),
            "manifestPath": str(manifest_path),
        }

    def get_document_text(self, filename: str) -> dict[str, Any]:
        doc = self._open_doc(filename)
        try:
            text = doc.export_text()
        except Exception:
            text = "\n".join(paragraph.text or "" for paragraph in doc.paragraphs)
        return {"text": text}

    def get_paragraphs_text(
        self,
        filename: str,
        start_index: int = 0,
        end_index: int | None = None,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        del max_chars
        doc = self._open_doc(filename)
        paragraphs = doc.paragraphs[start_index:end_index]
        return {
            "paragraphs": [
                {"index": start_index + index, "text": paragraph.text or ""}
                for index, paragraph in enumerate(paragraphs)
            ]
        }

    def get_table_map(self, filename: str) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._get_table_map_in_doc(doc)

    def get_table_text(self, filename: str, table_index: int = 0) -> dict[str, Any]:
        doc = self._open_doc(filename)
        return self._get_table_data(doc, table_index)

    def get_document_map(
        self, filename: str, max_preview_chars: int = 80
    ) -> dict[str, Any]:
        doc = self._open_doc(filename)
        limit = max(0, int(max_preview_chars))
        paragraph_anchors = [
            {
                "kind": "paragraph",
                "paragraphIndex": index,
                "textPreview": (paragraph.text or "")[:limit],
                "anchor": {"kind": "body_paragraph", "paragraphIndex": index},
            }
            for index, paragraph in enumerate(doc.paragraphs)
        ]
        table_map = self._get_table_map_in_doc(doc)
        return {
            "filename": filename,
            "info": {
                "sections": len(doc.sections),
                "paragraphs": len(doc.paragraphs),
                "tables": table_map.get("count", 0),
            },
            "outline": [],
            "tables": table_map,
            "formFields": {"fields": []},
            "anchors": {
                "paragraphs": paragraph_anchors,
                "tables": table_map.get("tables", []),
            },
        }

    def set_paragraph_format(
        self,
        filename: str,
        dry_run: bool = False,
        expected_revision: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision
        result = self._mutate(filename, lambda doc: doc.set_paragraph_format(**kwargs))
        return dict(result or {}, filename=filename)

    def set_page_setup(
        self,
        filename: str,
        dry_run: bool = False,
        expected_revision: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision
        result = self._mutate(filename, lambda doc: doc.set_page_setup(**kwargs))
        return dict(result or {}, filename=filename)

    def set_header_footer(
        self,
        filename: str,
        kind: str,
        dry_run: bool = False,
        expected_revision: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision
        wrapper = self._mutate(
            filename, lambda doc: doc.set_header_footer(kind=kind, **kwargs)
        )
        return {
            "filename": filename,
            "headerFooter": {"kind": kind, "text": getattr(wrapper, "text", "")},
        }

    def set_page_number(
        self,
        filename: str,
        dry_run: bool = False,
        expected_revision: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision
        wrapper = self._mutate(filename, lambda doc: doc.set_page_number(**kwargs))
        return {
            "filename": filename,
            "headerFooter": {
                "kind": kwargs.get("target", "footer"),
                "text": getattr(wrapper, "text", ""),
            },
        }

    def set_list_format(
        self,
        filename: str,
        dry_run: bool = False,
        expected_revision: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision
        result = self._mutate(filename, lambda doc: doc.set_list_format(**kwargs))
        return dict(result or {}, filename=filename)

    @staticmethod
    def _decode_image(image_base64: str) -> bytes:
        import base64

        return base64.b64decode(image_base64)

    def insert_picture(
        self,
        filename: str,
        image_base64: str,
        image_format: str = "png",
        dry_run: bool = False,
        expected_revision: str | None = None,
        output: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision, output
        image_data = self._decode_image(image_base64)

        def insert(doc: Any) -> list[dict[str, Any]]:
            doc.add_picture(image_data, image_format, **kwargs)
            return doc.picture_references()

        picture_refs = self._mutate(filename, insert)
        return {
            "ok": True,
            "filename": filename,
            "picture": picture_refs[-1] if picture_refs else None,
            "pictureReferences": picture_refs,
        }

    def replace_picture(
        self,
        filename: str,
        image_base64: str,
        image_format: str = "png",
        dry_run: bool = False,
        expected_revision: str | None = None,
        output: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del dry_run, expected_revision, output
        image_data = self._decode_image(image_base64)

        def replace(doc: Any) -> dict[str, Any]:
            replacement = doc.replace_picture(image_data, image_format, **kwargs)
            return {
                "replacement": replacement,
                "pictureReferences": doc.picture_references(),
            }

        result = self._mutate(filename, replace)
        return {"ok": True, "filename": filename, **result}

    def undo_last_edit(self, filename: str) -> dict[str, Any]:
        from hwpx_mcp_server.core.transactions import undo_last_backup

        return undo_last_backup(filename)

    def doc_diff(
        self,
        old_filename: str | None = None,
        new_filename: str | None = None,
        old_paragraphs: list[str] | None = None,
        new_paragraphs: list[str] | None = None,
    ) -> dict[str, Any]:
        from hwpx import doc_diff as hwpx_doc_diff

        if old_filename and new_filename:
            return hwpx_doc_diff(old_filename, new_filename)
        if old_paragraphs is not None and new_paragraphs is not None:
            return hwpx_doc_diff(old_paragraphs, new_paragraphs)
        raise ValueError(
            "provide old_filename/new_filename or old_paragraphs/new_paragraphs"
        )

    def create_comparison_table_document(
        self,
        filename: str,
        old_filename: str | None = None,
        new_filename: str | None = None,
        old_paragraphs: list[str] | None = None,
        new_paragraphs: list[str] | None = None,
        title: str = "신구대조표",
        include_equal: bool = True,
        verbosity: str = "compact",
    ) -> dict[str, Any]:
        del verbosity
        from hwpx import (
            build_comparison_table_plan,
            create_document_from_plan,
            validate_document_plan,
        )

        old_source: Any
        new_source: Any
        if old_filename and new_filename:
            old_source, new_source = old_filename, new_filename
        elif old_paragraphs is not None and new_paragraphs is not None:
            old_source, new_source = old_paragraphs, new_paragraphs
        else:
            raise ValueError(
                "provide old_filename/new_filename or old_paragraphs/new_paragraphs"
            )
        document_plan = build_comparison_table_plan(
            old_source, new_source, title=title, include_equal=include_equal
        )
        validation = validate_document_plan(document_plan)
        if not validation.ok:
            return {
                "filename": filename,
                "created": False,
                "plan_validation": validation.to_dict(),
            }
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        doc = create_document_from_plan(document_plan, preset="government_report")
        try:
            doc.save_to_path(filename)
        finally:
            doc.close()
        return {
            "filename": filename,
            "created": True,
            "document_plan": document_plan,
            "plan_validation": validation.to_dict(),
        }

    @staticmethod
    def _single_block_plan(block: dict[str, Any], title: str) -> dict[str, Any]:
        return {
            "schemaVersion": "hwpx.document_plan.v2",
            "title": title,
            "sections": [{"blocks": [block]}],
        }

    def build_image_grid(
        self,
        images: list,
        columns: int = 2,
        image_width_mm: float | None = None,
        title: str = "사진대지",
    ) -> dict[str, Any]:
        from hwpx import build_image_grid as hwpx_build_image_grid

        block = hwpx_build_image_grid(
            images or [], columns=columns, image_width_mm=image_width_mm
        )
        return {
            "block": block,
            "document_plan": self._single_block_plan(block, title),
            "next_tool": "create_document_from_plan",
        }

    def build_meeting_nameplates(
        self,
        names: list[str],
        size: str = "150x70",
        columns: int = 2,
        title: str = "회의 명패",
    ) -> dict[str, Any]:
        from hwpx import build_meeting_nameplates as hwpx_build_meeting_nameplates

        block = hwpx_build_meeting_nameplates(names or [], size=size, columns=columns)
        return {
            "block": block,
            "document_plan": self._single_block_plan(block, title),
            "next_tool": "create_document_from_plan",
        }

    def build_organization_chart(
        self,
        hierarchy: dict | list,
        max_depth: int = 3,
        title: str = "조직도",
    ) -> dict[str, Any]:
        from hwpx import build_organization_chart as hwpx_build_organization_chart

        block = hwpx_build_organization_chart(hierarchy or {}, max_depth=max_depth)
        return {
            "block": block,
            "document_plan": self._single_block_plan(block, title),
            "next_tool": "create_document_from_plan",
        }


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


def _available_server_tools(server: Any, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    names = {"create_document", "add_paragraph", "add_table"}
    names.update(
        call["tool"]
        for task in tasks
        for call in task.get("toolCalls", [])
    )
    return {name: getattr(server, name) for name in names if hasattr(server, name)}


def _seed_document(server: Any, task: dict[str, Any], document: Path) -> None:
    seed = task.get("startDocument", {"kind": "blank"})
    kind = seed.get("kind", "blank")
    server.create_document(str(document))
    for paragraph in seed.get("paragraphs", []):
        server.add_paragraph(str(document), paragraph)
    for table in seed.get("tables", []):
        rows = int(table.get("rows", len(table.get("data", [])) or 1))
        cols = int(
            table.get(
                "cols", max((len(row) for row in table.get("data", [])), default=1)
            )
        )
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


def _preflight(
    task: dict[str, Any], profile: Profile, bundle_text: str
) -> dict[str, Any] | None:
    required_tools = _tool_required_by_task(task)

    undocumented_tools = sorted(
        tool for tool in required_tools if not _bundle_mentions(bundle_text, tool)
    )
    if undocumented_tools:
        return {
            "classification": FAIL_SKILL_GUIDANCE_GAP,
            "reason": "skill bundle body does not document required tools",
            "missingBundleTools": undocumented_tools,
        }

    required_guidance = set(task.get("requiredGuidance", []))
    missing_evidence: dict[str, list[str]] = {}
    for tag in sorted(required_guidance):
        keywords = GUIDANCE_BODY_KEYWORDS.get(tag, ())
        missing_keywords = [
            keyword
            for keyword in keywords
            if not _bundle_mentions(bundle_text, keyword)
        ]
        if missing_keywords:
            missing_evidence[tag] = missing_keywords
    if missing_evidence:
        return {
            "classification": FAIL_SKILL_GUIDANCE_GAP,
            "reason": "skill bundle body lacks required guidance keywords",
            "missingGuidanceEvidence": missing_evidence,
        }

    missing_guidance = sorted(required_guidance - profile.guidance_tags)
    if missing_guidance:
        return {
            "classification": FAIL_SKILL_GUIDANCE_GAP,
            "reason": "profile is missing required skill guidance tags",
            "missingGuidance": missing_guidance,
        }

    missing_tools = sorted(
        tool for tool in required_tools if not profile.has_tool(tool)
    )
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


def _evaluate_oracle(
    server: Any,
    document: Path,
    oracle: dict[str, Any],
    call_payloads: list[Any] | None = None,
) -> tuple[bool, str]:
    oracle_type = oracle["type"]
    if oracle_type == "call_result_has":
        call_index = int(oracle.get("callIndex", 0))
        key = str(oracle["key"])
        payloads = call_payloads or []
        if call_index >= len(payloads):
            return (
                False,
                f"call {call_index} result missing (only {len(payloads)} calls)",
            )
        payload = payloads[call_index]
        ok = isinstance(payload, dict) and key in payload and payload[key] is not None
        return ok, f"call {call_index} result has key {key!r}"
    if oracle_type == "text_contains":
        value = str(oracle["value"])
        return value in _document_text(server, document), f"text contains {value!r}"
    if oracle_type == "text_not_contains":
        value = str(oracle["value"])
        return value not in _document_text(
            server, document
        ), f"text does not contain {value!r}"
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
        return (
            actual == expected,
            f"table {table_index} cell ({row}, {col}) == {expected!r}",
        )
    if oracle_type == "file_exists":
        path = Path(str(oracle["path"]).replace("{workDir}", str(document.parent)))
        return path.exists(), f"file exists: {path}"
    if oracle_type == "open_safety":
        return _check_open_safety(document)
    raise ValueError(f"unknown oracle type: {oracle_type}")


def _run_task(
    server: Any,
    tools: dict[str, Any],
    task: dict[str, Any],
    profile: Profile,
    work_dir: Path,
    bundle_text: str,
) -> dict[str, Any]:
    preflight = _preflight(task, profile, bundle_text)
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
    variables = {
        "document": str(document),
        "workDir": str(task_dir),
        "outputDir": str(output_dir),
    }

    try:
        _seed_document(server, task, document)
        call_results: list[dict[str, Any]] = []
        call_payloads: list[Any] = []
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
            call_payloads.append(result)
            call_results.append(
                {
                    "tool": tool_name,
                    "ok": True,
                    "resultKeys": sorted(result.keys())
                    if isinstance(result, dict)
                    else [],
                }
            )

        oracle_results = []
        for oracle in task.get("oracles", []):
            rendered_oracle = _render_value(oracle, variables)
            ok, detail = _evaluate_oracle(
                server, document, rendered_oracle, call_payloads
            )
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


def _summarize_profile(
    profile: Profile, task_results: list[dict[str, Any]]
) -> dict[str, Any]:
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
            failures_by_class[classification] = (
                failures_by_class.get(classification, 0) + 1
            )
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
        "againstProfiles": [
            {
                "profileId": other["profileId"],
                "scoreDelta": round(current["score"] - other["score"], 4),
                "passedDelta": current["passed"] - other["passed"],
            }
            for other in summaries[1:]
        ],
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# HWPX Deterministic Direct-Call Replay Report",
        "",
        "> This is deterministic replay of preselected calls. It is not live-agent tool-selection, routing, recovery, or unnecessary-call evidence.",
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


def run(
    tasks_path: Path,
    profile_paths: list[Path],
    output: Path,
    markdown: Path | None,
    work_dir: Path | None,
    skill_root: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload["tasks"]
    profiles = [Profile.from_path(path) for path in profile_paths]
    resolved_skill_root = skill_root or ROOT
    bundle_text = _load_skill_bundle_text(resolved_skill_root)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="hwpx_task_eval_")
        work_dir = Path(temp_dir.name)
    else:
        # Tool calls receive paths derived from this directory.  Normalize it
        # before configuring the workspace policy so a caller-provided relative
        # evidence path cannot be interpreted again relative to the workspace
        # root and rejected as an escape.
        work_dir = work_dir.resolve()
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)

    previous_workspace_roots = os.environ.get("HWPX_MCP_WORKSPACE_ROOTS")
    previous_sandbox_root = os.environ.pop("HWPX_MCP_SANDBOX_ROOT", None)
    os.environ["HWPX_MCP_WORKSPACE_ROOTS"] = json.dumps([str(work_dir.resolve())])
    try:
        server = _load_server_module()
        if hasattr(server, "_OPS"):
            from hwpx_mcp_server.hwpx_ops import HwpxOps
            from hwpx_mcp_server.storage import LocalDocumentStorage
            from hwpx_mcp_server.workspace import WorkspaceResolver

            ops = HwpxOps(
                storage=LocalDocumentStorage(
                    workspace_resolver=WorkspaceResolver.from_environment(),
                    auto_backup=False,
                )
            )
            # Feature 025 moved handler ownership to the stable runtime-service
            # container.  New runtimes must replace that graph through the
            # compatibility hook; the assignment remains for older profiles
            # replayed by this cross-version harness.
            replace_ops = getattr(server, "_replace_ops", None)
            if callable(replace_ops):
                replace_ops(ops)
            else:
                server._OPS = ops
        tools = _available_server_tools(server, tasks)
        summaries = []
        for profile in profiles:
            results = [
                _run_task(server, tools, task, profile, work_dir, bundle_text)
                for task in tasks
            ]
            summaries.append(_summarize_profile(profile, results))
        report = {
            "schemaVersion": "hwpx.deterministic-task-replay-report.v1",
            "evaluationKind": "deterministic-direct-tool-replay",
            "instructionSelectionUsed": False,
            "liveAgentEvidence": False,
            "routingMeasured": False,
            "recoveryMeasured": False,
            "unnecessaryCallsMeasured": False,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "taskSpec": str(tasks_path),
            "taskCount": len(tasks),
            "families": sorted({task["family"] for task in tasks}),
            "guidanceVerification": {
                "mode": "bundle-body",
                "skillRoot": str(resolved_skill_root),
                "bundleChars": len(bundle_text),
            },
            "profiles": summaries,
            "comparison": _comparison(summaries),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if markdown is not None:
            markdown.parent.mkdir(parents=True, exist_ok=True)
            _write_markdown(report, markdown)
        return report
    finally:
        if previous_workspace_roots is None:
            os.environ.pop("HWPX_MCP_WORKSPACE_ROOTS", None)
        else:
            os.environ["HWPX_MCP_WORKSPACE_ROOTS"] = previous_workspace_roots
        if previous_sandbox_root is not None:
            os.environ["HWPX_MCP_SANDBOX_ROOT"] = previous_sandbox_root
        if temp_dir is not None:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically replay preselected HWPX calls; this does not measure "
            "live-agent tool selection or recovery"
        )
    )
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--profile", type=Path, action="append", dest="profiles")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--skill-root", type=Path, default=None)
    args = parser.parse_args(argv)

    profile_paths = args.profiles or DEFAULT_PROFILES
    report = run(
        args.tasks,
        profile_paths,
        args.output,
        args.markdown,
        args.work_dir,
        args.skill_root,
    )
    current = report["profiles"][0]
    print(
        f"[OK] deterministically replayed {report['taskCount']} tasks for {len(report['profiles'])} profiles; "
        f"{current['profileId']} score={current['score']:.2%}"
    )
    print(f"[OK] report: {args.output}")
    if args.markdown:
        print(f"[OK] markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
