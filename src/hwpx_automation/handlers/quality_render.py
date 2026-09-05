# SPDX-License-Identifier: Apache-2.0
"""Quality and render automation handlers for the optional MCP adapter."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import mcp.types as mcp_types
from hwpx import (
    doc_diff as build_hwpx_doc_diff,
)
from hwpx import (
    inspect_reference_consistency as inspect_hwpx_reference_consistency,
)

from ..configuration import env_float, env_value
from ..identity import product_identity
from ..fastmcp_adapter import snapshot_runtime_tools
from ..office.authoring import (
    inspect_operating_plan_quality as inspect_operating_plan_document_quality,
)
from ..office.authoring.presets import (
    inspect_proposal_quality as inspect_proposal_document_quality,
)
from ..office.compliance import (
    inspect_official_document_style as inspect_hwpx_official_document_style,
)
from ..preview_output_models import RenderPreviewOutput
from ..runtime_services import RUNTIME_SERVICES
from ..tool_contract import (
    contract_hash as tool_contract_hash,
)
from ..tool_contract import (
    expected_tool_names,
    expected_tool_order,
    skill_required_tool_names,
    validate_registered_tools,
)
from ..utils.helpers import default_max_chars, resolve_path
from ..workflow.render_queue import RenderQueueError
from ..workflow.rendering import NullRenderClientV2, RenderJobV2
from ..workspace import (
    WORKSPACE_ROOTS_ENV,
    WorkspaceConfigurationError,
    WorkspaceResolver,
)
from ._shared import (
    _capability_block,
    _diff_sources,
    _inspect_authoring_quality,
    _package_version,
    _proposal_quality_fallback,
    _render_client,
    _with_document_state,
)

_DEFAULT_FETCH_TIMEOUT_SECONDS = 20.0


def _fastmcp_tool_names() -> list[str]:
    """Return names observed through the isolated FastMCP adapter seam."""

    return list(snapshot_runtime_tools(RUNTIME_SERVICES.require_mcp()))


def inspect_document_authoring_quality(
    filename: str,
    document_plan: dict = None,
    quality_profile: str = None,
    profile: dict = None,
) -> dict:
    """document-plan 기반 생성물의 reopen/package/schema 품질 근거를 조회합니다."""
    path = resolve_path(filename)
    return _inspect_authoring_quality(
        path,
        document_plan=document_plan,
        quality_profile=quality_profile,
        profile=profile,
    )


def inspect_operating_plan_quality(
    filename: str,
    document_plan: dict = None,
    profile: dict = None,
) -> dict:
    """운영 계획서 제출 후보의 file-only 품질 프로필을 반환합니다."""
    path = resolve_path(filename)
    if inspect_operating_plan_document_quality is not None:
        return inspect_operating_plan_document_quality(
            path, plan=document_plan, profile=profile
        )
    report = _inspect_authoring_quality(
        path,
        document_plan=document_plan,
        quality_profile={"name": "operating_plan", **dict(profile or {})},
    )
    return report.get("profiles", {}).get("operating_plan", report)


def inspect_official_document_style(
    filename: str = None,
    paragraphs: list[str] = None,
    document_plan: dict = None,
) -> dict:
    """공문서 작성규정 lint를 실행하고 위반별 수정 제안을 반환합니다."""
    if inspect_hwpx_official_document_style is None:
        raise RuntimeError(
            "installed python-hwpx does not provide official-document lint"
        )
    if filename:
        path = resolve_path(filename)
        return _with_document_state(inspect_hwpx_official_document_style(path), path)
    if document_plan is not None:
        return inspect_hwpx_official_document_style(document_plan or {})
    if paragraphs is not None:
        return inspect_hwpx_official_document_style(paragraphs or [])
    raise ValueError("filename, document_plan, or paragraphs is required")


def doc_diff(
    old_filename: str = None,
    new_filename: str = None,
    old_paragraphs: list[str] = None,
    new_paragraphs: list[str] = None,
) -> dict:
    """두 문서 또는 문단 목록의 LCS 기반 신구 paragraph diff를 반환합니다."""
    if build_hwpx_doc_diff is None:
        raise RuntimeError("installed python-hwpx does not provide doc_diff")
    old_source, new_source = _diff_sources(
        old_filename=old_filename,
        new_filename=new_filename,
        old_paragraphs=old_paragraphs,
        new_paragraphs=new_paragraphs,
    )
    return build_hwpx_doc_diff(old_source, new_source)


def inspect_reference_consistency(
    filename: str = None,
    paragraphs: list[str] = None,
    document_plan: dict = None,
) -> dict:
    """붙임 참조와 표/그림 번호 연속성의 의미 수준 정합성을 검사합니다."""
    if inspect_hwpx_reference_consistency is None:
        raise RuntimeError(
            "installed python-hwpx does not provide reference consistency lint"
        )
    if filename:
        path = resolve_path(filename)
        return _with_document_state(inspect_hwpx_reference_consistency(path), path)
    if document_plan is not None:
        return inspect_hwpx_reference_consistency(document_plan or {})
    if paragraphs is not None:
        return inspect_hwpx_reference_consistency(paragraphs or [])
    raise ValueError("filename, document_plan, or paragraphs is required")


def inspect_document_quality(filename: str, rubric: str = "proposal") -> dict:
    """생성된 HWPX 문서를 제안서 품질 루브릭으로 점검합니다."""
    if rubric != "proposal":
        raise ValueError("rubric must be 'proposal'")
    path = resolve_path(filename)
    if inspect_proposal_document_quality is not None:
        return inspect_proposal_document_quality(path)
    return _proposal_quality_fallback(path)


def render_preview(
    filename: str,
    output_dir: str | None = None,
    mode: str = "pages",
    screenshot: str = "auto",
    max_pages: int | None = None,
    embed_images: bool = True,
    max_image_bytes: int | None = None,
    viewer: bool = False,
) -> Annotated[mcp_types.CallToolResult, RenderPreviewOutput]:
    """레이아웃 충실 HTML과 headless browser PNG 프리뷰 산출물을 생성합니다.

    embed_images 가 참이면 각 페이지 PNG 를 인라인 이미지 콘텐츠 블록으로 함께
    반환해 (한컴/ComputerUse 없이) 모델이 레이아웃을 직접 볼 수 있습니다. 구조화
    매니페스트(JSON)는 structuredContent 로 그대로 유지됩니다.

    viewer 가 참이면 매니페스트에 자체완결 스크롤 문서 뷰어(수식은
    python-hwpx[preview] 설치 시 네이티브 MathML)를 workspace 안의
    viewer.html 로 쓰고 structuredContent.viewer 로 함께 반환합니다. 뷰어는
    래스터화와 독립이므로 가벼운 텍스트 경로에는 screenshot="off" 와 함께
    쓰세요. viewer.equationRendering 은 MathML/latex/script 폴백 개수로 충실도
    티어를 정직하게 표면화합니다.
    """
    manifest = RUNTIME_SERVICES.ops.render_preview(
        path=filename,
        output_dir=output_dir,
        mode=mode,
        screenshot=screenshot,
        max_pages=max_pages,
        embed_images=embed_images,
        max_image_bytes=max_image_bytes,
        viewer=viewer,
    )

    images: list[mcp_types.ImageContent] = []
    for shot in manifest.get("screenshots", []):
        data = shot.pop("imageBase64", None)
        mime = shot.pop("imageMime", "image/png")
        if data:
            images.append(
                mcp_types.ImageContent(type="image", data=data, mimeType=mime)
            )
            shot["imageEmbedded"] = True
        elif embed_images:
            shot["imageEmbedded"] = False

    content: list[mcp_types.ContentBlock] = [
        mcp_types.TextContent(
            type="text", text=json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    ]
    content.extend(images)
    return mcp_types.CallToolResult(
        content=content,
        structuredContent=manifest,
        isError=False,
    )


def describe_capabilities(domain: str | None = None) -> dict:
    """이 HWPX 툴킷이 무엇을 할 수 있는지 작업 종류별로 요약한 능력 지도를 반환합니다.

    도구 등록을 단일 ToolSpec 계약에서 생성하므로 실제 FastMCP 표면과
    capability map이 항상 같은 진실을 반영합니다. 이 도구를 한 번
    부르면 작업군(읽기·양식채움·생성·편집·표·서식·차례·PII·레드라인·시험지·직인·
    대량생산·메모·검증·패키지)별 intent + 언제 쓰는지 + 진입점 도구가 나옵니다.
    domain 인자로 한 작업군 상세만 필터할 수 있습니다(예: domain="form_fill").
    처음 이 서버로 HWPX 작업을 시작하는 에이전트는 이걸 먼저 부르면 오리엔테이션이
    됩니다. coverage에 등록 도구 대비 미매핑이 표시되면 그건 이 지도의 드리프트입니다."""
    from ..capabilities import build_capability_report, coverage_against

    advanced = RUNTIME_SERVICES.active_advanced
    report = build_capability_report(domain if domain else None, advanced=advanced)
    live = set(_fastmcp_tool_names())
    report["toolCount"] = len(live)
    validation = (
        validate_registered_tools(
            RUNTIME_SERVICES.require_mcp(), RUNTIME_SERVICES.tool_registry
        )
        if RUNTIME_SERVICES.tool_registry is not None
        else {"ok": False, "missing": sorted(expected_tool_names(advanced=advanced))}
    )
    report["coverage"] = coverage_against(
        live,
        advanced=advanced,
        registry_validation=validation,
    )
    # additive(6.6): core 자기서술·오라클 가용성·리소스 카탈로그를 합성한다 —
    # 자기서술 도구를 둘로 쪼개지 않는다(진실 이원화 방지).
    from ..capabilities import core_self_description, render_oracle_availability
    from ..resources import CANONICAL_RESOURCES

    report["core"] = core_self_description()
    report["renderOracle"] = render_oracle_availability()
    report["resources"] = [
        {"uri": spec.uri, "name": spec.name, "mimeType": spec.mime_type}
        for spec in CANONICAL_RESOURCES
    ]
    return report


_STACK_UPDATE_STATE_SCHEMA = "hwpx.stack-update-state.v1"


def _stack_update_block() -> dict[str, Any]:
    """Launcher-managed runtime update state (hwpx-plugins Feature 066).

    The bundled launcher writes update-state.json and passes its path as
    HWPX_STACK_UPDATE_STATE. Without it the runtime is not launcher-managed
    (pip install, editable checkout, plain uvx) and the block says so; it
    never guesses.
    """
    path = os.environ.get("HWPX_STACK_UPDATE_STATE")
    if not path:
        return {"available": False, "reason": "NOT_MANAGED"}
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {"available": False, "reason": "STATE_MISSING", "path": path}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": "STATE_UNREADABLE", "path": path, "detail": str(exc)}
    if not isinstance(state, dict) or state.get("schemaVersion") != _STACK_UPDATE_STATE_SCHEMA:
        return {"available": False, "reason": "STATE_SCHEMA_UNKNOWN", "path": path}
    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        return {"available": False, "reason": "STATE_INVALID", "path": path}
    installed = runtime.get("installed")
    if (
        not isinstance(installed, dict)
        or set(installed) != {"python-hwpx", "python-hwpx-automation"}
        or not all(isinstance(value, str) and value for value in installed.values())
    ):
        return {"available": False, "reason": "STATE_INVALID", "path": path}
    running = {
        "python-hwpx": _package_version("python-hwpx"),
        "python-hwpx-automation": _package_version("python-hwpx-automation"),
    }
    runtime = {
        **runtime,
        "running": running,
        "restartRequired": runtime["installed"] != running,
    }
    return {
        "available": True,
        "path": path,
        "checkedAt": state.get("checkedAt"),
        "autoUpdate": state.get("autoUpdate"),
        "channel": state.get("channel"),
        "runtime": runtime,
        "pluginBundle": state.get("pluginBundle"),
        "lastError": state.get("lastError"),
    }


def mcp_server_health() -> dict:
    """MCP 서버 transport와 timeout/keepalive 점검 정보를 반환합니다."""
    transport = env_value("TRANSPORT", "stdio")
    try:
        workspace = WorkspaceResolver.from_environment().describe()
    except WorkspaceConfigurationError as exc:
        workspace = {
            "source": "invalid",
            "roots": [],
            "rootCount": 0,
            "relativePathRoot": None,
            "failClosed": True,
            "configurationError": str(exc),
        }
    advanced = RUNTIME_SERVICES.active_advanced
    registry_validation: dict[str, Any] = (
        validate_registered_tools(
            RUNTIME_SERVICES.require_mcp(), RUNTIME_SERVICES.tool_registry
        )
        if RUNTIME_SERVICES.tool_registry is not None
        else {
            "ok": False,
            "missing": sorted(expected_tool_names(advanced=advanced)),
            "unexpected": [],
            "callableMismatches": [],
            "inputSchemaMismatches": [],
            "outputSchemaMismatches": [],
            "descriptionMismatches": [],
            "unavailable": [],
            "orderMismatch": False,
            "expectedOrder": list(expected_tool_order(advanced=advanced)),
            "actualOrder": [],
        }
    )
    fastmcp_tool_names = set(registry_validation["actualOrder"])
    expected = expected_tool_names(advanced=advanced)
    active_required = skill_required_tool_names() & expected
    missing_expected = sorted(expected - fastmcp_tool_names)
    unexpected_registered = sorted(fastmcp_tool_names - expected)
    missing_required = sorted(active_required - fastmcp_tool_names)
    skew_detected = bool(
        missing_expected
        or unexpected_registered
        or missing_required
        or not registry_validation["ok"]
    )
    surface_details = []
    if missing_expected:
        surface_details.append(f"missing expected: {', '.join(missing_expected)}")
    if unexpected_registered:
        surface_details.append(
            f"unexpected registered: {', '.join(unexpected_registered)}"
        )
    if missing_required:
        surface_details.append(f"missing skill-required: {', '.join(missing_required)}")
    if registry_validation["orderMismatch"]:
        surface_details.append("registered tool order differs from ToolSpec order")
    for key, label in (
        ("callableMismatches", "callable mismatch"),
        ("inputSchemaMismatches", "input schema mismatch"),
        ("outputSchemaMismatches", "output schema mismatch"),
        ("descriptionMismatches", "description mismatch"),
        ("unavailable", "unavailable"),
    ):
        values = registry_validation[key]
        if values:
            surface_details.append(f"{label}: {', '.join(values)}")
    return {
        "server": "python-hwpx-automation",
        "serverInfo": {
            "name": "python-hwpx-automation",
            "canonicalMcpConsole": "hwpx-automation-mcp",
            "compatibilityMcpConsoles": ["hwpx-mcp-server"],
            "hostConfigKeyRole": "host-local-alias",
        },
        "productIdentity": product_identity(),
        "version": _package_version("python-hwpx-automation"),
        "pythonHwpxVersion": _package_version("python-hwpx"),
        "skillBundleVersion": os.environ.get("HWPX_SKILL_VERSION", "unknown"),
        "pluginRoot": os.environ.get("HWPX_PLUGIN_ROOT"),
        "transport": transport,
        "streamable_http_available": callable(
            getattr(RUNTIME_SERVICES.require_mcp(), "streamable_http_app", None)
        ),
        "toolSurface": {
            "status": "skewed" if skew_detected else "ok",
            "profile": "advanced" if advanced else "default",
            "contractHash": tool_contract_hash(),
            "bindingHash": RUNTIME_SERVICES.tool_registry.binding_hash()
            if RUNTIME_SERVICES.tool_registry
            else None,
            "bindingStatus": "bound" if RUNTIME_SERVICES.tool_registry else "unbound",
            "expectedFastMcpToolCount": len(expected),
            "actualFastMcpToolCount": len(fastmcp_tool_names),
            "missingExpectedTools": missing_expected,
            "unexpectedRegisteredTools": unexpected_registered,
            "missingSkillRequiredTools": missing_required,
            "callableMismatches": registry_validation["callableMismatches"],
            "inputSchemaMismatches": registry_validation["inputSchemaMismatches"],
            "outputSchemaMismatches": registry_validation["outputSchemaMismatches"],
            "descriptionMismatches": registry_validation["descriptionMismatches"],
            "unavailableTools": registry_validation["unavailable"],
            "orderMismatch": registry_validation["orderMismatch"],
            # Compatibility alias for older skill startup checks.
            "missingKeyTools": missing_required,
            "keyTools": sorted(active_required),
            "diagnosis": (
                "Installed MCP surface is missing expected tools; reinstall the hwpx plugin, "
                "remove stale plugin venv/cache, then start a fresh host session."
                if skew_detected
                else "Installed MCP surface exactly matches the active ToolSpec contract."
            ),
        },
        "capability": _capability_block(skew_detected, surface_details),
        "stackUpdate": _stack_update_block(),
        "unitPolicy": {
            "status": "audited",
            "fontSize": "points",
            "paragraphLineSpacing": "percent",
            "paragraphIndent": "millimeters",
            "paragraphSpacing": "points",
            "pageSizeAndMargins": "millimeters",
            "borderWidth": "human value: number/string accepted; prefer pt or mm suffix when supported",
            "fileSizeLimits": "bytes",
            "pageAndTableInternals": "HWP units are internal implementation details; MCP tools should prefer mm/pt/% labels.",
            "verification": "public unit conversions are enforced by the automated test suite",
        },
        "fetch_timeout_seconds": env_float(
            "FETCH_TIMEOUT_SECONDS", _DEFAULT_FETCH_TIMEOUT_SECONDS
        ),
        "max_chars": default_max_chars(),
        "workspace": workspace,
        "sandbox": {
            "root": workspace["relativePathRoot"],
            "roots": workspace["roots"],
            "absolute_paths_inside_root_allowed": bool(workspace["rootCount"]),
            "path_guidance": (
                "Use a relative path under the primary workspace or an absolute path inside an authorized root. "
                f"Set {WORKSPACE_ROOTS_ENV} to a JSON array for deterministic multi-root launches."
            ),
        },
        "disconnect_diagnostics": {
            "likely_conditions": [
                "large document extraction exceeding client/tool timeout",
                "idle stdio client session termination",
                "remote URL fetch timeout",
            ],
            "keepalive_check": "streamable_http_app constructibility is covered by smoke tests; stdio keepalive is client-controlled.",
        },
    }


def repair_hwpx(
    source_filename: str,
    output_filename: str,
    recover: bool = False,
    overwrite: bool = False,
    max_entry_size: int = 64 * 1024 * 1024,
    max_total_size: int = 512 * 1024 * 1024,
    max_source_size: int = 512 * 1024 * 1024,
) -> dict:
    """HWPX ZIP 패키지를 repair-repack하거나, recover=true일 때 Local File Header 스캔으로 복구합니다."""
    return RUNTIME_SERVICES.ops.repair_hwpx(
        source=resolve_path(source_filename),
        output=resolve_path(output_filename),
        recover=recover,
        overwrite=overwrite,
        max_entry_size=max_entry_size,
        max_total_size=max_total_size,
        max_source_size=max_source_size,
    )


def render_submit(
    filename: str,
    idempotency_key: str,
    workflow_id: str = None,
    dpi: int = 144,
) -> dict:
    """실한컴 렌더 큐에 비동기로 제출하고 즉시 receipt를 반환합니다."""

    source = Path(resolve_path(filename))
    data = source.read_bytes()
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    stable = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    safe_workflow = workflow_id or f"direct-{stable}"
    client = _render_client()
    if not isinstance(client, NullRenderClientV2):
        try:
            existing = client.get(f"render-{stable}")
        except RenderQueueError:
            existing = None
        if existing is not None:
            if existing.input_content_hash != digest:
                return {
                    "ok": False,
                    "errorCode": "IDEMPOTENCY_CONFLICT",
                    "jobId": existing.job_id,
                }
            return {"ok": True, "receipt": existing.model_dump(mode="json")}
    job = RenderJobV2(
        job_id=f"render-{stable}",
        workflow_id=safe_workflow,
        idempotency_key=idempotency_key,
        source_content_hash=digest,
        source_size_bytes=len(data),
        submitted_at=datetime.now(timezone.utc),
        dpi=dpi,
    )
    receipt = client.submit(job, source)
    return {
        "ok": receipt.status.value not in {"failed", "unavailable"},
        "receipt": receipt.model_dump(mode="json"),
    }


def render_status(job_id: str, output_dir: str = None) -> dict:
    """렌더 job 상태를 한 번 조회합니다. 서버는 poll 동안 호출을 점유하지 않습니다."""

    client = _render_client()
    try:
        receipt = client.get(job_id)
    except (KeyError, RenderQueueError):
        return {
            "ok": False,
            "jobId": job_id,
            "status": "unverified",
            "errorCode": "RENDER_JOB_NOT_FOUND_OR_UNAVAILABLE",
        }
    response = {"ok": True, "receipt": receipt.model_dump(mode="json")}
    if output_dir and receipt.status.value == "succeeded":
        destination = Path(resolve_path(output_dir))
        destination.mkdir(parents=True, exist_ok=True)
        saved = []
        for artifact in receipt.artifacts:
            name = (
                "document.pdf"
                if artifact.kind.value == "pdf"
                else f"page-{artifact.page_number:04d}.png"
            )
            data = client.fetch_artifact(job_id, artifact.content_hash)
            target = destination / name
            target.write_bytes(data)
            saved.append(
                {
                    "path": str(target),
                    "contentHash": artifact.content_hash,
                    "kind": artifact.kind.value,
                }
            )
        response["savedArtifacts"] = saved
    return response


def render_cancel(job_id: str) -> dict:
    """대기 job을 취소하거나 실행 worker에 취소 요청을 기록합니다."""

    client = _render_client()
    try:
        receipt = client.cancel(job_id)
    except (KeyError, RenderQueueError):
        return {
            "ok": False,
            "jobId": job_id,
            "status": "unverified",
            "errorCode": "RENDER_JOB_NOT_FOUND_OR_UNAVAILABLE",
        }
    return {"ok": True, "receipt": receipt.model_dump(mode="json")}


def render_health() -> dict:
    """큐/worker/Hancom 상태와 적체를 반환하며 미구성·stale heartbeat는 degraded입니다."""

    return _render_client().capabilities()


def validate_structure(filename: str) -> dict:
    """[고급] HWPX 구조 유효성을 검사합니다."""
    return RUNTIME_SERVICES.ops.validate_structure(resolve_path(filename))


def lint_text_conventions(filename: str) -> dict:
    """[고급] 텍스트 규칙 위반 여부를 검사합니다."""
    return RUNTIME_SERVICES.ops.lint_text_conventions(resolve_path(filename))


__all__ = [
    "render_submit",
    "render_status",
    "render_cancel",
    "render_health",
    "render_preview",
    "repair_hwpx",
    "mcp_server_health",
    "describe_capabilities",
    "doc_diff",
    "validate_structure",
    "lint_text_conventions",
    "inspect_document_quality",
    "inspect_document_authoring_quality",
    "inspect_operating_plan_quality",
    "inspect_official_document_style",
    "inspect_reference_consistency",
]
