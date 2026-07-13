# 서버 강제 자율 HWPX workflow

일반적인 복합 문서 작업은 primitive를 직접 조합하지 말고 아래 7개 고수준 도구로 시작한다.

1. `start_workflow`에 typed work order를 제출한다.
2. `get_workflow`로 현재 영수증을 읽고 `continue_workflow`를 한 durable 경계씩 호출한다.
3. 상태가 `decision`일 때만 영수증의 action hash를 확인하고 `approve_workflow_decision`을 호출한다.
4. 프로세스 재시작 뒤에는 `resume_workflow`를 쓴다. 취소는 `cancel_workflow`를 쓴다.
5. `completed`, `needs_review`, `failed`, `cancelled` 중 하나가 되면 멈춘다.
6. terminal 영수증의 `result`가 `null`이고 `resultRef`가 있으면
   `get_workflow_result(workflow_id, action_hash)`로 암호화 저장된 원 결과를 회수하고
   `contentHash`를 대조한다. 보존기간이 끝난 결과는 복구됐다고 추정하지 않는다.

모든 mutation은 원본과 다른 `output_path`를 사용한다. `DISPATCH_IN_DOUBT`, capability skew, stale revision,
예산 초과, 불충분한 openSafety는 우회하지 않는다.

실한컴 검증이 필수인 work order에는 `policy.require_real_hancom_render=true`를 설정한다. 서버는 `VERIFY`에서
렌더 job을 한 번만 제출하고, `queued`/`running` 동안 상태를 `VERIFY`에 둔 채 즉시 반환한다. 긴 호출로
기다리지 말고 이후 `continue_workflow` 또는 재시작 뒤 `resume_workflow`로 폴링한다. 일치하는 실한컴
성공 receipt가 없으면 `completed`로 우회하지 않고 `needs_review`/unverified를 그대로 보고한다.

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
- `completed`: `artifacts`, 실제 `result` 또는 `resultRef`, `semanticDiff`, `domainVerification`,
  `openSafety`, `verificationStatus`, `versions`, `toolSpecHash`를 확인한다.
- family별 필수 검증은 편집=`doc_diff`, 알려진/처음 보는 양식=`inspect_fill_residue`+
  `verify_form_fill`, typed 생성=`inspect_document_authoring_quality`(공문은
  `inspect_official_document_style` 추가)다. 하나라도 누락·실패하면 `completed`가 아니라
  `needs_review`여야 한다.
- `policy.require_real_hancom_render=false`인 영수증의 `openSafety.renderChecked=false`는 구조적 열림 안전
  증거일 뿐 실한컴 검수가 아니다. `renderChecked=false`인 결과를 시각 검수 완료라고 주장하지 않는다.

workflow DB의 work order와 action result는 AES-256-GCM으로 암호화되고 terminal에서 parameters가
삭제된다. 운영 환경은 `HWPX_WORKFLOW_ENCRYPTION_KEY`(URL-safe base64 32바이트)를 비밀 저장소에서
주입한다. 미지정 시 DB 옆 0600 key file을 쓰며, result는 기본 24시간·최대 30일 보존 후 purge된다.
