#!/usr/bin/env python3
"""Fail when the P3 architecture baseline changes without an explicit review."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from pprint import pformat
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "hwpx_automation"
SERVICES_ROOT = PACKAGE_ROOT / "ops_services"

# S-081 removed the last cycle (render contracts extracted to a leaf module);
# the baseline is now exactly zero and must stay there.
EXPECTED_PACKAGE_CYCLES: tuple[tuple[str, ...], ...] = ()

# Modules allowed to import the mcp SDK at all. Everything else must reach the
# SDK through these seams (the audited adapter owns every private access), so a
# novel private-internal dependency cannot appear outside this list unnoticed.
EXPECTED_SDK_IMPORTERS = (
    "hwpx_automation.fastmcp_adapter",
    "hwpx_automation.handlers.quality_render",
    "hwpx_automation.runtime",
    "hwpx_automation.runtime_services",
)

EXPECTED_SERVICE_LINES = {
    "_border_fill.py": 283,
    # WP-F: add_equation/add_chart/set_header_footer/set_page_number now
    # dispatch to the page/shapes namespaces and .to_dict() the returned
    # living views before this op's dict-mutation contract (result.update()).
    "content_layout.py": 547,
    "context.py": 213,
    # Receipt-truthfulness repair: the publish decision now compares the
    # produced bytes against the source instead of trusting a field on the
    # domain payload. A payload describing only the structural step suppressed
    # the write entirely while the tool reported ok with twenty-six fills.
    # WP-F (core 6.0 namespace adaptation): add_form_field/fill_form_field now
    # rebuild the 5.x form-field dict shape from FormField/FieldFillResult
    # living views via a local _form_field_to_legacy_dict helper (design §2.3).
    "form_fields.py": 742,
    # WP-F: insert_picture/replace_picture rebuild the picture-reference and
    # replacement payload shapes from PictureRef/PictureReplacement, whose own
    # to_dict() keys do not match this op's established contract.
    "media.py": 208,
    # WP-F: add_memo/fill now create the host paragraph explicitly before
    # calling notes.add_memo(anchor=...), which has no auto-create fallback
    # (unlike 5.x's add_memo_with_anchor(paragraph=None)).
    "memo_style.py": 489,
    "package_validation.py": 166,
    "planning.py": 201,
    # S-108: canonical Chrome-path guidance names the 6.x fallback explicitly.
    "preview_export.py": 585,
    "read_query.py": 601,
    # Receipt-truthfulness repair: the written verification report copied the
    # domain payload's preservation claim verbatim, so an incoherent payload
    # printed a byteIdentical receipt onto a rewritten document. The seam now
    # refuses the impossible combination rather than forwarding it.
    "save_policy.py": 616,
    # core 6.1.0 removed HwpxOxmlHeader._update_border_fills_item_count; the
    # hasattr fallback (equivalent direct itemCnt computation) is now the only
    # branch, so the dead private call went away.
    "tables.py": 536,
    "transactions.py": 616,
}

EXPECTED_FACADE_LINES = {
    "hwpx_ops.py": 1526,
    # S-108: shared identity/config helpers replaced duplicated MCP-era parsing.
    "server.py": 268,
}

PRIVATE_ATTRIBUTES = ("_mcp_server", "_tool_manager", "_tools")

EXPECTED_PRIVATE_ACCESSES = (
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "_mcp_server",
        'runtime = getattr(mcp, "_mcp_server", None)',
    ),
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "_tool_manager",
        'manager = getattr(mcp, "_tool_manager", None)',
    ),
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "_tools",
        'tools = getattr(manager, "_tools", None)',
    ),
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "request_handlers",
        "previous_handler = request_handlers[mcp_types.CallToolRequest]",
    ),
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "request_handlers",
        "request_handlers[mcp_types.CallToolRequest] = previous_handler",
    ),
    (
        "src/hwpx_automation/fastmcp_adapter.py",
        "request_handlers",
        "request_handlers[mcp_types.CallToolRequest] = strict_call_handler",
    ),
)

C901_PATHS = (
    "src/hwpx_automation/handlers",
    "src/hwpx_automation/ops_services",
    "src/hwpx_automation/runtime.py",
    "src/hwpx_automation/runtime_services.py",
    "src/hwpx_automation/fastmcp_adapter.py",
    "src/hwpx_automation/tool_bindings.py",
    "src/hwpx_automation/server.py",
    "src/hwpx_automation/hwpx_ops.py",
    "src/hwpx_automation/form_fill.py",
    "src/hwpx_automation/office/agent",
    "src/hwpx_automation/office/authoring",
    "src/hwpx_automation/office/compliance",
    "src/hwpx_automation/office/evalplan",
    "src/hwpx_automation/office/form_fill",
    "src/hwpx_automation/office/quality",
    "src/hwpx_automation/office/utilities",
    "src/hwpx_automation/tool_contract.py",
    "src/hwpx_automation/workflow/service.py",
)

# report_parser arrived from python-hwpx unchanged in the 5.0 train — the S-099
# authoring migration had left it behind. Its complexity is relocated, not new:
# core's own ratchet lost the same function on the other side.
EXPECTED_C901 = (
    ("src/hwpx_automation/fastmcp_adapter.py", "_normalize_implicit_none_parameters", 13),
    ("src/hwpx_automation/fastmcp_adapter.py", "_register", 19),
    ("src/hwpx_automation/fastmcp_adapter.py", "normalize_schema", 12),
    ("src/hwpx_automation/form_fill.py", "_build_mapping_analysis", 12),
    ("src/hwpx_automation/form_fill.py", "_canonical_input_from_docx", 13),
    ("src/hwpx_automation/form_fill.py", "apply_form_fill_workflow", 12),
    ("src/hwpx_automation/handlers/content_edit.py", "_apply_edit_operation", 20),
    ("src/hwpx_automation/handlers/content_edit.py", "replace_in_paragraph", 14),
    ("src/hwpx_automation/handlers/read_export.py", "_build_read_model", 15),
    ("src/hwpx_automation/handlers/tracked_changes.py", "_validate_tracked_edits", 19),
    ("src/hwpx_automation/handlers/tracked_changes.py", "add_tracked_edit", 12),
    ("src/hwpx_automation/office/agent/blueprint/dump.py", "_make_manifest", 16),
    ("src/hwpx_automation/office/agent/blueprint/mapping.py", "_preflight_graph", 15),
    ("src/hwpx_automation/office/agent/blueprint/model.py", "_validate_public_json", 11),
    ("src/hwpx_automation/office/agent/blueprint/model.py", "validate_replay_request", 14),
    ("src/hwpx_automation/office/agent/blueprint/native.py", "create_root", 14),
    ("src/hwpx_automation/office/agent/cli.py", "main", 14),
    ("src/hwpx_automation/office/agent/commands.py", "_add", 16),
    ("src/hwpx_automation/office/agent/commands.py", "_move", 15),
    ("src/hwpx_automation/office/agent/commands.py", "_refresh_copy_identities", 13),
    ("src/hwpx_automation/office/agent/commands.py", "_remove", 12),
    ("src/hwpx_automation/office/agent/document.py", "_project_paragraph", 13),
    ("src/hwpx_automation/office/agent/form_plan.py", "_validate_plan_target", 11),
    ("src/hwpx_automation/office/agent/form_plan.py", "_validate_public_plan_request", 11),
    ("src/hwpx_automation/office/agent/form_plan.py", "validate_mixed_form_request", 13),
    ("src/hwpx_automation/office/agent/model.py", "__post_init__", 15),
    ("src/hwpx_automation/office/agent/model.py", "validate_agent_batch", 16),
    ("src/hwpx_automation/office/agent/path.py", "parse_path", 19),
    ("src/hwpx_automation/office/agent/query.py", "_split_steps", 15),
    ("src/hwpx_automation/office/authoring/__init__.py", "_bridge_to_design_plan", 15),
    ("src/hwpx_automation/office/authoring/__init__.py", "_normalize_block", 13),
    ("src/hwpx_automation/office/authoring/__init__.py", "_normalize_v2_block", 15),
    ("src/hwpx_automation/office/authoring/__init__.py", "_recovery_summary", 12),
    ("src/hwpx_automation/office/authoring/__init__.py", "_validate_block", 19),
    ("src/hwpx_automation/office/authoring/__init__.py", "inspect_document_authoring_quality", 15),
    ("src/hwpx_automation/office/authoring/__init__.py", "validate_document_plan", 11),
    ("src/hwpx_automation/office/authoring/builder/core.py", "_section_feature_flags", 14),
    ("src/hwpx_automation/office/authoring/builder/core.py", "lower", 18),
    ("src/hwpx_automation/office/authoring/presets/proposal.py", "create_proposal_document", 11),
    ("src/hwpx_automation/office/authoring/report_parser.py", "parse_government_report_text", 13),
    ("src/hwpx_automation/office/authoring/template_analyzer.py", "main", 11),
    ("src/hwpx_automation/office/compliance/official_lint.py", "_paragraphs_from_document_plan", 14),
    ("src/hwpx_automation/office/compliance/pii.py", "detect_pii", 13),
    ("src/hwpx_automation/office/compliance/pii.py", "mask_value", 14),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_build_3hak_ladder", 20),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_fill_2022_ladder_detailed", 14),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_fill_rubric_2022_ladder", 14),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_fill_rubric_ae_levels", 15),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_parse_subarea", 11),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_prune_header_empty_bullets", 11),
    ("src/hwpx_automation/office/evalplan/runtime.py", "_ratio_row_source", 14),
    ("src/hwpx_automation/office/evalplan/runtime.py", "fill_achievement", 13),
    ("src/hwpx_automation/office/evalplan/runtime.py", "fill_ratio", 15),
    ("src/hwpx_automation/office/evalplan/runtime.py", "fill_sections", 11),
    ("src/hwpx_automation/office/evalplan/runtime.py", "finalize_evalplan", 19),
    ("src/hwpx_automation/office/evalplan/runtime.py", "plan_structural_ops", 12),
    ("src/hwpx_automation/office/form_fill/classification.py", "_classify", 14),
    ("src/hwpx_automation/office/form_fill/fit/seal.py", "find_seal_anchor", 11),
    ("src/hwpx_automation/office/form_fill/fit/wordbox.py", "extract_glyph_boxes", 17),
    ("src/hwpx_automation/office/form_fill/fit/wordbox.py", "verify_form_fill", 11),
    ("src/hwpx_automation/office/form_fill/guidance.py", "to_markdown", 14),
    ("src/hwpx_automation/office/form_fill/quality.py", "detect_overflow_crossings", 11),
    ("src/hwpx_automation/office/form_fill/quality.py", "score_content", 18),
    ("src/hwpx_automation/office/form_fill/quality.py", "score_render", 12),
    ("src/hwpx_automation/office/form_fill/template_formfit.py", "_analyze_targets", 11),
    ("src/hwpx_automation/office/quality/page_guard.py", "collect_metrics", 13),
    ("src/hwpx_automation/office/quality/page_guard.py", "compare_metrics", 16),
    ("src/hwpx_automation/ops_services/form_fields.py", "apply_evalplan_fill", 12),
    ("src/hwpx_automation/ops_services/memo_style.py", "_split_run", 12),
    ("src/hwpx_automation/ops_services/preview_export.py", "render_preview", 16),
    ("src/hwpx_automation/ops_services/read_query.py", "analyze_template_structure", 13),
    ("src/hwpx_automation/ops_services/read_query.py", "find", 20),
    ("src/hwpx_automation/ops_services/read_query.py", "get_paragraphs", 11),
    ("src/hwpx_automation/ops_services/read_query.py", "read_text", 12),
    ("src/hwpx_automation/ops_services/save_policy.py", "_rotate_and_backup_exact", 12),
    ("src/hwpx_automation/ops_services/tables.py", "_auto_fit_table_columns", 16),
    ("src/hwpx_automation/ops_services/transactions.py", "_apply_transaction_operation", 20),
    ("src/hwpx_automation/ops_services/transactions.py", "byte_preserving_patch", 23),
    ("src/hwpx_automation/ops_services/transactions.py", "undo_last_edit", 20),
    ("src/hwpx_automation/runtime.py", "_classified_error_payload", 11),
    ("src/hwpx_automation/runtime.py", "_strict_call_tool_handler", 11),
    ("src/hwpx_automation/workflow/service.py", "continue_workflow", 22),
)



def _package_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        relative = path.relative_to(PACKAGE_ROOT)
        if path.name == "__init__.py":
            suffix = ".".join(relative.parent.parts)
        else:
            suffix = ".".join(relative.with_suffix("").parts)
        module = "hwpx_automation" + (f".{suffix}" if suffix else "")
        modules[module] = path
    return modules


def _package_import_graph() -> dict[str, set[str]]:
    modules = _package_modules()
    graph = {module: set() for module in modules}
    for module, path in modules.items():
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                else:
                    base = node.module or ""
                targets = [base]
                if node.module is None:
                    targets.extend(f"{base}.{alias.name}" for alias in node.names)
            graph[module].update(target for target in targets if target in modules)
    return graph


def _cyclic_components(graph: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[tuple[str, ...]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)
        for dependency in graph[module]:
            if dependency not in indices:
                visit(dependency)
                lowlinks[module] = min(lowlinks[module], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[dependency])
        if lowlinks[module] != indices[module]:
            return
        component: set[str] = set()
        while True:
            item = stack.pop()
            on_stack.remove(item)
            component.add(item)
            if item == module:
                break
        if len(component) > 1 or module in graph[module]:
            cycles.append(tuple(sorted(component)))

    for module in graph:
        if module not in indices:
            visit(module)
    return tuple(sorted(cycles))


def _line_counts(root: Path, names: tuple[str, ...]) -> dict[str, int]:
    return {
        name: len((root / name).read_text(encoding="utf-8").splitlines())
        for name in names
    }


def _private_accesses() -> tuple[tuple[str, str, str], ...]:
    accesses: list[tuple[str, str, str]] = []
    for root in (PACKAGE_ROOT, REPOSITORY_ROOT / "tests"):
        for path in root.rglob("*.py"):
            source_lines = path.read_text(encoding="utf-8").splitlines()
            tree = ast.parse("\n".join(source_lines), filename=str(path))
            for node in ast.walk(tree):
                marker: str | None = None
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in PRIVATE_ATTRIBUTES
                ):
                    marker = str(node.args[1].value)
                elif isinstance(node, ast.Attribute) and node.attr in PRIVATE_ATTRIBUTES:
                    marker = node.attr
                elif (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "request_handlers"
                ):
                    marker = "request_handlers"
                if marker is not None:
                    accesses.append(
                        (
                            path.relative_to(REPOSITORY_ROOT).as_posix(),
                            marker,
                            source_lines[node.lineno - 1].strip(),
                        )
                    )
    return tuple(sorted(accesses))


def _sdk_importers() -> tuple[str, ...]:
    """Package modules that import the ``mcp`` SDK (any form, any depth)."""

    importers: set[str] = set()
    for module, path in _package_modules().items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "mcp" or alias.name.startswith("mcp.")
                    for alias in node.names
                ):
                    importers.add(module)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                base = node.module or ""
                if base == "mcp" or base.startswith("mcp."):
                    importers.add(module)
    return tuple(sorted(importers))


def _c901_diagnostics() -> tuple[tuple[str, str, int], ...]:
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "C901", "--output-format", "json", *C901_PATHS],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"ruff C901 collection failed:\n{completed.stderr}")
    diagnostics = json.loads(completed.stdout or "[]")
    result: list[tuple[str, str, int]] = []
    for diagnostic in diagnostics:
        match = re.fullmatch(r"`([^`]+)` is too complex \((\d+) > \d+\)", diagnostic["message"])
        if match is None:
            raise RuntimeError(f"unexpected Ruff C901 message: {diagnostic['message']!r}")
        relative = Path(diagnostic["filename"]).resolve().relative_to(REPOSITORY_ROOT)
        result.append((relative.as_posix(), match.group(1), int(match.group(2))))
    return tuple(sorted(result))


EXPECTED_RATCHETS: dict[str, Any] = {
    "package_cycles": EXPECTED_PACKAGE_CYCLES,
    "sdk_importers": EXPECTED_SDK_IMPORTERS,
    "service_lines": EXPECTED_SERVICE_LINES,
    "facade_lines": EXPECTED_FACADE_LINES,
    "private_accesses": EXPECTED_PRIVATE_ACCESSES,
    "c901": EXPECTED_C901,
}


def capture_ratchets() -> dict[str, Any]:
    return {
        "package_cycles": _cyclic_components(_package_import_graph()),
        "sdk_importers": _sdk_importers(),
        "service_lines": _line_counts(
            SERVICES_ROOT, tuple(sorted(EXPECTED_SERVICE_LINES))
        ),
        "facade_lines": _line_counts(
            PACKAGE_ROOT, tuple(sorted(EXPECTED_FACADE_LINES))
        ),
        "private_accesses": _private_accesses(),
        "c901": _c901_diagnostics(),
    }


def assert_ratchets() -> None:
    actual = capture_ratchets()
    mismatches = {
        name: {"expected": EXPECTED_RATCHETS[name], "actual": actual[name]}
        for name in EXPECTED_RATCHETS
        if actual[name] != EXPECTED_RATCHETS[name]
    }
    if mismatches:
        raise RuntimeError("architecture ratchet drift:\n" + pformat(mismatches))


def main() -> int:
    try:
        assert_ratchets()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Architecture ratchets match the exact P3 baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
