from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.ops_services.content_layout import ContentLayoutService
from hwpx_automation.ops_services.context import DocumentContext
from hwpx_automation.ops_services.form_fields import FormFieldService
from hwpx_automation.ops_services.media import MediaService
from hwpx_automation.ops_services.memo_style import MemoStyleService
from hwpx_automation.ops_services.package_validation import PackageValidationService
from hwpx_automation.ops_services.planning import PlanningService
from hwpx_automation.ops_services.preview_export import PreviewExportService
from hwpx_automation.ops_services.read_query import ReadQueryService
from hwpx_automation.ops_services.save_policy import SavePolicy
from hwpx_automation.ops_services.tables import TableService
from hwpx_automation.ops_services.transactions import TransactionService


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "hwpx_automation"
FACADE_PATH = SOURCE_ROOT / "hwpx_ops.py"
SERVICES_ROOT = SOURCE_ROOT / "ops_services"

OWNER_METHODS = {
    "context": (
        "_new_error",
        "_resolve_path",
        "_make_handle_id",
        "_register_handle",
        "list_registered_handles",
        "open_document_handle",
        "list_open_documents",
        "close_document_handle",
        "get_registered_handle",
        "resolve_document_path",
        "_resolve_output_path",
        "_relative_path",
        "_open_document",
        "_read_only_hwp_paragraphs",
        "_iter_paragraphs",
        "_iter_tables",
    ),
    "save": (
        "_ensure_backup",
        "_maybe_backup",
        "_save_document",
        "_save_transaction_document",
        "_report_for_bytes",
        "_semantic_diff_bytes",
        "_capture_exact_sidecar_guard",
        "_absent_publication_guard",
        "_assert_exact_sidecar_publication",
        "_publish_exact_recovery",
        "_preserve_exact_preimages",
        "_cleanup_exact_recoveries",
        "_republish_exact_recoveries",
        "_rotate_and_backup_exact",
        "_rollback_exact_backup_mutations",
        "_write_patched",
        "save",
        "save_as",
        "fill_template",
        "make_blank",
    ),
    "transactions": (
        "_with_transaction_verification",
        "_operation_value",
        "_apply_transaction_operation",
        "apply_edits",
        "undo_last_edit",
        "byte_preserving_patch",
    ),
    "read_query": (
        "get_metadata_by_handle",
        "get_paragraphs_by_handle",
        "get_tables_by_handle",
        "open_info",
        "list_sections",
        "list_headers",
        "read_text",
        "get_paragraphs",
        "text_extract_report",
        "analyze_template_structure",
        "find",
        "object_find_by_tag",
        "object_find_by_attr",
    ),
    "content_layout": (
        "replace_text_in_runs",
        "add_paragraph",
        "add_equation",
        "add_chart",
        "insert_paragraphs_bulk",
        "set_paragraph_format",
        "set_page_setup",
        "_header_footer_payload",
        "set_header_footer",
        "set_page_number",
        "set_list_format",
    ),
    "tables": (
        "_auto_fit_table_columns",
        "_ensure_table_border_fill",
        "add_table",
        "set_table_border_fill",
        "get_table_cell_map",
        "set_table_cell_text",
        "replace_table_region",
        "split_table_cell",
        "copy_table_between_documents",
    ),
    "form_fields": (
        "list_form_fields",
        "add_form_field",
        "fill_form_field",
        "apply_table_ops",
        "run_edit_plan",
        "verify_form_fill",
        "score_form_fill",
        "apply_body_ops",
        "inspect_fill_residue",
        "scan_form_guidance",
        "apply_evalplan_fill",
    ),
    "media": (
        "_decode_image_base64",
        "_id_integrity_payload",
        "insert_picture",
        "replace_picture",
    ),
    "memo_style": (
        "_normalize_color",
        "_ensure_char_style",
        "find_runs_by_style",
        "add_memo_with_anchor",
        "set_memo_shape",
        "remove_memo",
        "_find_memo",
        "ensure_run_style",
        "list_styles_and_bullets",
        "apply_style_to_text_ranges",
        "apply_style_to_paragraphs",
    ),
    "preview_export": (
        "export_text",
        "export_html",
        "export_markdown",
        "_preview_output_dir",
        "_embed_screenshot_image",
        "_capture_preview_pages",
        "render_preview",
        "convert_hwp_to_hwpx",
    ),
    "package_validation": (
        "package_parts",
        "package_get_text",
        "repair_hwpx",
        "list_master_pages_histories_versions",
        "validate_structure",
        "lint_text_conventions",
        "package_get_xml",
    ),
    "planning": (
        "plan_manager",
        "_ensure_planner_document",
        "plan_edit",
        "preview_edit",
        "apply_edit",
        "search",
        "get_context",
    ),
}

OWNER_CLASSES = {
    "context": DocumentContext,
    "save": SavePolicy,
    "transactions": TransactionService,
    "read_query": ReadQueryService,
    "content_layout": ContentLayoutService,
    "tables": TableService,
    "form_fields": FormFieldService,
    "media": MediaService,
    "memo_style": MemoStyleService,
    "preview_export": PreviewExportService,
    "package_validation": PackageValidationService,
    "planning": PlanningService,
}

STATIC_SAVE_DELEGATES = {
    "_report_for_bytes",
    "_semantic_diff_bytes",
    "_absent_publication_guard",
}


def _facade_methods() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))
    facade = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HwpxOps"
    )
    return {
        node.name: node for node in facade.body if isinstance(node, ast.FunctionDef)
    }


def _single_return_expression(method: ast.FunctionDef) -> str:
    statements = [
        node
        for node in method.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    assert len(statements) == 1, method.name
    assert isinstance(statements[0], ast.Return), method.name
    assert statements[0].value is not None, method.name
    return ast.unparse(statements[0].value)


def test_facade_has_one_explicit_delegate_for_every_baselined_method() -> None:
    methods = _facade_methods()
    owned = {
        method_name: owner
        for owner, method_names in OWNER_METHODS.items()
        for method_name in method_names
    }

    assert len(OWNER_METHODS) == 12
    assert len(owned) == 123  # 8.0: -add_memo, -attach_memo_field, -add_shape, -add_control, +set_memo_shape
    assert set(methods) == {"__init__", *owned}
    assert sum(not name.startswith("_") for name in methods) == 82

    for method_name, owner in owned.items():
        expression = _single_return_expression(methods[method_name])
        if method_name == "_new_error":
            expected = "cast(HwpxOperationError, self._services.context._new_error("
        elif method_name == "plan_manager":
            expected = "self._services.planning.plan_manager"
        elif method_name in STATIC_SAVE_DELEGATES:
            expected = f"SavePolicy.{method_name}("
        else:
            expected = f"self._services.{owner}.{method_name}("

        if expected.endswith("("):
            assert expression.startswith(expected), (method_name, expression)
        else:
            assert expression == expected, (method_name, expression)

        assert hasattr(OWNER_CLASSES[owner], method_name)


def test_service_composition_shares_context_and_policies_without_facade_backrefs(
    tmp_path: Path,
) -> None:
    ops = HwpxOps(base_directory=tmp_path)
    services = ops._services

    assert services.context is not ops
    assert services.save._context is services.context
    for owner in OWNER_METHODS:
        service = getattr(services, owner)
        assert service is not ops
        assert all(value is not ops for value in vars(service).values())
        if owner != "context":
            assert service._context is services.context
        if hasattr(service, "_save"):
            assert service._save is services.save


def test_services_are_bounded_concrete_classes_with_an_acyclic_import_graph() -> None:
    service_modules = {
        path.stem
        for path in SERVICES_ROOT.glob("*.py")
        if path.stem not in {"__init__", "composition", "_border_fill"}
    }
    assert service_modules == {
        "content_layout",
        "context",
        "form_fields",
        "media",
        "memo_style",
        "package_validation",
        "planning",
        "preview_export",
        "read_query",
        "save_policy",
        "tables",
        "transactions",
    }
    assert not (SERVICES_ROOT / "tracked_changes.py").exists()

    edges: dict[str, set[str]] = defaultdict(set)
    for module_name in service_modules | {"composition"}:
        tree = ast.parse(
            (SERVICES_ROOT / f"{module_name}.py").read_text(encoding="utf-8")
        )
        assert not any(
            isinstance(node, ast.FunctionDef) and node.name == "__getattr__"
            for node in ast.walk(tree)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {node.module or ""}
                if node.level == 1 and node.module in service_modules:
                    edges[module_name].add(node.module)
            else:
                continue
            assert not any(
                name == "hwpx_automation.server"
                or name == "hwpx_automation.hwpx_ops"
                or name.endswith(".server")
                or name.endswith(".hwpx_ops")
                for name in imported
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_name: str) -> None:
        assert module_name not in visiting, f"service import cycle at {module_name}"
        if module_name in visited:
            return
        visiting.add(module_name)
        for dependency in edges[module_name]:
            visit(dependency)
        visiting.remove(module_name)
        visited.add(module_name)

    for module_name in service_modules | {"composition"}:
        visit(module_name)

    for service_class in OWNER_CLASSES.values():
        assert service_class.__bases__ == (object,)


def test_hwpx_ops_graph_is_constructed_only_at_runtime_composition_boundaries() -> None:
    allowed = {"runtime_services.py", "server.py"}
    imports: set[str] = set()
    constructions: set[str] = set()

    for path in SOURCE_ROOT.rglob("*.py"):
        if path == FACADE_PATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "HwpxOps" for alias in node.names
            ):
                imports.add(relative)
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "HwpxOps":
                constructions.add(relative)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "HwpxOps":
                constructions.add(relative)

    assert imports <= allowed
    assert constructions <= allowed
    assert constructions == allowed


def test_facade_and_service_sizes_remain_bounded() -> None:
    facade_lines = len(FACADE_PATH.read_text(encoding="utf-8").splitlines())
    service_lines = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in SERVICES_ROOT.glob("*.py")
        if path.name not in {"__init__.py", "composition.py"}
    }

    assert facade_lines < 1_600
    assert service_lines
    assert max(service_lines.values()) < 750
