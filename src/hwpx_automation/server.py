# SPDX-License-Identifier: Apache-2.0
"""Stable FastMCP import and CLI facade over cohesive handler owners."""

from __future__ import annotations

import argparse
import json
import os

from .configuration import env_int, env_value
from .handlers import _shared, authoring, quality_render, read_export, specialized
from . import quality as _quality_contract
from .hwpx_ops import HwpxOps
from .minimal_profile import add_profile_argument, served_for_profile
from . import runtime as _runtime
from .runtime_services import RUNTIME_SERVICES
from .storage import LocalDocumentStorage
from .tool_bindings import TOOL_BINDINGS
from .workspace import (
    WORKSPACE_ROOTS_ENV,
    WorkspaceConfigurationError,
)


_runtime.refresh_runtime_for_environment()
ACTIVE_ADVANCED = _runtime.ACTIVE_ADVANCED
TOOL_REGISTRY = _runtime.TOOL_REGISTRY
_strict_call_tool_handler = _runtime._strict_call_tool_handler
mcp = _runtime.mcp
quality_contract = _quality_contract
save_doc = _shared.save_doc
build_hwpx_verification_report = _shared.build_hwpx_verification_report
_save_generated_document = authoring._save_generated_document
resolve_oracle = specialized.resolve_oracle
measure_question_splits = specialized.measure_question_splits
render_glyph_boxes = specialized.render_glyph_boxes
extract_image_boxes = specialized.extract_image_boxes
RemoteRenderClientV2 = _shared.RemoteRenderClientV2


# Explicit stable re-exports.  These are the exact objects in TOOL_BINDINGS.
get_document_node = TOOL_BINDINGS["get_document_node"]
query_document_nodes = TOOL_BINDINGS["query_document_nodes"]
apply_document_commands = TOOL_BINDINGS["apply_document_commands"]
dump_document_blueprint = TOOL_BINDINGS["dump_document_blueprint"]
replay_document_blueprint = TOOL_BINDINGS["replay_document_blueprint"]
get_document_text = TOOL_BINDINGS["get_document_text"]
get_document_info = TOOL_BINDINGS["get_document_info"]
get_document_outline = TOOL_BINDINGS["get_document_outline"]
get_document_map = TOOL_BINDINGS["get_document_map"]
get_paragraph_text = TOOL_BINDINGS["get_paragraph_text"]
get_paragraphs_text = TOOL_BINDINGS["get_paragraphs_text"]
get_location_text = TOOL_BINDINGS["get_location_text"]
get_table_text = TOOL_BINDINGS["get_table_text"]
get_table_map = TOOL_BINDINGS["get_table_map"]
find_text = TOOL_BINDINGS["find_text"]
list_available_documents = TOOL_BINDINGS["list_available_documents"]
hwpx_to_markdown = TOOL_BINDINGS["hwpx_to_markdown"]
document_to_markdown = TOOL_BINDINGS["document_to_markdown"]
hwpx_to_html = TOOL_BINDINGS["hwpx_to_html"]
hwpx_extract_json = TOOL_BINDINGS["hwpx_extract_json"]
document_extract_json = TOOL_BINDINGS["document_extract_json"]
package_parts = TOOL_BINDINGS["package_parts"]
package_get_text = TOOL_BINDINGS["package_get_text"]
package_get_xml = TOOL_BINDINGS["package_get_xml"]
object_find_by_attr = TOOL_BINDINGS["object_find_by_attr"]
object_find_by_tag = TOOL_BINDINGS["object_find_by_tag"]
create_document = TOOL_BINDINGS["create_document"]
create_document_from_plan = TOOL_BINDINGS["create_document_from_plan"]
copy_document = TOOL_BINDINGS["copy_document"]
create_government_report_document = TOOL_BINDINGS["create_government_report_document"]
create_proposal_document = TOOL_BINDINGS["create_proposal_document"]
create_comparison_table_document = TOOL_BINDINGS["create_comparison_table_document"]
get_document_plan_schema = TOOL_BINDINGS["get_document_plan_schema"]
validate_document_plan = TOOL_BINDINGS["validate_document_plan"]
analyze_document_plan = TOOL_BINDINGS["analyze_document_plan"]
markdown_to_document_plan = TOOL_BINDINGS["markdown_to_document_plan"]
parse_government_report_text = TOOL_BINDINGS["parse_government_report_text"]
compute_report_value = TOOL_BINDINGS["compute_report_value"]
register_template = TOOL_BINDINGS["register_template"]
list_templates = TOOL_BINDINGS["list_templates"]
describe_template = TOOL_BINDINGS["describe_template"]
add_heading = TOOL_BINDINGS["add_heading"]
add_paragraph = TOOL_BINDINGS["add_paragraph"]
add_equation = TOOL_BINDINGS["add_equation"]
add_chart = TOOL_BINDINGS["add_chart"]
insert_paragraph = TOOL_BINDINGS["insert_paragraph"]
delete_paragraph = TOOL_BINDINGS["delete_paragraph"]
add_page_break = TOOL_BINDINGS["add_page_break"]
apply_edits = TOOL_BINDINGS["apply_edits"]
undo_last_edit = TOOL_BINDINGS["undo_last_edit"]
replace_by_anchor = TOOL_BINDINGS["replace_by_anchor"]
replace_in_paragraph = TOOL_BINDINGS["replace_in_paragraph"]
search_and_replace = TOOL_BINDINGS["search_and_replace"]
batch_replace = TOOL_BINDINGS["batch_replace"]
byte_preserving_patch = TOOL_BINDINGS["byte_preserving_patch"]
insert_picture = TOOL_BINDINGS["insert_picture"]
replace_picture = TOOL_BINDINGS["replace_picture"]
add_table = TOOL_BINDINGS["add_table"]
set_table_cell_text = TOOL_BINDINGS["set_table_cell_text"]
merge_table_cells = TOOL_BINDINGS["merge_table_cells"]
split_table_cell = TOOL_BINDINGS["split_table_cell"]
format_table = TOOL_BINDINGS["format_table"]
table_compute = TOOL_BINDINGS["table_compute"]
list_styles = TOOL_BINDINGS["list_styles"]
create_custom_style = TOOL_BINDINGS["create_custom_style"]
set_paragraph_format = TOOL_BINDINGS["set_paragraph_format"]
set_list_format = TOOL_BINDINGS["set_list_format"]
format_text = TOOL_BINDINGS["format_text"]
extract_style_profile = TOOL_BINDINGS["extract_style_profile"]
apply_style_profile_to_plan = TOOL_BINDINGS["apply_style_profile_to_plan"]
compare_style_profiles = TOOL_BINDINGS["compare_style_profiles"]
set_page_setup = TOOL_BINDINGS["set_page_setup"]
set_header_footer = TOOL_BINDINGS["set_header_footer"]
set_page_number = TOOL_BINDINGS["set_page_number"]
add_toc = TOOL_BINDINGS["add_toc"]
add_cross_reference = TOOL_BINDINGS["add_cross_reference"]
verify_toc = TOOL_BINDINGS["verify_toc"]
add_memo = TOOL_BINDINGS["add_memo"]
add_memo_by_anchor = TOOL_BINDINGS["add_memo_by_anchor"]
remove_memo = TOOL_BINDINGS["remove_memo"]
scan_form_guidance = TOOL_BINDINGS["scan_form_guidance"]
apply_table_ops = TOOL_BINDINGS["apply_table_ops"]
run_edit_plan = TOOL_BINDINGS["run_edit_plan"]
apply_body_ops = TOOL_BINDINGS["apply_body_ops"]
inspect_fill_residue = TOOL_BINDINGS["inspect_fill_residue"]
verify_form_fill = TOOL_BINDINGS["verify_form_fill"]
list_form_fields = TOOL_BINDINGS["list_form_fields"]
add_form_field = TOOL_BINDINGS["add_form_field"]
fill_form_field = TOOL_BINDINGS["fill_form_field"]
find_cell_by_label = TOOL_BINDINGS["find_cell_by_label"]
fill_by_path = TOOL_BINDINGS["fill_by_path"]
analyze_form_fill = TOOL_BINDINGS["analyze_form_fill"]
apply_form_fill = TOOL_BINDINGS["apply_form_fill"]
analyze_template_formfit = TOOL_BINDINGS["analyze_template_formfit"]
apply_template_formfit = TOOL_BINDINGS["apply_template_formfit"]
apply_evalplan_fill = TOOL_BINDINGS["apply_evalplan_fill"]
score_form_fill = TOOL_BINDINGS["score_form_fill"]
add_tracked_edit = TOOL_BINDINGS["add_tracked_edit"]
scan_personal_info = TOOL_BINDINGS["scan_personal_info"]
compose_exam = TOOL_BINDINGS["compose_exam"]
verify_question_splits = TOOL_BINDINGS["verify_question_splits"]
place_seal = TOOL_BINDINGS["place_seal"]
check_seal_compliance = TOOL_BINDINGS["check_seal_compliance"]
mail_merge = TOOL_BINDINGS["mail_merge"]
add_boxed_org_chart = TOOL_BINDINGS["add_boxed_org_chart"]
compose_section_chip = TOOL_BINDINGS["compose_section_chip"]
compose_official_draft = TOOL_BINDINGS["compose_official_draft"]
compose_simple_draft = TOOL_BINDINGS["compose_simple_draft"]
get_genre_grammar = TOOL_BINDINGS["get_genre_grammar"]
inspect_mail_merge_placeholders = TOOL_BINDINGS["inspect_mail_merge_placeholders"]
build_image_grid = TOOL_BINDINGS["build_image_grid"]
build_meeting_nameplates = TOOL_BINDINGS["build_meeting_nameplates"]
build_organization_chart = TOOL_BINDINGS["build_organization_chart"]
render_submit = TOOL_BINDINGS["render_submit"]
render_status = TOOL_BINDINGS["render_status"]
render_cancel = TOOL_BINDINGS["render_cancel"]
render_health = TOOL_BINDINGS["render_health"]
render_preview = TOOL_BINDINGS["render_preview"]
repair_hwpx = TOOL_BINDINGS["repair_hwpx"]
mcp_server_health = TOOL_BINDINGS["mcp_server_health"]
describe_capabilities = TOOL_BINDINGS["describe_capabilities"]
doc_diff = TOOL_BINDINGS["doc_diff"]
validate_structure = TOOL_BINDINGS["validate_structure"]
lint_text_conventions = TOOL_BINDINGS["lint_text_conventions"]
inspect_document_quality = TOOL_BINDINGS["inspect_document_quality"]
inspect_document_authoring_quality = TOOL_BINDINGS["inspect_document_authoring_quality"]
inspect_operating_plan_quality = TOOL_BINDINGS["inspect_operating_plan_quality"]
inspect_official_document_style = TOOL_BINDINGS["inspect_official_document_style"]
inspect_reference_consistency = TOOL_BINDINGS["inspect_reference_consistency"]
start_workflow = TOOL_BINDINGS["start_workflow"]
get_workflow = TOOL_BINDINGS["get_workflow"]
get_workflow_result = TOOL_BINDINGS["get_workflow_result"]
continue_workflow = TOOL_BINDINGS["continue_workflow"]
approve_workflow_decision = TOOL_BINDINGS["approve_workflow_decision"]
cancel_workflow = TOOL_BINDINGS["cancel_workflow"]
resume_workflow = TOOL_BINDINGS["resume_workflow"]

_SERVER_TOOL_BINDINGS = TOOL_BINDINGS
_TOOL_REGISTRY = TOOL_REGISTRY
_ACTIVE_ADVANCED = ACTIVE_ADVANCED
_OPS = RUNTIME_SERVICES.ops
_fastmcp_tool_names = quality_render._fastmcp_tool_names
_render_client = quality_render._render_client
_table_count = read_export._table_count


def _replace_ops(ops: HwpxOps) -> None:
    global _OPS
    RUNTIME_SERVICES.replace_ops(ops)
    _OPS = ops


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hwpx-automation-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "http"),
        default=env_value("TRANSPORT", "stdio"),
        help="MCP transport to use",
    )
    parser.add_argument(
        "--host",
        default=env_value("HOST", "127.0.0.1"),
        help="Host interface for streamable HTTP transport",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=max(1, env_int("PORT", 8000)),
        help="TCP port for streamable HTTP transport",
    )
    add_profile_argument(parser)
    parser.add_argument(
        "--workspace-root",
        action="append",
        default=None,
        help=(
            "Authorized local workspace root. Repeat for multiple roots; relative paths use the first. "
            f"Equivalent to {WORKSPACE_ROOTS_ENV}."
        ),
    )
    args = parser.parse_args(argv)

    if args.workspace_root:
        os.environ[WORKSPACE_ROOTS_ENV] = json.dumps(args.workspace_root)
    try:
        storage = LocalDocumentStorage(auto_backup=False)
    except WorkspaceConfigurationError as exc:
        # Explicit HWPX_AUTOMATION_WORKSPACE_ROOTS (or its supported 6.x
        # HWPX_MCP_WORKSPACE_ROOTS fallback) / --workspace-root configuration is
        # invalid: fail fast so the operator fixes the value. An unconfigured
        # degenerate cwd instead defers inside LocalDocumentStorage so the server
        # still boots and every document tool call reports WORKSPACE_ROOT_INVALID.
        parser.error(
            f"invalid HWPX workspace configuration: {exc}. "
            f"Set {WORKSPACE_ROOTS_ENV} to existing project directories or launch from the project workspace."
        )
    _replace_ops(HwpxOps(storage=storage))

    served = served_for_profile(args.profile, mcp)
    selected_transport = args.transport
    if selected_transport == "http":
        selected_transport = "streamable-http"

    if selected_transport == "stdio":
        served.run(transport="stdio")
        return

    # TODO: add pluggable auth middleware/headers for production HTTP deployments.
    try:  # HTTP transport is an optional [http] extra
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "HTTP transport requires the 'uvicorn' package. Install it with: "
            "pip install 'python-hwpx-automation[http]' "
            "(or 'hwpx-mcp-server[http]', or pip install uvicorn). "
            "The default stdio transport needs no extra."
        ) from exc

    app = served.streamable_http_app()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
