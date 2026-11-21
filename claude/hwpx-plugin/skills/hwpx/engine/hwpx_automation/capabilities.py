"""Task-oriented capability report derived from the FastMCP ToolSpec contract."""

from __future__ import annotations

from typing import Any

from .tool_contract import (
    DOMAIN_SPECS,
    TOOL_SPECS,
    bound_tool_registry,
    contract_hash,
    expected_tool_names,
)


# Backward-compatible data shape for callers that imported DOMAINS directly.
DOMAINS: list[dict[str, Any]] = [
    {
        "key": domain.key,
        "title": domain.title,
        "intent": domain.intent,
        "whenToUse": domain.when_to_use,
        "tools": list(domain.tools),
    }
    for domain in DOMAIN_SPECS
]


def build_capability_report(
    domain: str | None = None,
    *,
    advanced: bool = False,
) -> dict[str, Any]:
    """Return only tools callable on the active FastMCP profile."""

    active = expected_tool_names(advanced=advanced)
    specs = {spec.name: spec for spec in TOOL_SPECS}
    bound = bound_tool_registry().by_name()
    selected = DOMAIN_SPECS if domain is None else tuple(item for item in DOMAIN_SPECS if item.key == domain)
    out_domains: list[dict[str, Any]] = []
    for item in selected:
        tools = [name for name in item.tools if name in active]
        if not tools and domain is None:
            continue
        out_domains.append(
            {
                "key": item.key,
                "title": item.title,
                "intent": item.intent,
                "whenToUse": item.when_to_use,
                "toolCount": len(tools),
                "tools": tools,
                "toolDetails": [
                    {
                        "name": name,
                        "lifecycle": specs[name].classification.value,
                        "profile": specs[name].profile.value,
                        "availability": bound[name].availability.value,
                        "mutates": specs[name].mutates,
                        "tags": list(specs[name].tags),
                        "replacementTools": list(specs[name].replacement_tools),
                    }
                    for name in tools
                ],
            }
        )
    return {
        "domains": out_domains,
        "domainCount": len(out_domains),
        "profile": "advanced" if advanced else "default",
        "contractHash": contract_hash(),
        "note": (
            "실제 FastMCP 등록 표면의 작업군 지도. isolated legacy testkit와 internal fixture QA는 "
            "호출 가능 도구 수에 포함하지 않는다. 양식 채움은 analyze_form_fill → apply_form_fill → "
            "verify_form_fill canonical 경로를 따른다."
        ),
    }


def coverage_against(
    tool_names: set[str],
    *,
    advanced: bool = False,
    registry_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare a live registry to the exact active ToolSpec set."""

    expected = expected_tool_names(advanced=advanced)
    missing = sorted(expected - tool_names)
    unexpected = sorted(tool_names - expected)
    registry_ok = True if registry_validation is None else bool(registry_validation.get("ok"))
    return {
        "missingExpected": missing,
        "unexpectedRegistered": unexpected,
        # Compatibility keys retained for older health consumers/tests.
        "unmapped": unexpected,
        "mappedNotRegistered": missing,
        "registryValidation": registry_validation,
        "ok": not missing and not unexpected and registry_ok,
    }


def tool_domain(name: str) -> str | None:
    for spec in TOOL_SPECS:
        if spec.name == name:
            return spec.domain
    return None


def core_self_description() -> dict[str, Any]:
    """설치된 core의 `hwpx.capabilities/v1` 자기서술 — 없으면 정직 degrade.

    core 5.6+가 제공한다. 구버전 core 위에서는 없다는 사실 자체를 보고하지,
    자기서술을 지어내지 않는다.
    """

    try:
        from hwpx.experimental import describe_capabilities as core_caps
    except ImportError:
        return {
            "available": False,
            "reason": (
                "installed python-hwpx does not expose hwpx.capabilities "
                "(needs >= 5.6.0)"
            ),
        }
    report = dict(core_caps())
    report["available"] = True
    return report


def render_oracle_availability() -> dict[str, Any]:
    """실한컴 렌더 오라클 가용성 — **무실행 프로브만**(세션·렌더 발사 없음).

    resolve_oracle 캐스케이드(Windows COM → Mac GUI → Null; STRUCTURAL_ONLY는
    Null 단락)와 imaging/pymupdf 프로브를 그대로 보고한다. available=False는
    결함이 아니라 이 환경의 사실이며, 그때 render 게이트는 renderChecked=false
    로 정직하게 degrade한다.
    """

    from .office.rendering import detectors, diff
    from .office.rendering.oracle import resolve_oracle

    oracle = resolve_oracle()
    try:
        available = bool(oracle.available())
    except Exception:
        available = False
    return {
        "oracle": type(oracle).__name__,
        "available": available,
        "imaging": bool(detectors.imaging_available()),
        "pymupdf": bool(diff.pymupdf_available()),
        "note": "probe-only — 어떤 렌더 세션도 시작하지 않는다",
    }


__all__ = [
    "DOMAINS",
    "build_capability_report",
    "core_self_description",
    "coverage_against",
    "render_oracle_availability",
    "tool_domain",
]
