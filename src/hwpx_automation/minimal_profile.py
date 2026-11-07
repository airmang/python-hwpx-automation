# SPDX-License-Identifier: Apache-2.0
"""The ``minimal`` MCP profile: six coarse tools for small local models.

``hwpx-automation-mcp --profile minimal`` (or ``HWPX_AUTOMATION_PROFILE=minimal``)
serves these instead of the canonical tool contract. Descriptions are short,
results are compact JSON, no result carries the document body, and no tool
needs a long argument: a long Markdown body is staged in chunks with
``stage_text`` and handed to ``create_from_markdown`` by its draft id.

This profile is a separate surface with its own frozen contract
(:data:`MINIMAL_TOOL_NAMES`); it does not change the canonical tool contract
or its hash. The operations are :mod:`hwpx_automation.office.compact`.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

import mcp.types as mcp_types
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .office import compact

__all__ = [
    "MINIMAL_INSTRUCTIONS",
    "MINIMAL_TOOL_NAMES",
    "add_profile_argument",
    "build_minimal_server",
    "served_for_profile",
]

#: The profile's frozen contract, in registration order.
MINIMAL_TOOL_NAMES = (
    "read_outline",
    "apply_text_changes",
    "replace_text",
    "stage_text",
    "create_from_markdown",
    "validate_document",
)

MINIMAL_INSTRUCTIONS = (
    "HWPX (한글) documents. Edit: read_outline → apply_text_changes with {id: new text}. "
    "New document: stage_text in chunks of at most 1000 characters (pass the draftId back "
    "to append), then create_from_markdown(draft_id, output). Never paste a long body into "
    "one call. Report only the output path the tool returns."
)


def _compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_minimal_server(package_version: str) -> FastMCP:
    """A FastMCP server exposing only :data:`MINIMAL_TOOL_NAMES`."""

    from .fastmcp_adapter import configure_runtime

    server = FastMCP("python-hwpx-automation-minimal", instructions=MINIMAL_INSTRUCTIONS)

    @server.tool(description="Short id-tagged list of the document's paragraphs and table cells. If complete is false, call again with after=nextAfter.")
    def read_outline(
        path: str,
        max_chars: Annotated[int, Field(ge=500, le=50_000)] = 6000,
        after: str | None = None,
    ) -> dict[str, Any]:
        return compact.read_outline(path, max_chars=max_chars, after=after)

    @server.tool(description="Replace paragraph text by id ({id: new text}); formatting kept. Saves to output (default <name>.edited.hwpx). overflow lists cells the new text may not fit.")
    def apply_text_changes(path: str, changes: dict[str, str], output: str | None = None) -> dict[str, Any]:
        return compact.apply_text_changes(path, changes, output=output)

    @server.tool(description="Replace every occurrence of old with new (body, tables, headers, footers). Saves to output (default <name>.edited.hwpx).")
    def replace_text(path: str, old: str, new: str, output: str | None = None) -> dict[str, Any]:
        return compact.replace_text(path, old, new, output=output)

    @server.tool(description="Store text for a later call and return its draftId. Send long text in chunks of at most 1000 characters: pass the draftId back to append.")
    def stage_text(text: str, draft_id: str | None = None) -> dict[str, Any]:
        return compact.stage_text(text, draft_id)

    @server.tool(description="Make a new .hwpx from Markdown (# headings, lists, | tables |, **bold**). Give draft_id from stage_text, or markdown_path of a workspace file.")
    def create_from_markdown(
        output: str,
        draft_id: str | None = None,
        markdown_path: str | None = None,
        markdown: Annotated[str | None, Field(max_length=2000)] = None,
    ) -> dict[str, Any]:
        return compact.create_from_markdown(
            output, draft_id=draft_id, markdown_path=markdown_path, markdown=markdown
        )

    @server.tool(description="Check that a .hwpx opens, reopens after saving and is safe for the Hancom editor.")
    def validate_document(path: str) -> dict[str, Any]:
        return compact.validate_document(path)

    async def call_tool(req: mcp_types.CallToolRequest) -> mcp_types.ServerResult:
        try:
            result = await server.call_tool(req.params.name, req.params.arguments or {})
        except Exception as exc:  # FastMCP wraps the tool's exception in ToolError
            payload = {"ok": False, "error": {"code": "TOOL_FAILED", "message": str(exc)}}
            return mcp_types.ServerResult(
                mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text=_compact(payload))],
                    structuredContent=payload,
                    isError=True,
                )
            )
        structured: Any = result[1] if isinstance(result, tuple) and len(result) == 2 else result
        if isinstance(structured, dict) and set(structured) == {"result"}:
            structured = structured["result"]
        if not isinstance(structured, dict):  # pragma: no cover - every tool returns a dict
            structured = {"ok": True, "result": structured}
        return mcp_types.ServerResult(
            mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=_compact(structured))],
                structuredContent=cast(dict[str, Any], structured),
                isError=structured.get("ok") is False,
            )
        )

    configure_runtime(server, package_version, call_tool)
    return server


def add_profile_argument(parser: Any) -> None:
    """The server CLI's ``--profile`` option (``HWPX_AUTOMATION_PROFILE``)."""

    from .configuration import env_value

    parser.add_argument(
        "--profile",
        choices=("full", "minimal"),
        default=env_value("PROFILE", "full"),
        help=(
            "Tool surface: 'full' (the canonical tool contract) or 'minimal' "
            "(six coarse tools with short descriptions for small local models). "
            "Equivalent to HWPX_AUTOMATION_PROFILE."
        ),
    )


def served_for_profile(profile: str, full: FastMCP) -> FastMCP:
    """The server to run for *profile*: *full* itself, or a new minimal server."""

    if profile != "minimal":
        return full
    from . import __version__

    return build_minimal_server(__version__)
