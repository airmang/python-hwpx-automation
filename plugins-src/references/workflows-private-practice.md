# 비공개 코퍼스 합성 문서편집 연습

이 경로는 운영자가 로컬의 비공개 practice root와 runner manifest를 서버 환경에 결합한 경우에만
사용한다. 에이전트는 원본 경로·파일명·split·lineage·평가 gold를 받지 않고 불투명 scenario ID와
합성 입력만 본다. 외부 모델이나 외부 저장소로 문서 내용을 전송하지 않는다.

## 실행 순서

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

## 실패와 재시도

- 같은 scenario와 `idempotency_key`를 다시 시작하면 같은 run ID를 받아야 한다.
- 확정 적용 후 같은 destination으로 재시도할 때는 기존 영수증의 content hash가 일치할 때만
  idempotent replay로 인정한다.
- artifact hash mismatch, evaluator-only field 노출, private root 안쪽 destination, open-safety 실패는
  fail-closed다. 경로를 추측하거나 primitive 도구로 우회하지 않는다.
- raw source와 sanitized source는 직접 수정하지 않는다. 산출물은 항상 별도 destination에 쓴다.

## 설치형 데모 판정

설치된 플러그인의 MCP stdio surface에서 두 practice 도구가 조회되고, 위 순서를 통해 새 HWPX가
생성되어야 한다. Python 내부 함수를 직접 부른 실행은 설치형 증거가 아니다. 구조 검증 영수증과
원본 SHA-256 불변을 보관하고, 실제 한컴 검증이 없으면 pre-render 상태를 그대로 기록한다.
