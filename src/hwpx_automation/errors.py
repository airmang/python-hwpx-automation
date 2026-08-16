# SPDX-License-Identifier: Apache-2.0
"""공통 에러 모델과 MCP 에러 변환 유틸리티."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ErrorCategory = Literal[
    "validation",
    "permission",
    "not_found",
    "capability",
    "document",
    "network",
    "internal",
]


class CommonErrorModel(BaseModel):
    """클라이언트가 일관되게 처리할 수 있는 공통 에러 페이로드."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal["hwpx.mcp-error/v1"] = Field(
        default="hwpx.mcp-error/v1", alias="schemaVersion"
    )
    code: str
    category: ErrorCategory
    message: str
    retryable: bool = False
    details: Optional[Dict[str, Any]] = None
    hint: Optional[str] = None
    suggestion: Optional[str] = None


ERROR_CODE_TO_MCP_CODE: dict[str, int] = {
    "CLIENT_UPLOAD_PATH_UNAVAILABLE": -32602,
    "DOCUMENT_NOT_FOUND": -32044,
    "PERMISSION_DENIED": -32043,
    "TABLE_INDEX_OUT_OF_RANGE": -32042,
    "PARAGRAPH_INDEX_OUT_OF_RANGE": -32042,
    "PIPELINE_ERROR": -32041,
    "WORKSPACE_OUTSIDE_ROOT": -32043,
    "WORKSPACE_SYMLINK_ESCAPE": -32043,
    "WORKSPACE_ROOT_INVALID": -32043,
    "WORKSPACE_PATH_INVALID": -32602,
    "INVALID_ARGUMENT": -32602,
    "NETWORK_DESTINATION_DENIED": -32040,
}


DEFAULT_MCP_ERROR_CODE = -32000


DEFAULT_ERROR_SUGGESTIONS: dict[str, str] = {
    "AMBIGUOUS_TARGET": "검색 조건을 더 구체화하거나 limit=1로 미리보기를 다시 생성하세요.",
    "BYTE_PATCH_OPEN_SAFETY_FAILED": "반환된 openSafety 진단을 확인하고 일반 저장/복구 경로로 다시 생성하세요.",
    "CAPABILITY_SKEW": "core/automation/plugin ToolSpec 계약 불일치로 쓰기가 차단되었습니다. mcp_server_health의 최소 버전과 contract hash에 맞춰 다시 설치한 뒤 호스트를 재시작하세요.",
    "CLIENT_UPLOAD_PATH_UNAVAILABLE": "대화에 업로드된 파일의 내부 경로는 로컬 MCP 서버에서 읽을 수 없습니다. 파일을 PC에 저장한 뒤 실제 로컬 경로를 전달하세요.",
    "FIELD_OVERFLOW": "값이 칸에 넘칩니다. fitPolicy(mode=wrap_then_shrink/shrink/truncate_with_report) 또는 overflow=warn으로 다시 채우거나 값을 줄이세요. details.visualComplete.suggestedRetry 참고.",
    "STALE_LINESEG_DETECTED": "오래된 lineseg 레이아웃 캐시가 남았습니다. 해당 문단을 다시 편집해 캐시를 무효화한 뒤 저장하세요.",
    "VISUAL_COMPLETE_FAILED": "한컴 렌더에서 겹침/넘침 등 시각 결함이 감지되었습니다. details.visualComplete를 확인하고 수정 후 다시 저장하세요.",
    "REQUIRED_FIELD_MISSING": "필수 폼 필드가 비어 있습니다. 값을 채운 뒤 다시 저장하세요.",
    "TABLE_STRUCTURE_INVALID": "표 구조가 한컴 필수 요소를 누락했습니다. repair_hwpx로 복구하거나 표를 다시 생성하세요.",
    "BYTE_PATCH_UNAVAILABLE": "설치된 python-hwpx 버전을 확인한 뒤 플러그인을 다시 설치하거나 일반 편집 도구를 사용하세요.",
    "CONFLICTING_TARGETS": "동일 범위를 겹쳐 수정하지 않도록 edit 목록을 분리해 다시 실행하세요.",
    "DOCUMENT_LOCATOR_REQUIRED": "path 또는 handleId 중 하나를 지정한 뒤 같은 작업을 다시 호출하세요.",
    "DOCUMENT_NOT_FOUND": "문서 경로가 허용된 workspace root 안에 존재하는지 확인하고 절대/상대 경로를 다시 전달하세요.",
    "DOCUMENT_OPEN_FAILED": "파일이 유효한 HWPX인지 확인하고 repair_hwpx로 복구한 뒤 다시 여세요.",
    "DOCUMENT_SAVE_FAILED": "출력 경로의 쓰기 권한과 남은 디스크 공간을 확인한 뒤 다시 저장하세요.",
    "EMPTY_MATCH": "찾을 텍스트나 앵커 조건을 실제 문서 내용에 맞게 수정하세요.",
    "HWP_CONVERSION_FAILED": "원본 HWP가 손상되지 않았는지 확인하고 변환 로그의 원인을 기준으로 다시 시도하세요.",
    "HWP_TEXT_EXTRACT_FAILED": "HWP 파일을 다른 뷰어에서 열어 유효성을 확인한 뒤 텍스트 추출을 다시 실행하세요.",
    "IDEMPOTENT_REPLAY": "이미 적용된 planId입니다. 최신 preview/plan을 새로 만든 뒤 apply를 다시 호출하세요.",
    "MEMO_NOT_FOUND": "list_memos 또는 문서 리소스에서 memoId를 다시 확인한 뒤 호출하세요.",
    "MISSING_NODE": "대상 섹션, 문단, 표, 셀이 아직 존재하는지 조회한 뒤 새 앵커로 다시 실행하세요.",
    "PARAGRAPH_INDEX_OUT_OF_RANGE": "list_paragraphs 결과의 paragraphIndex 범위 안에서 다시 선택하세요.",
    "PERMISSION_DENIED": "허용된 workspace root와 파일 권한을 확인하고 쓰기 가능한 위치를 사용하세요.",
    "PIPELINE_ERROR": "details.pipelineCode와 hint를 확인한 뒤 preview부터 다시 생성하세요.",
    "PLAN_RECORD_MISSING": "preview_edit 또는 plan_edit으로 planId를 새로 발급받은 뒤 apply를 다시 호출하세요.",
    "PREVIEW_REQUIRED": "preview_edit으로 변경 내용을 확인한 뒤 반환된 planId로 apply_edit을 호출하세요.",
    "READ_ONLY_HWP_DOCUMENT": "HWP 바이너리는 직접 저장할 수 없습니다. 먼저 HWPX로 변환한 뒤 편집하세요.",
    "RENDER_PREVIEW_INVALID_MODE": "mode는 'pages' 또는 'long'으로 지정한 뒤 다시 실행하세요.",
    "RENDER_PREVIEW_INVALID_SCREENSHOT_MODE": "screenshot은 'auto', 'require', 'off' 중 하나로 지정하세요.",
    "RENDER_PREVIEW_UNAVAILABLE": "matching python-hwpx 버전을 설치하고 MCP 서버를 새로 시작한 뒤 다시 실행하세요.",
    "RANGE_OUT_OF_BOUNDS": "문단/문자 범위를 최신 문서 기준으로 다시 계산한 뒤 실행하세요.",
    "REPAIR_UNAVAILABLE": "설치된 python-hwpx에 repair helper가 있는지 확인하고 플러그인을 다시 설치하세요.",
    "SOURCE_FILE_TYPE_INVALID": "source에는 .hwp 파일을 전달하거나 HWPX 도구에는 .hwpx 경로를 사용하세요.",
    "STYLE_BORDER_FILL_HEADER_MISSING": "문서 스타일 헤더가 손상되었습니다. repair_hwpx를 실행한 뒤 다시 시도하세요.",
    "STYLE_CHAR_PROPERTY_ID_MISSING": "문서 문자 스타일 정의를 복구한 뒤 formatting 작업을 다시 실행하세요.",
    "STYLE_HEADER_MISSING": "문서 style.xml/header 구성이 유효한지 확인하고 repair_hwpx를 먼저 실행하세요.",
    "STYLE_ID_ALLOCATOR_MISSING": "문서 스타일 ID 할당 정보를 복구하거나 새 문서로 내용을 옮긴 뒤 다시 시도하세요.",
    "TABLE_CELL_INDEX_OUT_OF_RANGE": "list_tables 결과로 행/열 범위를 확인한 뒤 유효한 셀 좌표를 사용하세요.",
    "TABLE_CELL_OPERATION_FAILED": "병합 셀 구조와 행/열 좌표를 확인하고 단일 셀 대상으로 다시 실행하세요.",
    "TABLE_EMPTY": "표에 행과 셀이 있는지 확인하고 비어 있으면 표를 다시 생성하세요.",
    "TABLE_INDEX_OUT_OF_RANGE": "list_tables 결과의 tableIndex 범위 안에서 다시 선택하세요.",
    "UNSAFE_WILDCARD": "와일드카드 범위를 줄이거나 정확한 문자열 매칭으로 preview를 다시 생성하세요.",
    "WORKSPACE_OUTSIDE_ROOT": "mcp_server_health의 workspace.roots 안에 있는 경로를 사용하거나 호스트의 HWPX_AUTOMATION_WORKSPACE_ROOTS 설정을 갱신하세요(HWPX_MCP_WORKSPACE_ROOTS도 6.x에서 지원).",
    "WORKSPACE_SYMLINK_ESCAPE": "작업공간 밖을 가리키는 심볼릭 링크를 제거하고 허용된 루트 안의 실제 경로를 사용하세요.",
    "WORKSPACE_ROOT_INVALID": "기존 디렉터리를 HWPX_AUTOMATION_WORKSPACE_ROOTS JSON 배열로 지정한 뒤 호스트를 다시 시작하세요(HWPX_MCP_WORKSPACE_ROOTS도 6.x에서 지원).",
    "WORKSPACE_PATH_INVALID": "비어 있지 않은 파일 경로를 지정하고 출력에는 디렉터리가 아닌 파일명을 사용하세요.",
    "INVALID_ARGUMENT": "도구 스키마에 맞는 인자 형식과 값을 확인한 뒤 다시 호출하세요.",
    "NETWORK_DESTINATION_DENIED": "기본 정책은 사설·루프백·링크로컬·예약 주소를 차단합니다. 신뢰된 사설 서비스가 꼭 필요할 때만 명시적 private-network opt-in을 사용하세요.",
    "TOOL_EXECUTION_FAILED": "같은 입력을 반복하기 전에 오류 범주와 서버 상태를 확인하세요. 재현되면 민감정보를 제거한 최소 사례로 보고하세요.",
}


def category_for_error(error_code: str) -> ErrorCategory:
    if error_code in {
        "WORKSPACE_OUTSIDE_ROOT",
        "WORKSPACE_SYMLINK_ESCAPE",
        "WORKSPACE_ROOT_INVALID",
        "PERMISSION_DENIED",
    }:
        return "permission"
    if error_code in {"DOCUMENT_NOT_FOUND", "PLAN_RECORD_MISSING", "MEMO_NOT_FOUND"}:
        return "not_found"
    if error_code in {"CAPABILITY_SKEW", "REPAIR_UNAVAILABLE", "BYTE_PATCH_UNAVAILABLE"}:
        return "capability"
    if error_code.startswith("NETWORK_"):
        return "network"
    if error_code in {
        "CLIENT_UPLOAD_PATH_UNAVAILABLE",
        "INVALID_ARGUMENT",
        "WORKSPACE_PATH_INVALID",
        "DOCUMENT_LOCATOR_REQUIRED",
        "RANGE_OUT_OF_BOUNDS",
        "TABLE_INDEX_OUT_OF_RANGE",
        "PARAGRAPH_INDEX_OUT_OF_RANGE",
    }:
        return "validation"
    if error_code in {"TOOL_EXECUTION_FAILED", "INTERNAL_ERROR"}:
        return "internal"
    return "document"


def mcp_code_for_error(error_code: str) -> int:
    return ERROR_CODE_TO_MCP_CODE.get(error_code, DEFAULT_MCP_ERROR_CODE)


def suggestion_for_error(
    error_code: str,
    *,
    details: Optional[Dict[str, Any]] = None,
    hint: Optional[str] = None,
) -> Optional[str]:
    if error_code == "PIPELINE_ERROR" and details:
        pipeline_code = details.get("pipelineCode")
        if isinstance(pipeline_code, str):
            mapped = DEFAULT_ERROR_SUGGESTIONS.get(pipeline_code)
            if mapped:
                return mapped
    return DEFAULT_ERROR_SUGGESTIONS.get(error_code) or hint


def build_error_payload(
    *,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    hint: Optional[str] = None,
    suggestion: Optional[str] = None,
    category: Optional[ErrorCategory] = None,
    retryable: bool = False,
) -> Dict[str, Any]:
    return CommonErrorModel(
        code=code,
        category=category or category_for_error(code),
        message=message,
        retryable=retryable,
        details=details,
        hint=hint,
        suggestion=suggestion
        or suggestion_for_error(code, details=details, hint=hint),
    ).model_dump(exclude_none=True, by_alias=True)
