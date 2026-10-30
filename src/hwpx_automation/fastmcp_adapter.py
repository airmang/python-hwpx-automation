# SPDX-License-Identifier: Apache-2.0
"""Sole fail-closed FastMCP compatibility seam for the server runtime.

Ordinary registration stays on FastMCP's public API.  The SDK does not expose
public hooks for the initialize version, the raw ``CallToolRequest`` handler,
or callable-aware live registry snapshots, so those exact operations remain
isolated here.  Every other module and test consumes the project-owned APIs
below and never reaches into FastMCP implementation details.
"""

from __future__ import annotations

import copy
import functools
import inspect
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as distribution_version
from types import MappingProxyType
from typing import Annotated, Any, Awaitable, Callable, Mapping, cast, get_args, get_origin

import mcp.types as mcp_types
from mcp.server.fastmcp import FastMCP
from pydantic import TypeAdapter

from .execution_lock import PUBLIC_MUTATION_LOCK


# The package resolver pin and this audited allowlist MUST admit the same
# set: anything pip can install must also start. Admitting a new patch is an
# explicit re-audit (docs/mcp-sdk-reaudit.md) that updates both together.
SUPPORTED_MCP_RANGE = "==1.30.0"
AUDITED_MCP_PATCHES = ("1.30.0",)


class FastMcpAdapterError(RuntimeError):
    """FastMCP cannot provide the registry guarantees required by the server."""


@dataclass(frozen=True, slots=True)
class FastMcpToolSnapshot:
    name: str
    callable: Callable[..., Any]
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    meta: dict[str, Any]


StrictCallHandler = Callable[[mcp_types.CallToolRequest], Awaitable[Any]]


def _installed_mcp_version() -> str:
    try:
        return distribution_version("mcp")
    except PackageNotFoundError as exc:  # pragma: no cover - required dependency
        raise FastMcpAdapterError("the MCP SDK distribution is unavailable") from exc


def _require_audited_mcp_patch() -> str:
    installed = _installed_mcp_version()
    if installed not in AUDITED_MCP_PATCHES:
        audited = ", ".join(AUDITED_MCP_PATCHES)
        raise FastMcpAdapterError(
            f"unsupported MCP SDK {installed!r}; the package pins mcp"
            f"{SUPPORTED_MCP_RANGE} and only audited patches are admitted "
            f"({audited}) — see docs/mcp-sdk-reaudit.md"
        )
    return installed


def _low_level_runtime(mcp: Any) -> tuple[Any, dict[Any, Any]]:
    """Return the pinned low-level runtime shape or fail before mutation."""

    _require_audited_mcp_patch()
    runtime = getattr(mcp, "_mcp_server", None)
    if runtime is None or not hasattr(runtime, "version"):
        raise FastMcpAdapterError(
            "FastMCP low-level runtime/version hook is unavailable for the audited SDK"
        )
    request_handlers = getattr(runtime, "request_handlers", None)
    if not isinstance(request_handlers, dict):
        raise FastMcpAdapterError(
            "FastMCP request handler registry has an incompatible shape"
        )
    existing = request_handlers.get(mcp_types.CallToolRequest)
    if not callable(existing):
        raise FastMcpAdapterError(
            "FastMCP CallToolRequest handler is unavailable for the audited SDK"
        )
    return runtime, request_handlers


def configure_runtime(
    mcp: Any,
    package_version: str,
    strict_call_handler: StrictCallHandler,
) -> None:
    """Set initialize version and the strict raw call handler atomically.

    FastMCP 1.30.0 exposes neither operation through its public constructor or
    decorators.  Shape and audited-patch checks happen before mutation; any
    failed write restores the prior runtime state and raises the adapter-owned
    error type.
    """

    if not isinstance(package_version, str) or not package_version.strip():
        raise FastMcpAdapterError("package_version must be a non-empty string")
    if not callable(strict_call_handler):
        raise FastMcpAdapterError("strict_call_handler must be callable")

    runtime, request_handlers = _low_level_runtime(mcp)
    previous_version = runtime.version
    previous_handler = request_handlers[mcp_types.CallToolRequest]
    try:
        runtime.version = package_version
        request_handlers[mcp_types.CallToolRequest] = strict_call_handler
        if runtime.version != package_version:
            raise FastMcpAdapterError(
                "FastMCP did not retain the configured server version"
            )
        if request_handlers.get(mcp_types.CallToolRequest) is not strict_call_handler:
            raise FastMcpAdapterError("FastMCP did not retain the strict call handler")
    except Exception as exc:
        try:
            runtime.version = previous_version
            request_handlers[mcp_types.CallToolRequest] = previous_handler
        except Exception:
            pass
        if isinstance(exc, FastMcpAdapterError):
            raise
        raise FastMcpAdapterError(
            f"cannot configure the FastMCP runtime: {exc}"
        ) from exc


def runtime_server_version(mcp: Any) -> str:
    """Return the configured initialize version without exposing SDK internals."""

    runtime, _ = _low_level_runtime(mcp)
    configured = runtime.version
    if not isinstance(configured, str) or not configured:
        raise FastMcpAdapterError("FastMCP runtime has no configured server version")
    return configured


def normalize_schema(schema: Mapping[str, Any] | None, *, input_schema: bool) -> dict[str, Any]:
    """Return a deterministic JSON-compatible schema.

    Object inputs are closed at every generated object boundary unless their
    schema explicitly declares an open mapping. Array order is preserved so
    catalog-owned schemas remain byte-for-byte attributable to their source.
    MCP restricts both tool input and output schemas to an object at the root;
    Pydantic root-model unions need that discriminator restored explicitly.
    """

    def visit(value: Any) -> Any:
        if isinstance(value, Mapping):
            out = {str(key): visit(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
            # A ``properties`` member can itself be a user field name inside a
            # JSON Schema property map. Only explicit object-schema nodes are
            # eligible for generated closure defaults.
            if out.get("type") == "object":
                composed = any(
                    keyword in out for keyword in ("$ref", "allOf", "anyOf", "oneOf")
                )
                if "properties" in out or not composed:
                    out.setdefault("properties", {})
                    if "additionalProperties" not in out:
                        out["additionalProperties"] = (
                            False if out["properties"] else True
                        )
            return out
        if isinstance(value, (list, tuple)):
            return [visit(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise FastMcpAdapterError(f"schema contains non-JSON value: {type(value).__name__}")

    normalized = visit(dict(schema or {}))
    if not isinstance(normalized, dict):  # pragma: no cover - defensive
        raise FastMcpAdapterError("tool schema must be a JSON object")
    if input_schema:
        normalized.setdefault("type", "object")
        normalized.setdefault("properties", {})
        # A tool call is never an open mapping, including zero-argument tools.
        # Nested mapping values keep their explicitly generated openness.
        normalized["additionalProperties"] = False
        normalized.setdefault("required", [])
    else:
        root_type = normalized.get("type")
        if root_type not in (None, "object"):
            raise FastMcpAdapterError(
                f"MCP output schema root must be object, got {root_type!r}"
            )
        normalized.setdefault("type", "object")
        if len(normalized) == 1:
            normalized.update({"properties": {}, "additionalProperties": True})
    return normalized


def _resolved_annotations(func: Callable[..., Any]) -> dict[str, Any]:
    """Resolve annotations without Python 3.10's implicit Optional rewrite."""

    candidates: list[Callable[..., Any]] = []
    seen: set[int] = set()
    current = func
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        candidates.append(current)
        nested = getattr(current, "__hwpx_original_callable__", current)
        if nested is current:
            break
        current = nested
    for candidate in candidates:
        try:
            return dict(inspect.get_annotations(candidate, eval_str=True))
        except (NameError, TypeError, ValueError):
            continue
    for candidate in reversed(candidates):
        raw = getattr(candidate, "__annotations__", None)
        if isinstance(raw, Mapping):
            return dict(raw)
    return {}


def _resolved_return_annotation(func: Callable[..., Any]) -> Any:
    return _resolved_annotations(func).get(
        "return", inspect.signature(func).return_annotation
    )


def _annotation_schema_extra(annotation: Any) -> dict[str, Any]:
    """Collect mapping-valued Field.json_schema_extra without reordering it."""

    extras: dict[str, Any] = {}
    while get_origin(annotation) is Annotated:
        nested, *metadata = get_args(annotation)
        for item in metadata:
            extra = getattr(item, "json_schema_extra", None)
            if isinstance(extra, Mapping):
                extras.update(copy.deepcopy(dict(extra)))
        annotation = nested
    return extras


def _restore_parameter_schema_extras(
    schema: Mapping[str, Any] | None,
    func: Callable[..., Any],
) -> dict[str, Any]:
    """Restore catalog-owned schema fragments that Pydantic may reorder.

    Pydantic faithfully carries ``json_schema_extra`` into the generated
    schema, but it normalizes nested ``required`` arrays. The shared agent
    catalog is the canonical byte-level source, so overlay the original extras
    after generation before storing the FastMCP registry receipt.
    """

    restored = copy.deepcopy(dict(schema or {}))
    properties = restored.get("properties")
    if not isinstance(properties, dict):
        return restored
    hints = _resolved_annotations(func)
    for name, annotation in hints.items():
        if name == "return" or name not in properties:
            continue
        extra = _annotation_schema_extra(annotation)
        if extra and isinstance(properties[name], dict):
            properties[name].update(extra)
    top_level_extra = getattr(func, "__hwpx_input_schema_extra__", None)
    if isinstance(top_level_extra, Mapping):
        restored.update(copy.deepcopy(dict(top_level_extra)))
    return restored


def _normalize_implicit_none_parameters(
    schema: Mapping[str, Any] | None,
    func: Callable[..., Any],
) -> dict[str, Any]:
    """Remove Python-version-specific implicit nullability.

    A number of legacy callables use ``value: T = None`` without declaring
    ``T | None``. Pydantic emits different schemas for that invalid typing
    pattern on Python 3.10 and newer interpreters. The public contract follows
    the explicit annotation: omitted arguments may still receive their default,
    but an explicitly supplied JSON ``null`` is accepted only when the
    annotation itself includes ``None``. Catalog-owned schema extras are
    restored after this normalization and therefore remain authoritative.
    """

    normalized = copy.deepcopy(dict(schema or {}))
    properties = normalized.get("properties")
    if not isinstance(properties, dict):
        return normalized
    source = original_callable(func)
    try:
        # Unlike get_type_hints(), inspect.get_annotations() does not rewrite
        # ``T = None`` into Optional[T] on Python 3.10. That distinction is the
        # exact source declaration this normalization must preserve.
        hints = inspect.get_annotations(source, eval_str=True)
    except (NameError, TypeError, ValueError):
        hints = dict(getattr(source, "__annotations__", {}))
    try:
        signature = inspect.signature(source)
    except (TypeError, ValueError):  # pragma: no cover - binding checks first
        return normalized

    for name, parameter in signature.parameters.items():
        if parameter.default is not None or name not in properties:
            continue
        annotation = hints.get(name, parameter.annotation)
        while get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        annotation_args = get_args(annotation)
        if isinstance(annotation, str) and (
            "None" in annotation or "Optional" in annotation
        ):
            continue
        if (
            annotation is None
            or annotation is type(None)
            or None in annotation_args
            or type(None) in annotation_args
        ):
            continue
        property_schema = properties[name]
        if not isinstance(property_schema, dict):
            continue
        options = property_schema.get("anyOf")
        if not isinstance(options, list):
            continue
        retained = [
            option
            for option in options
            if not (isinstance(option, Mapping) and option.get("type") == "null")
        ]
        if len(retained) == len(options) or not retained:
            continue
        siblings = {
            key: value for key, value in property_schema.items() if key != "anyOf"
        }
        if len(retained) == 1 and isinstance(retained[0], Mapping):
            properties[name] = {**copy.deepcopy(dict(retained[0])), **siblings}
        else:
            properties[name] = {**siblings, "anyOf": retained}
    return normalize_schema(normalized, input_schema=True)


def _registration_callable(func: Callable[..., Any]) -> tuple[Callable[..., Any], bool]:
    """Normalize bare ``dict`` returns for structured output without altering API functions."""

    # Annotated metadata is contract-critical: the core agent catalog binds its
    # closed command/blueprint schemas through Field(json_schema_extra=...).
    resolved_hints = _resolved_annotations(func)
    return_annotation = resolved_hints.get("return", inspect.signature(func).return_annotation)
    call_result, call_result_model = _call_tool_result_output_model(return_annotation)
    if call_result:
        if call_result_model is None:
            raise FastMcpAdapterError(
                "CallToolResult returns require Annotated[CallToolResult, OutputModel] "
                "so outputSchema validates structuredContent"
            )
        return func, True
    if return_annotation is not dict:
        return func, return_annotation is not inspect.Signature.empty and return_annotation is not Any

    @functools.wraps(func)
    def structured_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return func(*args, **kwargs)

    original_signature = inspect.signature(func)
    structured_wrapper.__signature__ = original_signature.replace(  # type: ignore[attr-defined]
        parameters=[
            parameter.replace(annotation=resolved_hints.get(parameter.name, parameter.annotation))
            for parameter in original_signature.parameters.values()
        ],
        return_annotation=dict[str, Any],
    )
    structured_wrapper.__annotations__ = {
        **resolved_hints,
        "return": dict[str, Any],
    }
    setattr(structured_wrapper, "__hwpx_original_callable__", func)
    return structured_wrapper, True


def _call_tool_result_output_model(annotation: Any) -> tuple[bool, Any | None]:
    """Return whether *annotation* is CallToolResult and its owned output model."""

    metadata: tuple[Any, ...] = ()
    base = annotation
    if get_origin(annotation) is Annotated:
        base, *nested_metadata = get_args(annotation)
        metadata = tuple(nested_metadata)
    try:
        is_call_result = isinstance(base, type) and issubclass(
            base, mcp_types.CallToolResult
        )
    except TypeError:  # pragma: no cover - defensive for exotic annotations
        is_call_result = False
    return is_call_result, metadata[0] if is_call_result and metadata else None


def _serialize_mutation_callable(
    func: Callable[..., Any],
    *,
    mutates: bool,
) -> Callable[..., Any]:
    """Serialize catalog-declared writers without changing their tool schema."""

    if not mutates:
        return func

    @functools.wraps(func)
    def serialized(*args: Any, **kwargs: Any) -> Any:
        with PUBLIC_MUTATION_LOCK:
            return func(*args, **kwargs)

    # The public server module uses postponed annotations.  A wrapper defined
    # in this adapter has a different globals namespace, so copying annotation
    # strings verbatim makes FastMCP try to resolve e.g. ``mcp_types`` here and
    # can incorrectly treat CallToolResult as structured output.  Bind the
    # already-resolved objects onto both the signature and annotations.
    resolved_hints = _resolved_annotations(func)
    original_signature = inspect.signature(func)
    serialized.__signature__ = original_signature.replace(  # type: ignore[attr-defined]
        parameters=[
            parameter.replace(
                annotation=resolved_hints.get(parameter.name, parameter.annotation)
            )
            for parameter in original_signature.parameters.values()
        ],
        return_annotation=resolved_hints.get(
            "return", original_signature.return_annotation
        ),
    )
    serialized.__annotations__ = resolved_hints
    setattr(serialized, "__hwpx_original_callable__", original_callable(func))
    return serialized


def original_callable(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return the public server function behind an adapter-generated wrapper."""

    seen: set[int] = set()
    current = func
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        nested = getattr(current, "__hwpx_original_callable__", current)
        if nested is current:
            return current
        current = nested
    return current


def _manager_tools(mcp: Any) -> dict[str, Any]:
    _require_audited_mcp_patch()
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if manager is None or not isinstance(tools, dict):
        raise FastMcpAdapterError(
            "FastMCP tool manager is unavailable; supported registry introspection is required"
        )
    return tools


def _register(
    mcp: Any,
    *,
    name: str,
    func: Callable[..., Any],
    description: str,
    meta: Mapping[str, Any],
) -> FastMcpToolSnapshot:
    _require_audited_mcp_patch()
    adapted, structured_output = _registration_callable(func)
    adapted = _serialize_mutation_callable(
        adapted,
        mutates=bool(meta.get("hwpxMutates")),
    )
    tool_method = getattr(mcp, "tool", None)
    if not callable(tool_method):
        raise FastMcpAdapterError("FastMCP.tool is unavailable")
    try:
        parameters = inspect.signature(tool_method).parameters
    except (TypeError, ValueError) as exc:
        raise FastMcpAdapterError(f"cannot inspect FastMCP.tool: {exc}") from exc
    required_parameters = {"name", "description", "meta", "structured_output"}
    missing_parameters = sorted(required_parameters - set(parameters))
    if missing_parameters:
        raise FastMcpAdapterError(
            "FastMCP.tool lacks audited registration parameters: "
            + ", ".join(missing_parameters)
        )
    live_tools = _manager_tools(mcp)
    if name in live_tools:
        raise FastMcpAdapterError(f"FastMCP already contains tool {name!r}")
    kwargs: dict[str, Any] = {
        "name": name,
        "description": description,
        "meta": dict(meta),
        "structured_output": structured_output,
    }
    cast(Callable[..., Any], tool_method)(**kwargs)(adapted)

    tool = _manager_tools(mcp).get(name)
    if tool is None:
        raise FastMcpAdapterError(f"FastMCP did not retain registered tool {name!r}")
    registered_callable = getattr(tool, "fn", None)
    if not callable(registered_callable):
        raise FastMcpAdapterError(f"registered tool {name!r} has no callable")
    raw_parameters = getattr(tool, "parameters", None)
    if not isinstance(raw_parameters, Mapping):
        raise FastMcpAdapterError(
            f"registered tool {name!r} has no mapping input schema"
        )
    registered_description = getattr(tool, "description", None)
    if not isinstance(registered_description, str):
        raise FastMcpAdapterError(f"registered tool {name!r} has no description")
    registered_meta = getattr(tool, "meta", None)
    if not isinstance(registered_meta, Mapping):
        raise FastMcpAdapterError(f"registered tool {name!r} has no metadata mapping")

    input_json = normalize_schema(raw_parameters, input_schema=True)
    input_json = _normalize_implicit_none_parameters(input_json, func)
    # Overlay catalog fragments after normalization so their original array
    # order and intentional open-object semantics remain exact.
    input_json = _restore_parameter_schema_extras(input_json, func)
    raw_output = getattr(tool, "output_schema", None)
    if not isinstance(raw_output, Mapping):
        raise FastMcpAdapterError(
            f"FastMCP did not publish a mapping output schema for {name!r}"
        )
    output_json = normalize_schema(raw_output, input_schema=False)

    call_result, call_result_model = _call_tool_result_output_model(
        _resolved_return_annotation(func)
    )
    if call_result:
        assert call_result_model is not None  # guarded by _registration_callable
        try:
            expected_output = normalize_schema(
                TypeAdapter(call_result_model).json_schema(),
                input_schema=False,
            )
        except Exception as exc:
            raise FastMcpAdapterError(
                f"cannot derive structuredContent schema for {name!r}: {exc}"
            ) from exc
        if output_json != expected_output:
            raise FastMcpAdapterError(
                f"FastMCP did not honor the Annotated CallToolResult output model "
                f"for {name!r}; mcp{SUPPORTED_MCP_RANGE} is required"
            )

    # Make the live MCP schema byte-for-byte comparable with the canonical
    # registry. CallToolResult tools advertise their source-owned structured
    # content model, never the outer MCP response envelope.
    try:
        tool.parameters = input_json
        if structured_output:
            tool.output_schema = output_json
        tool.description = description
        tool.meta = dict(meta)
    except Exception as exc:
        raise FastMcpAdapterError(
            f"cannot normalize registered tool {name!r}: {exc}"
        ) from exc
    if tool.parameters != input_json or tool.description != description:
        raise FastMcpAdapterError(
            f"FastMCP did not retain normalized schema/description for {name!r}"
        )
    if structured_output and tool.output_schema != output_json:
        raise FastMcpAdapterError(
            f"FastMCP did not retain the normalized output schema for {name!r}"
        )
    if tool.meta != dict(meta):
        raise FastMcpAdapterError(f"FastMCP did not retain metadata for {name!r}")
    return FastMcpToolSnapshot(
        name=name,
        callable=original_callable(registered_callable),
        description=tool.description,
        input_schema=input_json,
        output_schema=output_json,
        meta=dict(tool.meta),
    )


def describe_callables(
    entries: list[tuple[str, Callable[..., Any], str, Mapping[str, Any]]],
) -> dict[str, FastMcpToolSnapshot]:
    """Build schemas for every public callable, including inactive advanced tools."""

    schema_server = FastMCP("hwpx-tool-contract-schema")
    snapshots: dict[str, FastMcpToolSnapshot] = {}
    for name, func, description, meta in entries:
        snapshots[name] = _register(
            schema_server,
            name=name,
            func=func,
            description=description,
            meta=meta,
        )
    return snapshots


def register_canonical_tool(
    mcp: Any,
    *,
    name: str,
    func: Callable[..., Any],
    description: str,
    meta: Mapping[str, Any],
) -> FastMcpToolSnapshot:
    """Register one canonical callable through the public SDK hook."""

    return _register(mcp, name=name, func=func, description=description, meta=meta)


def register_canonical_resource(
    mcp: Any,
    *,
    uri: str,
    name: str,
    description: str,
    mime_type: str,
    func: Callable[[], str],
) -> None:
    """Register one canonical read-only resource through the public SDK hook.

    이 어댑터가 유일한 FastMCP 호환 seam이라는 계약(모듈 docstring)은 리소스
    표면에도 그대로 적용된다 — 다른 모듈은 이 함수를 부르지, SDK의
    ``resource`` 데코레이터를 직접 만지지 않는다.
    """

    try:
        mcp.resource(uri, name=name, description=description, mime_type=mime_type)(
            func
        )
    except Exception as exc:  # pragma: no cover - SDK 계약 위반은 등록 시점 하드 실패
        raise FastMcpAdapterError(
            f"failed to register canonical resource {uri!r}: {exc}"
        ) from exc


def snapshot_runtime_tools(mcp: Any) -> Mapping[str, FastMcpToolSnapshot]:
    """Return an insertion-ordered, read-only snapshot of the live registry."""

    snapshots: dict[str, FastMcpToolSnapshot] = {}
    for name, tool in _manager_tools(mcp).items():
        if not isinstance(name, str) or not name:
            raise FastMcpAdapterError("FastMCP retained a non-string tool name")
        registered = getattr(tool, "fn", None)
        if not callable(registered):
            raise FastMcpAdapterError(f"registered tool {name!r} has no callable")
        func = original_callable(registered)
        description = getattr(tool, "description", None)
        if not isinstance(description, str):
            raise FastMcpAdapterError(f"registered tool {name!r} has no description")
        meta = getattr(tool, "meta", None)
        if not isinstance(meta, Mapping):
            raise FastMcpAdapterError(f"registered tool {name!r} has no metadata mapping")
        raw_parameters = getattr(tool, "parameters", None)
        if not isinstance(raw_parameters, Mapping):
            raise FastMcpAdapterError(
                f"registered tool {name!r} has no mapping input schema"
            )
        raw_output = getattr(tool, "output_schema", None)
        if not isinstance(raw_output, Mapping):
            raise FastMcpAdapterError(
                f"registered tool {name!r} has no mapping output schema"
            )
        input_schema = normalize_schema(raw_parameters, input_schema=True)
        input_schema = _normalize_implicit_none_parameters(input_schema, func)
        input_schema = _restore_parameter_schema_extras(input_schema, func)
        snapshots[name] = FastMcpToolSnapshot(
            name=name,
            callable=func,
            description=description,
            input_schema=input_schema,
            output_schema=normalize_schema(raw_output, input_schema=False),
            meta=dict(meta),
        )
    return MappingProxyType(snapshots)


__all__ = [
    "AUDITED_MCP_PATCHES",
    "FastMcpAdapterError",
    "FastMcpToolSnapshot",
    "SUPPORTED_MCP_RANGE",
    "configure_runtime",
    "describe_callables",
    "normalize_schema",
    "original_callable",
    "register_canonical_tool",
    "runtime_server_version",
    "snapshot_runtime_tools",
]
