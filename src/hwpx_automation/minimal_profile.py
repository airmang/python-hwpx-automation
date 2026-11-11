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

import hmac
import ipaddress
import json
from typing import Annotated, Any, cast

import mcp.types as mcp_types
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .office import compact

__all__ = [
    "MINIMAL_INSTRUCTIONS",
    "MINIMAL_TOOL_NAMES",
    "PROFILE_CHOICES",
    "TRANSPORT_CHOICES",
    "add_http_guard_argument",
    "add_profile_argument",
    "build_minimal_server",
    "checked_startup",
    "guarded_http_app",
    "served_for_profile",
]

#: Every profile the server can run. Anything else is refused at startup.
PROFILE_CHOICES = ("full", "minimal")

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
        choices=PROFILE_CHOICES,
        default=env_value("PROFILE", "full"),
        help=(
            "Tool surface: 'full' (the canonical tool contract) or 'minimal' "
            "(six coarse tools with short descriptions for small local models). "
            "Equivalent to HWPX_AUTOMATION_PROFILE."
        ),
    )


def served_for_profile(profile: str, full: FastMCP) -> FastMCP:
    """The server to run for *profile*: *full* itself, or a new minimal server."""

    if profile not in PROFILE_CHOICES:
        # argparse does not check a default taken from the environment, so an
        # unknown name must not fall through to the full tool surface.
        raise ValueError(
            f"unknown profile {profile!r}; expected one of: {', '.join(PROFILE_CHOICES)}"
        )
    if profile != "minimal":
        return full
    from . import __version__

    return build_minimal_server(__version__)


# --- Server start-up guards -------------------------------------------------

#: Every transport the server can run.
TRANSPORT_CHOICES = ("stdio", "streamable-http", "http")
_HTTP_TOKEN_ENV = "HTTP_TOKEN"
_ALLOW_UNAUTHENTICATED_HTTP_ENV = "ALLOW_UNAUTHENTICATED_HTTP"
_MIN_HTTP_TOKEN_LENGTH = 32


def _is_loopback_host(host: str) -> bool:
    """True only for a bind address that is reachable from this machine alone."""

    value = (host or "").strip().strip("[]").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


class _BearerTokenGate:
    """ASGI wrapper that answers 401 unless the request carries the token."""

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode("utf-8")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        supplied = b""
        for name, value in scope.get("headers") or ():
            if name.lower() == b"authorization":
                supplied = value
                break
        if hmac.compare_digest(supplied, self._expected):
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})


def add_http_guard_argument(parser: Any) -> None:
    """The explicit opt-in for unauthenticated HTTP on a non-loopback address."""

    from .configuration import env_value

    parser.add_argument(
        "--allow-unauthenticated-http",
        action="store_true",
        default=(env_value(_ALLOW_UNAUTHENTICATED_HTTP_ENV, "") or "").strip().lower()
        in {"1", "true", "yes"},
        help=(
            "Serve HTTP on a non-loopback address without a token. Only for a "
            "network that is already trusted. Equivalent to "
            "HWPX_AUTOMATION_ALLOW_UNAUTHENTICATED_HTTP=1."
        ),
    )


def checked_startup(parser: Any, args: Any) -> str | None:
    """Validate the parsed start-up options; return the HTTP token, if any.

    argparse validates values typed on the command line but not defaults read
    from the environment, so profile and transport are checked again here.
    """

    from .configuration import env_value

    if args.profile not in PROFILE_CHOICES:
        parser.error(
            f"unknown profile {args.profile!r}; expected one of: {', '.join(PROFILE_CHOICES)}"
        )
    if args.transport not in TRANSPORT_CHOICES:
        parser.error(
            f"unknown transport {args.transport!r}; expected one of: "
            f"{', '.join(TRANSPORT_CHOICES)}"
        )
    if args.transport == "stdio":
        return None
    token = env_value(_HTTP_TOKEN_ENV)
    if token is not None and len(token) < _MIN_HTTP_TOKEN_LENGTH:
        parser.error(
            f"HWPX_AUTOMATION_{_HTTP_TOKEN_ENV} must be at least "
            f"{_MIN_HTTP_TOKEN_LENGTH} characters"
        )
    if (
        not _is_loopback_host(args.host)
        and not token
        and not args.allow_unauthenticated_http
    ):
        parser.error(
            f"refusing to serve HTTP on {args.host!r} without authentication. "
            f"Bind to 127.0.0.1, set HWPX_AUTOMATION_{_HTTP_TOKEN_ENV} to a "
            "long random secret (clients then send 'Authorization: Bearer "
            "<token>'), or pass --allow-unauthenticated-http on a trusted network."
        )
    return token or None


def guarded_http_app(app: Any, token: str | None) -> Any:
    """Wrap *app* so every request must carry *token*; unchanged without one."""

    return _BearerTokenGate(app, token) if token else app
