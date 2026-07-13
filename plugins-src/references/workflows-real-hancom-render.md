# 비동기 실한컴 렌더

실제 한컴 렌더가 필요한 제출 후보에만 이 경로를 쓴다. `render_preview`나 deterministic fake는
`realHancom`/`renderChecked` 증거가 아니며 대체할 수 없다.

## 절차

원격 큐의 기본 transport는 mTLS다. MCP 쪽에 `HWPX_RENDER_QUEUE_URL`,
`HWPX_RENDER_QUEUE_SECRET`, `HWPX_RENDER_CA_FILE`, `HWPX_RENDER_CLIENT_CERT_FILE`,
`HWPX_RENDER_CLIENT_KEY_FILE`을 설정한다. 큐 서비스는 서버 인증서/키와 `--client-ca`를 받아
클라이언트 인증서를 필수 검증하며 private/loopback 주소에만 bind한다. mTLS를 쓸 수 없는 명시적
대안만 `HWPX_RENDER_TRANSPORT_AUTH=signed_https`와 서버 `--transport-auth signed_https`를 함께 쓴다.
단순 HTTPS를 mTLS라고 보고하지 않는다.

1. `render_health()`를 호출한다. `available=true`, `degraded=false`와 fresh worker/Hancom 정보를 확인한다.
   미구성, stale heartbeat, queue 장애이면 결과를 `unverified`로 보류하고 아래 degraded 절차를 따른다.
2. `render_submit(filename, idempotency_key, workflow_id?, dpi=144)`를 한 번 호출한다. 응답의
   `receipt.job_id`, `input_content_hash`, `status`를 보관한다. 같은 작업의 재시도에는 같은
   `idempotency_key`를 사용한다.
3. MCP 호출을 열어 둔 채 기다리지 않는다. `render_status(job_id)`를 적당한 간격으로 한 번씩 호출한다.
   `queued`/`running`이면 나중에 다시 조회한다. `succeeded`일 때만
   `render_status(job_id, output_dir=<별도 디렉터리>)`로 PDF와 페이지 PNG를 저장한다.
4. 성공 receipt에서 다음을 모두 확인한다.

   - `schema_version == "hwpx.render.v2"`, `status == "succeeded"`, `render_checked == true`
   - `input_content_hash`가 제출한 HWPX의 SHA-256과 일치
   - `backend`, `hancom_build`, `worker_version`, `queued_at`, `started_at`, `completed_at`
   - PDF 1개와 연속된 page PNG의 `content_hash`, `size_bytes`, `page_count`
   - `savedArtifacts[].contentHash`가 receipt artifact hash와 일치

   하나라도 없거나 불일치하면 실한컴 검증 완료로 취급하지 않는다.
5. 더 이상 필요 없는 `queued`/`running` job은 `render_cancel(job_id)`로 취소한다. `cancelled` receipt를
   확인할 때까지 성공으로 간주하지 않는다.

## degraded·실패 처리

- `render_health`가 unavailable/degraded이거나 `render_status`가 job unavailable을 반환하면
  `unverified`/`needs_review`로 종료하고 `degradedReason`·`errorCode`를 보존한다.
- `failed`, `unavailable`, `cancelled`는 terminal이지만 성공이 아니다. `terminal_reason`을 그대로 보고한다.
- local `render_preview` 성공, 구조 검증, 비전 판단만으로 `render_checked=true`를 추정하지 않는다.
- workflow에서는 `policy.require_real_hancom_render=true`를 사용한다. `VERIFY`의 queued/running은
  defer 상태이므로 `continue_workflow`/`resume_workflow`로 재개하고 primitive로 완료 상태를 우회하지 않는다.
