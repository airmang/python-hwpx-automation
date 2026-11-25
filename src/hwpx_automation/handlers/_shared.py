# SPDX-License-Identifier: Apache-2.0
"""Shared automation handlers used by the optional MCP adapter."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import os
from pathlib import Path
from typing import Any, Literal, cast

from ..office.authoring import (
    inspect_document_authoring_quality as inspect_authoring_document_quality,
)
from hwpx.tools.id_integrity import check_id_integrity

from ..core.document import save_doc
from ..core.transactions import (
    rotate_and_backup,
    save_dry_run,
    semantic_diff,
)
from ..document_state import document_state_payload, revision_mismatch_response
from .. import quality as quality_contract
from ..quality_generation import (
    inspect_quality_fallback,
)
from ..storage import (
    build_hwpx_verification_report,
    refuse_existing_hwp_overwrite,
)
from ..utils.helpers import resolve_path
from ..workflow.render_queue import DurableRenderQueue
from ..workflow.render_security import RenderSecurityPolicy
from ..workflow.render_transport import RemoteRenderClientV2
from ..workflow.rendering import NullRenderClientV2, QueueRenderClientV2
from ..runtime_services import RUNTIME_SERVICES


def _package_version(package: str) -> str:
    return quality_contract.package_version(package)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    return max(0.1, parsed)


def _idempotency_scope(
    tool_name: str, path: str, idempotency_key: str | None
) -> str | None:
    key = (idempotency_key or "").strip()
    if not key:
        return None
    resolved = str(Path(path).resolve())
    return f"{tool_name}:{resolved}:{key}"


def _idempotency_fingerprint(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)


def _idempotency_replay(
    scope: str | None,
    *,
    fingerprint: str,
) -> dict[str, Any] | None:
    if scope is None:
        return None
    cached = RUNTIME_SERVICES.idempotency_cache.get(scope)
    if cached is None:
        return None
    if cached.get("fingerprint") != fingerprint:
        raise ValueError("idempotency_key was reused with different arguments")
    payload = copy.deepcopy(cached["payload"])
    payload["idempotentReplay"] = True
    return payload


def _idempotency_store(
    scope: str | None,
    *,
    fingerprint: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if scope is None:
        return payload
    stored = copy.deepcopy(payload)
    stored["idempotentReplay"] = False
    RUNTIME_SERVICES.idempotency_cache[scope] = {
        "fingerprint": fingerprint,
        "payload": stored,
    }
    while (
        len(RUNTIME_SERVICES.idempotency_cache)
        > RUNTIME_SERVICES.max_idempotency_cache_entries
    ):
        RUNTIME_SERVICES.idempotency_cache.pop(
            next(iter(RUNTIME_SERVICES.idempotency_cache))
        )
    return copy.deepcopy(stored)


def _normalize_fill_mappings(mappings: dict[str, str]) -> dict[str, str]:
    if not isinstance(mappings, dict):
        raise ValueError(
            "mappings must be an object mapping path strings to text values"
        )
    if not mappings:
        raise ValueError("mappings must not be empty")

    normalized: dict[str, str] = {}
    for path, value in mappings.items():
        if not isinstance(path, str) or not path.strip():
            raise ValueError("mappings keys must be non-empty strings")
        normalized[path] = value if isinstance(value, str) else str(value)
    return normalized


def _decode_image_base64(image_base64: str) -> bytes:
    try:
        payload = base64.b64decode((image_base64 or "").strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid image_base64 payload") from exc
    if not payload:
        raise ValueError("image_base64 decoded to empty payload")
    return payload


def _id_integrity_payload(doc: Any) -> dict[str, Any]:
    report = check_id_integrity(doc)
    return {
        "ok": report.ok,
        "dangling": [str(item) for item in report.dangling],
        "orphanBinData": [str(item) for item in report.orphan_bin_data],
        "ignored": [str(item) for item in report.ignored],
    }


def _save_doc_verification(
    doc: Any, path: str, *, quality: Any = None
) -> dict[str, Any]:
    target = Path(path)
    # Before the backup: a refused save leaves no .bak beside the original.
    refuse_existing_hwp_overwrite(target)
    backup = rotate_and_backup(target)
    verification = save_doc(doc, path, quality=quality)
    if not isinstance(verification, dict):
        verification = build_hwpx_verification_report(target)
    verification["filePath"] = str(target)
    verification["backup"] = backup.to_dict()
    if backup.backup_path is not None:
        try:
            verification["semanticDiff"] = semantic_diff(backup.backup_path, target)
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            verification["semanticDiff"] = {
                "schemaVersion": "hwpx.semantic-diff.v1",
                "changed": True,
                "summary": f"Semantic diff unavailable: {exc}",
                "items": [],
                "error": str(exc),
            }
    return verification


def _with_document_state(result: dict[str, Any], path: str) -> dict[str, Any]:
    payload = dict(result)
    payload.update(document_state_payload(path))
    return payload


def _revision_guard(path: str, expected_revision: str | None) -> dict[str, Any] | None:
    return revision_mismatch_response(path, expected_revision)


def _with_save_verification(
    result: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    payload = dict(result)
    payload.setdefault("dryRun", False)
    payload["verificationReport"] = verification
    payload.setdefault("openSafety", verification.get("openSafety"))
    if "visualComplete" in verification:
        payload.setdefault("visualComplete", verification["visualComplete"])
    if "semanticDiff" in verification:
        payload.setdefault("semanticDiff", verification["semanticDiff"])
    if "backup" in verification:
        payload.setdefault("backup", verification["backup"])
    file_path = verification.get("filePath")
    if isinstance(file_path, str):
        payload.update(document_state_payload(file_path))
    return payload


def _with_dry_run_verification(
    result: dict[str, Any], doc: Any, path: str, *, quality: Any = None
) -> dict[str, Any]:
    payload = dict(result)
    dry_run = save_dry_run(doc, path, quality=quality)
    payload.update(dry_run)
    payload.update(document_state_payload(path))
    return payload


def _quality_profile_argument(
    quality_profile: str | dict | None,
    profile: dict | None = None,
) -> str | dict | None:
    """Normalize MCP quality-profile arguments for python-hwpx."""

    if profile:
        merged = dict(profile)
        if quality_profile:
            merged.setdefault("name", quality_profile)
        return merged
    return quality_profile


def _inspect_authoring_quality(
    source: str | Any,
    *,
    document_plan: dict | None,
    quality_profile: str | dict | None = None,
    profile: dict | None = None,
    verify_render: bool = False,
) -> dict:
    if inspect_authoring_document_quality is None:
        raise RuntimeError(
            "installed python-hwpx does not provide document-plan authoring"
        )
    profile_arg = _quality_profile_argument(quality_profile, profile)
    kwargs: dict[str, Any] = {"plan": document_plan}
    if profile_arg is not None:
        kwargs["quality_profile"] = profile_arg
    if verify_render:
        kwargs["verify_render"] = True
    try:
        return inspect_authoring_document_quality(source, **kwargs)
    except TypeError as exc:
        # An older installed python-hwpx may predate verify_render and/or the
        # quality_profile kwarg; retry without the unsupported argument(s).
        if verify_render:
            kwargs.pop("verify_render", None)
            try:
                return inspect_authoring_document_quality(source, **kwargs)
            except TypeError:
                pass
        if profile_arg is not None:
            raise RuntimeError(
                "installed python-hwpx does not support document-plan quality profiles"
            ) from exc
        raise


def _diff_sources(
    *,
    old_filename: str | None = None,
    new_filename: str | None = None,
    old_paragraphs: list[str] | None = None,
    new_paragraphs: list[str] | None = None,
) -> tuple[Any, Any]:
    if old_filename and new_filename:
        return resolve_path(old_filename), resolve_path(new_filename)
    if old_paragraphs is not None and new_paragraphs is not None:
        return old_paragraphs, new_paragraphs
    raise ValueError(
        "provide old_filename/new_filename or old_paragraphs/new_paragraphs"
    )


def _proposal_quality_fallback(path: str) -> dict:
    """Compatibility report when installed python-hwpx lacks proposal presets."""

    report = inspect_quality_fallback(path)
    table_checks = dict(report.get("table_checks") or {})
    table_checks.setdefault(
        "has_budget_table", bool(table_checks.get("has_structured_tables"))
    )
    report["table_checks"] = table_checks
    report["report_version"] = "proposal-quality-v2"
    return report


def _capability_block(tool_surface_skew: bool, surface_details: list[str]) -> dict:
    """Core/automation/plugin capability handshake (plan §2 Phase F).

    Versions + a fingerprint hash + skew. Writes fail closed on a *version* skew
    (the SavePipeline gate would otherwise be unavailable). Tool-surface skew is
    part of the installed capability verdict and is never reported healthy.
    """

    state = quality_contract.capability_state()
    skew = list(state["skew"])
    if tool_surface_skew:
        detail = "; ".join(surface_details) or "ToolSpec mismatch"
        skew.append(f"MCP tool surface skew: {detail}")
    fail_closed = quality_contract.fail_closed_enabled()
    return {
        "handshake": "hwpx.capability.v1",
        "versions": state["versions"],
        "minPythonHwpx": state["minPythonHwpx"],
        "minAutomationVersion": state["minAutomationVersion"],
        # 6.x compatibility alias for existing health consumers.
        "minMcpVersion": state["minMcpVersion"],
        "minSkillVersion": state["minSkillVersion"],
        "savePipelineAvailable": state["savePipelineAvailable"],
        "hash": state["hash"],
        "toolContractHash": state["toolContractHash"],
        "skew": skew,
        "ok": not skew,
        "failClosed": fail_closed,
        "writesBlocked": fail_closed and bool(skew),
        "diagnosis": (
            "Capability handshake OK; general saves use SavePipeline, while guarded "
            "byte-preserving form writers return open-safety receipts."
            if not skew
            else "Capability skew: install the contract-required core/automation/plugin versions and restart the host."
        ),
    }


def _render_client():
    root = os.environ.get("HWPX_RENDER_QUEUE_ROOT")
    remote_url = os.environ.get("HWPX_RENDER_QUEUE_URL")
    secret = os.environ.get("HWPX_RENDER_QUEUE_SECRET")
    if remote_url and secret:
        transport_auth = os.environ.get("HWPX_RENDER_TRANSPORT_AUTH", "mtls")
        ca_file = os.environ.get("HWPX_RENDER_CA_FILE")
        client_certfile = os.environ.get("HWPX_RENDER_CLIENT_CERT_FILE")
        client_keyfile = os.environ.get("HWPX_RENDER_CLIENT_KEY_FILE")
        return RemoteRenderClientV2(
            remote_url,
            secret=secret.encode("utf-8"),
            transport_auth=cast(Literal["mtls", "signed_https"], transport_auth),
            ca_file=Path(ca_file).expanduser().resolve() if ca_file else None,
            client_certfile=Path(client_certfile).expanduser().resolve()
            if client_certfile
            else None,
            client_keyfile=Path(client_keyfile).expanduser().resolve()
            if client_keyfile
            else None,
        )
    if not root or not secret:
        return NullRenderClientV2()
    queue_root = Path(root).expanduser().resolve()
    policy = RenderSecurityPolicy(sandbox_root=queue_root / "sandboxes")
    queue = DurableRenderQueue(queue_root, secret=secret.encode("utf-8"), policy=policy)
    return QueueRenderClientV2(queue, secret=secret.encode("utf-8"))


__all__ = [
    "_revision_guard",
    "_save_doc_verification",
    "_with_document_state",
    "_with_dry_run_verification",
    "_with_save_verification",
    "_env_float",
    "_capability_block",
    "_decode_image_base64",
    "_diff_sources",
    "_id_integrity_payload",
    "_idempotency_fingerprint",
    "_idempotency_replay",
    "_idempotency_scope",
    "_idempotency_store",
    "_inspect_authoring_quality",
    "_normalize_fill_mappings",
    "_package_version",
    "_proposal_quality_fallback",
    "_quality_profile_argument",
    "_render_client",
]
