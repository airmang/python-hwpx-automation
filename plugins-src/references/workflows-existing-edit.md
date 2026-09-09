# 기존 문서 편집: 조회에서 검증까지

`get_document_map(detail="summary")`는 JSON 본문 16,000자, 목록별 24개,
미리보기 텍스트별 256자를 상한으로 사용합니다. `summaryCoverage`는 전체 개수,
`truncated`는 생략 여부입니다. `targetSelectionComplete`는 항상 false입니다.
짧은 지도만 보고 라벨의 유일성을 단정하지 마세요. 기존 full 지도는 그대로입니다.

`continuation`이 안내하는 `get_document_node`에 현재 `expected_revision`을
전달해 상세 노드를 읽습니다. 목록에서 생략된 자식은 1부터 시작하는
`kind[index]` 경로로 읽을 수 있습니다. 응답은 편집에 사용할 정식 경로를
돌려줍니다. 이 보조 경로는 조회에만 적용하며, 쓰기 대상은 정식 경로여야 합니다.
문서가 바뀌면 재조회하고 계획을 다시 만드세요.

Python의 `apply_mixed_form_fill`, CLI의 `hwpx batch`, MCP의 `apply_form_fill`은
기존 `hwpx.mixed-form-plan/v1` 요청을 같은 도메인에서 실행합니다. CLI는
`hwpx.mixed-form-compiled-plan/v1`도 해당 도메인으로 전달합니다. 원본·출력
분리, 현재 revision, 정확한 대상 조건, 동일 멱등성 키를 사용하세요. 원본을
사본 경로로 편집하고 patch/error 보존 저장과 요청값 재검증을 요구하세요.

`bodyAnchor.expectedCount`는 정확히 1입니다. MCP는 잘못된 값(예: 2)을 공개
스키마에서 `INVALID_ARGUMENT`로 거부하며, Python·CLI는 도메인 검증에서 거부합니다.
실제 일치 개수가 0 또는 복수일 때도 추측해 쓰지 않습니다. JSONL 한 호출 안의
동일 키 재시도는 원자 계획의 기존 멱등성 저장소를 공유합니다.

구조 검증과 실제 한컴 화면 검증은 서로 다른 결과입니다. `openSafety` 통과를
페이지 배치·잘림·겹침이 확인되었다는 뜻으로 사용하지 마세요.
