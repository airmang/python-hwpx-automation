# SPDX-License-Identifier: Apache-2.0
"""MCP resources 표면 — 계약 문서·스키마 구독 .

에이전트가 도구 호출 없이 계약을 구독한다: core가 wheel에 동봉한 계약 문서
4종(`hwpx.capabilities.contract_document`)과 라이브 빌드 JSON Schema 4종
(`contract_json_schema`), 그리고 automation 자신의 도구 계약 payload.

SDK 접근은 :mod:`hwpx_automation.fastmcp_adapter`의
``register_canonical_resource`` seam으로만 한다(architecture ratchet — 다른
모듈의 SDK 내부 접근 금지). 콘텐츠는 요청 시 로드된다(라이브 — 파일 박제 없음,
core 문서는 설치된 core 배포본이 진실).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


def _core_document(name: str) -> Callable[[], str]:
    def load() -> str:
        from hwpx.capabilities import contract_document

        return contract_document(name)

    return load


def _core_schema(name: str) -> Callable[[], str]:
    def load() -> str:
        from hwpx.capabilities import contract_json_schema

        return json.dumps(contract_json_schema(name), ensure_ascii=False, indent=2)

    return load


def _tools_contract() -> str:
    from .tool_contract import contract_payload

    return json.dumps(contract_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class ResourceSpec:
    uri: str
    name: str
    description: str
    mime_type: str
    loader: Callable[[], str]


CANONICAL_RESOURCES: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        uri="hwpx://contract/support-matrix",
        name="support-matrix",
        description="python-hwpx 지원 매트릭스 — 능력 영역별 상태·증거 (core 동봉본)",
        mime_type="text/markdown",
        loader=_core_document("support-matrix"),
    ),
    ResourceSpec(
        uri="hwpx://contract/recipes-traversal",
        name="recipes-traversal",
        description="문서 순회·읽기 태스크 레시피 (core 동봉본)",
        mime_type="text/markdown",
        loader=_core_document("recipes-traversal"),
    ),
    ResourceSpec(
        uri="hwpx://contract/mutation-semantics",
        name="mutation-semantics",
        description="편집 op별 실측 의미론·캐비앗 표 (core 동봉본)",
        mime_type="text/markdown",
        loader=_core_document("mutation-semantics"),
    ),
    ResourceSpec(
        uri="hwpx://contract/known-traps",
        name="known-traps",
        description="에이전트가 실제로 밟아 본 함정 사전 (core 동봉본)",
        mime_type="text/markdown",
        loader=_core_document("known-traps"),
    ),
    ResourceSpec(
        uri="hwpx://schemas/edit-plan-v1",
        name="edit-plan-v1",
        description="hwpx.edit-plan/v1 JSON Schema — run_edit_plan 입력 계획 (라이브 빌드)",
        mime_type="application/json",
        loader=_core_schema("hwpx.edit-plan/v1"),
    ),
    ResourceSpec(
        uri="hwpx://schemas/plan-report-v1",
        name="plan-report-v1",
        description="hwpx.plan-report/v1 JSON Schema — run_edit_plan 결과 (라이브 빌드)",
        mime_type="application/json",
        loader=_core_schema("hwpx.plan-report/v1"),
    ),
    ResourceSpec(
        uri="hwpx://schemas/mutation-report-v1",
        name="mutation-report-v1",
        description="hwpx.mutation-report/v1 JSON Schema — 안전-쓰기 영수증 (라이브 빌드)",
        mime_type="application/json",
        loader=_core_schema("hwpx.mutation-report/v1"),
    ),
    ResourceSpec(
        uri="hwpx://schemas/capabilities-v1",
        name="capabilities-v1",
        description="hwpx.capabilities/v1 JSON Schema — core 자기서술 (라이브 빌드)",
        mime_type="application/json",
        loader=_core_schema("hwpx.capabilities/v1"),
    ),
    ResourceSpec(
        uri="hwpx://contract/tools",
        name="tool-contract",
        description="python-hwpx-automation 도구 계약 payload(버전 플로어·도구 전 레코드·해시 입력)",
        mime_type="application/json",
        loader=_tools_contract,
    ),
)


def register_canonical_resources(mcp: object) -> int:
    """카탈로그의 모든 리소스를 어댑터 seam으로 등록하고 개수를 돌려준다.

    어댑터는 여기서 지연 import한다 — 카탈로그 자체(이 모듈)는 MCP SDK 없는
    base-public 설치에서도 import 가능해야 한다(public-modules 경계).
    """

    from .fastmcp_adapter import register_canonical_resource

    for spec in CANONICAL_RESOURCES:
        register_canonical_resource(
            mcp,
            uri=spec.uri,
            name=spec.name,
            description=spec.description,
            mime_type=spec.mime_type,
            func=spec.loader,
        )
    return len(CANONICAL_RESOURCES)
