# SPDX-License-Identifier: Apache-2.0
"""Automation quality contract (VisualComplete Phase F).

Every write funnels through the one ``python-hwpx`` SavePipeline gate and reports a
uniform ``VisualCompleteReport``. This module owns:

* :func:`resolve_policy` — turn a model-facing ``quality`` block into a
  :class:`~hwpx.quality.QualityPolicy` (default = transparent, i.e. today's
  open-safety-only behaviour, so the contract is invisible until a caller opts in).
* :func:`save_through_pipeline` / :func:`visual_complete_block` — run the gate and
  map the report to an MCP payload (``ok`` / ``visualComplete`` / structured
  ``errors`` carrying retry-able codes + ``suggestedRetry``).
* :class:`QualityGateError` — raised when an elevated policy's gate fails so the
  write is **withheld** (fail-closed) and the model sees the structured error.
* the **capability handshake** (:func:`capability_state` / :func:`assert_write_capability`)
  — core/automation/plugin versions + a hash that **fails closed on skew** (e.g. a
  ``python-hwpx`` too old to expose the SavePipeline gate).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Any, Mapping

from .configuration import canonical_env_name, env_value
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 runtime compatibility
    import tomli as tomllib

from .tool_contract import (
    MIN_AUTOMATION_VERSION,
    MIN_MCP_VERSION,
    MIN_PYTHON_HWPX,
    MIN_SKILL_VERSION,
    contract_hash,
)

# FastMCP's call_tool catches a tool's exception and returns an isError result in
# a copied context, so the structured gate/skew error can't be caught at the
# dispatch boundary nor handed back via a ContextVar. A plain module global is
# shared across that boundary (and across threads): the exceptions stash
# themselves here on construction; the dispatch handler reads it back to rebuild
# the structured payload (codes + suggestedRetry). Dispatch is serial per request
# (clear-then-read brackets each call), so this is not a concurrency hazard.
_LAST_GATE_ERROR: Any = None


def take_last_gate_error() -> Any:
    """Pop the most recent gate/skew error recorded since the last clear."""

    global _LAST_GATE_ERROR
    err = _LAST_GATE_ERROR
    _LAST_GATE_ERROR = None
    return err


def clear_last_gate_error() -> None:
    global _LAST_GATE_ERROR
    _LAST_GATE_ERROR = None


def _record_gate_error(err: Any) -> None:
    global _LAST_GATE_ERROR
    _LAST_GATE_ERROR = err

_QUALITY_ENV = canonical_env_name("QUALITY")
_REQUIRE_CAPABILITY_ENV = canonical_env_name("REQUIRE_CAPABILITY")


# --------------------------------------------------------------------------- #
# python-hwpx quality stack (imported lazily so this module loads even on a skew).
# --------------------------------------------------------------------------- #
def _quality_available() -> bool:
    return importlib.util.find_spec("hwpx.quality") is not None


def package_version(package: str) -> str:
    module_name = {"python-hwpx": "hwpx", "python-hwpx-automation": "hwpx_automation",
                   "hwpx-mcp-server": "hwpx_automation"}.get(package)
    if module_name:
        spec = importlib.util.find_spec(module_name)
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        if origin is not None:
            for parent in origin.parents:
                pyproject = parent / "pyproject.toml"
                if not pyproject.is_file():
                    continue
                try:
                    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                    project = data.get("project", {})
                    if project.get("name") == package and isinstance(project.get("version"), str):
                        return project["version"]
                except (OSError, tomllib.TOMLDecodeError):
                    break
    try:
        return _pkg_version(package)
    except PackageNotFoundError:
        return "unknown"


def _version_lt(value: str, minimum: str) -> bool:
    """True if *value* is an older version than *minimum* (PEP 440 aware).

    Uses ``packaging.version`` so that ``"2.12"`` == ``"2.12.0"`` and a
    pre-release (``"2.12.0rc1"`` / ``".dev1"``) sorts BEFORE the final release —
    otherwise a healthy install (or an rc of the boundary) would falsely skew and
    fail closed.
    """

    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(value) < Version(minimum)
        except InvalidVersion:
            pass
    except Exception:  # pragma: no cover - packaging always present via pip
        pass
    # Stdlib fallback: zero-pad to equal length so "2.12" is not < "2.12.0".
    a = [int("".join(c for c in p if c.isdigit()) or 0) for p in value.split(".")]
    b = [int("".join(c for c in p if c.isdigit()) or 0) for p in minimum.split(".")]
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a < b


# --------------------------------------------------------------------------- #
# Quality policy resolution.
# --------------------------------------------------------------------------- #
_POLICY_KEY_MAP = {
    "requireOpenSafety": "require_open_safety",
    "requireVisualComplete": "require_visual_complete",
    "requireReferenceIntegrity": "require_reference_integrity",
    "renderCheck": "render_check",
    "xsdMode": "xsd_mode",
    "overflowPolicy": "overflow_policy",
    "layoutLint": "layout_lint",
    "allowExpertUnsafe": "allow_expert_unsafe",
}


def resolve_policy(quality: Mapping[str, Any] | str | None) -> Any:
    """Map a model-facing ``quality`` block to a ``QualityPolicy``.

    ``None`` → the ``HWPX_AUTOMATION_QUALITY`` env default (with the supported
    6.x ``HWPX_MCP_QUALITY`` fallback) → transparent. A string picks a
    named policy (``transparent`` / ``strict``). A dict elevates from transparent
    with camelCase overrides (``renderCheck`` / ``overflowPolicy`` / ``layoutLint`` …).
    """

    from hwpx import QualityPolicy

    if quality is None:
        quality = env_value("QUALITY", "transparent") or "transparent"

    if isinstance(quality, str):
        mode = quality.strip().lower()
        if mode in ("strict", "docx", "full"):
            return QualityPolicy.strict()
        return QualityPolicy.transparent()

    if isinstance(quality, Mapping):
        mode = str(quality.get("mode", "transparent")).lower()
        base = QualityPolicy.strict() if mode in ("strict", "docx", "full") else QualityPolicy.transparent()
        changes: dict[str, Any] = {}
        for key, attr in _POLICY_KEY_MAP.items():
            if key in quality:
                changes[attr] = quality[key]
        return base.with_(**changes) if changes else base

    return QualityPolicy.transparent()


# --------------------------------------------------------------------------- #
# Report → MCP payload.
# --------------------------------------------------------------------------- #
def visual_complete_block(report: Any) -> dict[str, Any]:
    """The model-facing VisualComplete block (codes + suggestedRetry)."""

    errors = [
        {
            "code": err.code,
            "message": err.message,
            "suggestedRetry": err.suggested_retry,
        }
        for err in report.errors
    ]
    return {
        "ok": bool(report.ok),
        "visualComplete": bool(report.visual_complete),
        "status": report.visual_complete_status,
        "renderChecked": bool(report.render_checked),
        "errors": errors,
        "errorCodes": [err.code for err in report.errors],
        "warnings": list(report.warnings),
        "suggestedRetry": _aggregate_retry(report),
        "form": report.form.to_dict(),
        "layout": report.layout.to_dict(),
    }


def _aggregate_retry(report: Any) -> dict[str, Any] | None:
    for err in report.errors:
        if err.suggested_retry:
            return {"code": err.code, **err.suggested_retry}
    if report.errors:
        return {"code": report.errors[0].code}
    return None


class QualityGateError(RuntimeError):
    """An elevated-policy gate failed; the write was withheld (fail-closed)."""

    def __init__(self, report: Any) -> None:
        block = visual_complete_block(report)
        self.report = report
        self.block = block
        self.code = (block["errorCodes"] or ["VISUAL_COMPLETE_FAILED"])[0]
        message = "; ".join(e["message"] for e in block["errors"]) or "visual_complete gate failed"
        _record_gate_error(self)
        super().__init__(message)


def save_through_pipeline(document: Any, output_path: Any, *, quality: Any = None) -> Any:
    """Save *document* through the SavePipeline; return the ``VisualCompleteReport``.

    Raises :class:`QualityGateError` when the gate fails (so the caller withholds
    the output — fail-closed). Open-safety serialize failures still raise the
    library's ``ValueError`` as before.
    """

    # Accept a ready QualityPolicy, or resolve None/str/dict into one.
    if quality is None or isinstance(quality, (str, Mapping)):
        policy = resolve_policy(quality)
    else:
        policy = quality
    from .office.rendering import bind_document_rendering, save_gate_report

    with bind_document_rendering(document):
        report = save_gate_report(document, output_path, quality=policy)
    if not report.ok:
        raise QualityGateError(report)
    return report


# --------------------------------------------------------------------------- #
# Capability handshake (fail-closed on skew).
# --------------------------------------------------------------------------- #
def capability_state() -> dict[str, Any]:
    """Core/automation/plugin versions + a fingerprint hash + any version skew."""

    core = package_version("python-hwpx")
    automation = package_version("python-hwpx-automation")
    plugin = os.environ.get("HWPX_SKILL_VERSION", "unknown")
    has_pipeline = _quality_available()

    skew: list[str] = []
    if not has_pipeline:
        skew.append("python-hwpx is missing the hwpx.quality SavePipeline gate")
    elif _version_lt(core, MIN_PYTHON_HWPX):
        skew.append(f"python-hwpx {core} < required {MIN_PYTHON_HWPX}")
    if automation == "unknown":
        skew.append("python-hwpx-automation version is unresolved")
    elif _version_lt(automation, MIN_AUTOMATION_VERSION):
        skew.append(
            f"python-hwpx-automation {automation} < required {MIN_AUTOMATION_VERSION}"
        )
    if plugin != "unknown" and _version_lt(plugin, MIN_SKILL_VERSION):
        skew.append(f"hwpx skill {plugin} < required {MIN_SKILL_VERSION}")

    fingerprint = hashlib.sha256(
        "|".join(
            [
                "core", core,
                "automation", automation,
                "plugin", plugin,
                "pipeline", str(has_pipeline),
                "toolContract", contract_hash(),
            ]
        ).encode()
    ).hexdigest()[:16]

    return {
        "versions": {
            "core": core,
            "automation": automation,
            # 6.x compatibility alias.
            "mcp": automation,
            "plugin": plugin,
        },
        "minPythonHwpx": MIN_PYTHON_HWPX,
        "minAutomationVersion": MIN_AUTOMATION_VERSION,
        # 6.x compatibility alias.
        "minMcpVersion": MIN_MCP_VERSION,
        "minSkillVersion": MIN_SKILL_VERSION,
        "savePipelineAvailable": has_pipeline,
        "toolContractHash": contract_hash(),
        "hash": fingerprint,
        "skew": skew,
        "ok": not skew,
    }


def fail_closed_enabled() -> bool:
    return env_value("REQUIRE_CAPABILITY", "1") != "0"


def assert_write_capability() -> None:
    """Raise :class:`QualityGateError`-style failure if capability is skewed.

    Fail-closed: a write must not proceed when the installed quality stack can't
    honour the gate (e.g. a stale python-hwpx). Disable with
    ``HWPX_AUTOMATION_REQUIRE_CAPABILITY=0`` for an expert/debug bypass. The
    old ``HWPX_MCP_REQUIRE_CAPABILITY`` spelling remains a 6.x fallback.
    """

    if not fail_closed_enabled():
        return
    state = capability_state()
    if not state["ok"]:
        raise CapabilitySkewError(state)


class CapabilitySkewError(RuntimeError):
    """The core/automation/plugin handshake detected skew; writes fail closed."""

    code = "CAPABILITY_SKEW"

    def __init__(self, state: Mapping[str, Any]) -> None:
        self.state = dict(state)
        _record_gate_error(self)
        super().__init__("; ".join(state.get("skew", [])) or "capability skew detected")


__all__ = [
    "MIN_PYTHON_HWPX",
    "resolve_policy",
    "save_through_pipeline",
    "visual_complete_block",
    "QualityGateError",
    "CapabilitySkewError",
    "capability_state",
    "assert_write_capability",
    "fail_closed_enabled",
    "package_version",
]
