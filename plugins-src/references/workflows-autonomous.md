# 서버 강제 자율 HWPX workflow

일반적인 복합 문서 작업은 primitive를 직접 조합하지 말고 아래 6개 고수준 도구로 시작한다.

1. `start_workflow`에 typed work order를 제출한다.
2. `get_workflow`로 현재 영수증을 읽고 `continue_workflow`를 한 durable 경계씩 호출한다.
3. 상태가 `decision`일 때만 영수증의 action hash를 확인하고 `approve_workflow_decision`을 호출한다.
4. 프로세스 재시작 뒤에는 `resume_workflow`를 쓴다. 취소는 `cancel_workflow`를 쓴다.
5. `completed`, `needs_review`, `failed`, `cancelled` 중 하나가 되면 멈춘다.

모든 mutation은 원본과 다른 `output_path`를 사용한다. `DISPATCH_IN_DOUBT`, capability skew, stale revision,
예산 초과, 불충분한 openSafety는 우회하지 않는다.

## 5개 family 입력

공통 필드는 `family`, 8자 이상의 `idempotency_key`, 선택적 `budget`·`policy`다. 기존 문서 작업은
`source_path`, mutation은 별도 `output_path`를 준다. `expected_revision`을 생략하면 서버가 intake에서
현재 revision을 고정한다.

### 읽기·추출

```json
{"family":"read_extract","idempotency_key":"read-2026-001","source_path":"/docs/a.hwpx","parameters":{"operation":"info"}}
```

`operation`은 `text`, `info`, `outline`, `map`, `markdown`, `json` 중 하나다.

### 트랜잭션 편집

```json
{"family":"transactional_edit","idempotency_key":"edit-2026-001","source_path":"/docs/a.hwpx","output_path":"/docs/a-edited.hwpx","parameters":{"operations":[{"op":"replace_text","find":"기존","replace":"수정"}]}}
```

### 승인된 템플릿 채움

```json
{"family":"known_template_fill","idempotency_key":"known-form-001","source_path":"/forms/blank.hwpx","output_path":"/forms/filled.hwpx","parameters":{"baseline":{"schema":"approved"},"content":{"성명":"홍길동"}}}
```

### 처음 보는 양식 채움

```json
{"family":"unknown_form_fill","idempotency_key":"unknown-form-001","source_path":"/forms/blank.hwpx","output_path":"/forms/filled.hwpx","parameters":{"operationKind":"table","operations":[{"op":"fill_cell","table_index":0,"row":1,"col":1,"text":"홍길동"}]}}
```

`operationKind`는 `table` 또는 `body`다. 이 family는 recon과 plan 뒤 destructive decision을 요구한다.

### typed 문서 생성

```json
{"family":"typed_authoring","idempotency_key":"author-2026-001","output_path":"/docs/new.hwpx","parameters":{"documentPlan":{"schemaVersion":"hwpx.document_plan.v2","title":"계획","sections":[]}}}
```

## decision과 terminal 영수증

- `decision`: `decisions`/계획의 `actionHash`를 확인한다. 사용자 또는 정책 소유자의 승인을 추정하지 않는다.
- `needs_review`: `stopReason`과 `unresolvedFindings`를 그대로 보고하고 primitive로 우회하지 않는다.
- `completed`: `artifacts`, `semanticDiff`, `openSafety`, `verificationStatus`, `versions`, `toolSpecHash`를 확인한다.
- S-067의 모든 영수증은 `openSafety.renderChecked=false`다. 이는 구조적 열림 안전 증거일 뿐 실한컴 렌더
  검수가 아니다. `renderChecked=false`인 결과를 시각 검수 완료 또는 최종 제출 가능이라고 주장하지 않는다.
