# Fixture 기반 전 페이지 시각 검수

버전이 고정된 페이지 PNG fixture로 결함 탐지와 제한적 수정 루프를 재현하는 경로다. 실한컴이
렌더한 결과가 아니므로 이 경로의 영수증은 성공하더라도 항상 `renderChecked=false`,
`real_hancom_verified=false`, `verificationStatus="unverified"`여야 한다. fixture 결과를 실제
한컴 검증 증거로 승격하거나 최종 제출 가능 상태로 해석하지 않는다.

## 검수 루프

1. `visual_review_fixture`에 HWPX, 버전 고정 fixture manifest/page set, 기대 document revision을 준다.
2. 응답에서 모든 manifest 페이지에 page verdict가 있는지 확인한다. 누락·중복·크기 불일치는 pass가 아니다.
3. aggregate만 보지 말고 `findings[]`와 detector/adapter 각각의 원시 결과를 확인한다. critical finding이나
   detector disagreement가 aggregate score에 가려져서는 안 된다.
4. 각 finding의 `page`, 정규화 bbox, category, severity, confidence, evidence crop/hash,
   provenance, optional document target을 ledger에 보존한다.
5. 안전하게 target이 매핑된 allow-list 항목만 별도 `hwpx.visual-repair-plan/v1` JSON에 적어
   `visual_repair_fixture`에 넘긴다. `repair_plan_path`, expected revision과 idempotency key를 반드시
   사용하고 최대 3회까지만 실행한다.
6. 매 회 fixture를 다시 검수한다. 새 결함이나 심각도 상승이 생기면 해당 round를 rollback하고 멈춘다.

## 수정과 escalation

- 자동수정 허용 여부는 서버의 allow-list가 결정한다. 에이전트가 category 이름만 보고 안전하다고
  추정하지 않는다.
- target이 없거나 모호한 finding, critical finding, image/seal 위치, 표 구조·페이지 흐름처럼 파급 범위가
  큰 수정, detector 간 불일치는 `needs_review`로 escalation한다.
- `visual_repair_fixture`의 `unsafe`/`escalated`/`unresolved` 항목을 primitive 편집 도구로 우회하지 않는다.
- 수정 전후 영수증, revision, input/output hash, 적용·거절된 action, rollback, before/after finding을 하나의
  append-only evidence ledger로 남긴다. 원시 페이지와 crop은 render artifact와 동일한 PII·보존 정책을 따른다.

## 완료 판정

fixture 루프의 성공은 "고정 fixture에서 더 깨끗해졌고 unsafe 항목을 정직하게 escalation했다"는 뜻이다.
최종 영수증에서 다음을 모두 확인한다.

- manifest의 모든 페이지가 검수됨
- 최소 한 개의 before/after finding 연결과 수정 action ledger가 존재
- unsafe 또는 unmapped 항목이 `needs_review`/escalated로 남음
- `renderChecked == false`
- `real_hancom_verified == false`
- 실제 한컴 검증이 필요하면 별도로 `render_health` → `render_submit` → `render_status`를 실행

설치 플러그인 프로토콜 데모는 `scripts/plugin_fixture_qa_e2e.py --help`를 사용한다. 도구가 아직 없는
구버전 서버에서는 기본적으로 `skipped`를 정직하게 보고하며, release gate에서는 `--require-tools`로
누락을 실패 처리한다.
