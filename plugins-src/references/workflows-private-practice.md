# 비공개 코퍼스 합성 문서편집 연습

이 경로는 운영자가 로컬의 비공개 practice root와 runner manifest를 서버 환경에 결합한 경우에만
사용한다. 에이전트는 원본 경로·파일명·split·lineage·평가 gold를 받지 않고 불투명 scenario ID와
합성 입력만 본다. 외부 모델이나 외부 저장소로 문서 내용을 전송하지 않는다.

## 단일 scenario 실행

1. `start_practice_scenario(scenario_id, idempotency_key)`를 호출한다.
   - `privateStorageCoordinatesExposed == false`인지 확인한다.
   - instruction, syntheticInputs, suggestedOperations, requiredOracles만 작업 입력으로 사용한다.
   - `syntheticInputs.synthetic != true`이거나 원본 좌표·평가 정답이 보이면 중단한다.
2. `apply_practice_scenario(..., use_suggested_operations=true, confirm=false)`로 decision preview를 받는다.
   - destination은 private practice root 밖의 새 `.hwpx` 경로여야 한다.
   - operationKind와 operationCount가 의도와 일치하는지 확인한다.
3. 사용자가 이미 허용한 연습 범위이고 계획이 맞을 때만 동일 인자로 `confirm=true`를 호출한다.
4. 반환 영수증에서 다음을 모두 확인한다.
   - `sourceArtifact.unchanged == true`
   - `openSafety.ok == true`
   - `domainVerification.ok == true`
   - `syntheticInputsOnly == true`
   - `privateStorageCoordinatesExposed == false`
5. `render.checked == false`이면 결과는 `structurally_verified_render_unverified`다. 이 상태를 시각 검증
   완료로 표현하지 않는다. 최종 시각 주장이 필요하면 별도로 `render_health` → `render_submit` →
   `render_status`를 실행하고 실제 한컴 provenance를 확인한다.

## Leap B 내구성 campaign 실행

캠페인 도구에는 경로 대신 불투명 `campaign_id`만 전달한다. 원본·practice root·manifest 위치를
추측하거나 도구 인자로 넘기지 않는다.
설치형 Claude/Codex 번들 런처는 `HWPX_SKILL_ROOT`를 번들 안의 실제 skill bytes에 결합한다.
운영자는 source/practice root와 runtime provenance를 private MCP 환경에서 별도로 준비해야 한다.
OpenClaw/Hermes는 설치된 skill 디렉터리를 `HWPX_SKILL_ROOT`로 명시한다. 이 좌표는 prompt나
영수증에 복사하지 않는다.

1. `start_practice_campaign(campaign_id, idempotency_key, confirm=false)`로 preview를 읽는다.
   - `requiresConfirmation == true`, `privateStorageCoordinatesExposed == false`, 예상 run 수와 manifest
     hash를 확인한다.
   - 범위가 맞을 때만 같은 `campaign_id`와 `idempotency_key`로 `confirm=true`를 호출한다.
2. `get_practice_campaign(campaign_id)`로 `counts`, `terminalReceiptCount`, `incompleteSlots`,
   `cancelRequested`를 조회한다. 프로세스 재시작 뒤에도 먼저 이 상태를 다시 읽는다.
3. `continue_practice_campaign(campaign_id, max_steps=8)`로 한 run씩 bounded advance한다.
   - 응답의 `boundary.decisionRequired == true`이면 `runId`와 `decisionReceiptSha256`를 보존하고,
     허용 범위를 검토한 뒤 같은 run에 `approved`와 정확한 receipt hash를 전달한다.
   - 재시작·재호출은 같은 run/receipt를 재사용해야 하며 중복 mutation을 새 성공으로 세지 않는다.
4. 새 claim을 중단해야 하면 `cancel_practice_campaign(campaign_id)`를 호출한다. 취소 요청은 자동으로
   되돌리지 않는다. 이미 terminal인 run의 영수증은 그대로 집계한다.
5. 모든 예정 run에 정확히 하나의 terminal receipt가 있을 때만
   `export_practice_campaign(campaign_id)`를 호출한다. `terminalReceiptCount == expectedRunCount`,
   manifest hash, `exportSha256`, `privateStorageCoordinatesExposed == false`를 확인한다.

## 결과를 정직하게 읽기

- campaign `state == "completed"`는 예정 run의 terminal accounting이 닫혔다는 뜻이다. 개별 run에
  `needs_review`, `refused`, `unverified`가 포함될 수 있으므로 전부 성공했다는 뜻이 아니다.
- `needs_review`는 사람 판단이나 누락된 안전 증거가 남은 상태다. 자동 승인하거나 `completed`로
  바꾸지 않는다. `unverified`는 필수 검증이 없거나 완료되지 않은 상태이며 pass로 합산하지 않는다.
- HWPX 성공은 해당 run의 package/open-safety, semantic/lossless, family domain verifier가 모두
  통과해야 한다. 시각 완료 주장은 입력·출력 hash가 결합된 실제 한컴 영수증 없이는 `unverified`다.
- export는 private 좌표를 제거한 로컬 영수증 묶음이다. 공개 데이터나 게시 승인으로 해석하지 않는다.
- L0 선택 가중치는 실험 workspace 안에서만 유효하다. L1/L2 개선안은 staging에만 두며 자동
  `adopt`하지 않는다. 캠페인 실행 결과만으로 게시·push·병합·릴리스를 수행하지 않는다.

## 실패와 재시도

- 같은 scenario와 `idempotency_key`를 다시 시작하면 같은 run ID를 받아야 한다.
- 확정 적용 후 같은 destination으로 재시도할 때는 기존 영수증의 content hash가 일치할 때만
  idempotent replay로 인정한다.
- artifact hash mismatch, evaluator-only field 노출, private root 안쪽 destination, open-safety 실패는
  fail-closed다. 경로를 추측하거나 primitive 도구로 우회하지 않는다.
- raw source와 sanitized source는 직접 수정하지 않는다. 산출물은 항상 별도 destination에 쓴다.
- campaign 응답이 `ok == false`이면 `state == "needs_review"`와 공개 error code만 보존한다. private
  경로나 내부 예외를 알아내려 재시도 인자를 넓히지 않는다.

## 설치형 데모 판정

설치된 플러그인의 MCP stdio surface에서 단일 scenario 두 도구와 campaign 다섯 도구가 조회되어야
한다. campaign 증거는 form 성공, structural 성공, 올바른 abstention을 포함하고 재시작 뒤에도 중복
mutation 없이 terminal receipt가 run마다 하나여야 한다. Python 내부 함수를 직접 부른 실행은
설치형 증거가 아니다. 구조 검증 영수증과 원본 SHA-256 불변을 보관하고, 실제 한컴 검증이 없으면
pre-render 또는 `unverified` 상태를 그대로 기록한다.
