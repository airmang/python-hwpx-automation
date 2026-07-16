# HWPX 양식 채움 워크플로

양식 채움의 기본 경로는 `analyze_form_fill` → `apply_form_fill`이다. 분석기는 누름틀,
라벨이 붙은 표 셀, canonical path, 표 밖 본문 anchor를 한 typed mixed-form plan에 모으고,
적용기는 그 계획을 **한 트랜잭션**으로 실행한다. 필드 유무만으로 오래된 도구 세대를 먼저
고르거나 표·본문 작업을 별도 commit으로 나누지 않는다.

정확한 현재 입력 스키마, profile, deprecation/replacement 정보는 자동 생성된
[`tool-contract.generated.md`](tool-contract.generated.md)가 정본이다.

## 라우팅 우선순위

1. 출제 Markdown을 시험지 양식에 재조판하는 요청이면 `compose_exam`을 사용한다. 시험은 generic
   form-fill로 낮추지 않는다.
2. 교수학습운영 및 평가계획이면 전용 specialized facade `apply_evalplan_fill`을 사용한다.
3. 그 밖의 누름틀, 라벨 셀, 경로 셀, 표 밖 본문이 하나라도 섞인 양식은 모두
   `analyze_form_fill` → `apply_form_fill`로 처리한다.
4. legacy facade는 기존 자동화의 전환 기간에만 사용한다. 새 사용자 요청의 1차 경로로 선택하지
   않고 generated contract의 replacement guidance를 따른다.

## Canonical mixed-form plan/apply/verify

1. 원본과 다른 destination을 정하고 필요하면 `get_document_map`으로 bounded 구조와 revision을 읽는다.
2. `analyze_form_fill`에 source, destination, 채울 값/초안을 준다. 이 호출은 파일을 변경하지 않아야 한다.
3. 반환된 versioned plan에서 다음을 확인한다.
   - source/destination과 expected revision
   - `nativeField`, `canonicalPath`, `labelCell`, `bodyAnchor`별 discriminated operation
   - unresolved/ambiguous target과 사용자 결정이 필요한 항목
   - byte-preservation 범위, 예상 semantic diff, 검증 요구사항
4. target kind가 정해진 뒤에는 다른 kind로 runtime fallback하지 않는다. 자동 정찰 후보를 정렬할
   때만 `stable native field` → `explicit revision-bound canonical path` → `exact unique label cell` →
   `unique direct-body single-run anchor` 순서를 쓴다. 0건·복수건·run/paragraph 경계에 걸친 anchor는
   fail-closed다. 모호한 target은 임의로 첫 후보를 고르지 말고 한 번에 묶어 사용자에게 확인한다.
5. 모든 target이 mutation 전에 해석됐는지 확인한다. dry-run은 top-level 인자가 아니라
   `plan.dryRun=true`로 설정해 `apply_form_fill(plan=...)`의 semantic diff를 먼저 검토한다.
   commit은 동일 operations/verification requirements를 `plan.dryRun=false`, 새 idempotency key,
   최신 revision으로 다시 분석한 뒤 한 번 적용한다. `apply_table_ops`와
   `apply_body_ops`를 따로 commit해 원자성을 깨지 않는다.
6. 응답의 rollback/idempotency, package reopen, byte-preservation, `openSafety.ok`, residue/verification
   영수증을 확인한다. 별도 검증이 요구된 계약에서는 `verify_form_fill` 결과도 같은 revision과 연결한다.
7. revision mismatch면 다시 분석하고 새 plan을 만든다. 같은 commit 재시도에만 같은 idempotency key를 쓴다.

적용 중 한 operation이라도 실패하면 destination 전체가 적용 전 상태로 rollback되어야 한다. 일부
표만 바뀐 결과를 성공으로 handoff하지 않는다.

## 상의 질문 설계

분석 직후 질문은 대상별로 흩어 묻지 말고 다음 항목을 한 묶음으로 제시한다.

- source of truth: 문서 안 값, 사용자 제공 값, 외부 초안 중 무엇이 우선인지
- ambiguous target: 같은 라벨/본문이 여러 곳일 때 어느 anchor인지
- condition: 선택 블록 중 무엇을 남기고 지울지
- generation freedom: 원문 보존인지 내용 생성까지 맡기는지
- visual gate: 실제 한컴 전 페이지 검토가 필수인지

명확한 매핑은 재질문하지 않는다. 모호하거나 민감한 값은 빈칸으로 무음 채움하지 말고
`needs_review`로 남긴다.

## 평가계획 facade — `apply_evalplan_fill`

도교육청 교수학습운영 및 평가계획은 구조와 품질 게이트가 고정된 전문 facade를 유지한다.
빈 HWPX 양식과 검토용 Markdown을 입력하고 원본과 다른 destination을 지정한다.

```text
apply_evalplan_fill(
  filename=".../빈양식.hwpx",
  review_md=".../검토용.md",
  output=".../채움본.hwpx",
  render_check="required",
  score_gold_path=".../gold.hwpx"  # 선택
)
```

- facade 응답의 typed plan과 canonical apply/verify 영수증을 확인한다.
- `render_check="required"`이면 실제 한컴 전 페이지 판정이 없을 때 완료를 확언하지 않는다.
- advanced profile에서 정량 비교가 명시적으로 필요할 때만 `score_form_fill`을 별도로 호출한다.
- facade가 unavailable이면 typed reason과 요구 버전을 보고하고 설치 조합을 교정한다. 새 작업을
  수동 `apply_table_ops` 조합으로 조용히 낮추지 않는다.

검토용 Markdown은 제목/담당교사, 교수학습 운영 계획 표, 평가 목적·방침·성취기준·성취수준,
반영비율, 수행평가 세부기준, 정의적 영역, 결시자 처리, 유의사항, 결과 분석을 명시적으로 담는다.
누락되거나 서로 충돌하는 항목은 `needs_review`로 남긴다.

## Compatibility facade 경계

다음 이름은 기존 호출자를 위한 전환 표면이거나 집중 검사 도구다. generated contract가
deprecated/replacement로 표시한 이름은 root router에 다시 올리지 않는다.

| 이름 | 전환 원칙 |
|---|---|
| `list_form_fields` | native field 존재 여부를 읽는 집중 검사. 새 채움 계획은 `analyze_form_fill`로 만든다. |
| `find_cell_by_label` | 정확한 표 라벨 후보를 찾는 public locator. mutation은 canonical plan에 합친다. |
| `fill_form_field` · `fill_by_path` | 단일 legacy target 호환. 새 mixed 작업은 canonical plan에 합친다. |
| `apply_table_ops` · `apply_body_ops` | 기존 op payload 호환. 새 작업에서 두 mutation을 따로 commit하지 않는다. |
| `scan_form_guidance` · `inspect_fill_residue` · `verify_form_fill` | bounded 정찰/검증에 사용할 수 있으나 별도 mutation 세대를 만들지 않는다. |
| `analyze_template_formfit` · `apply_template_formfit` | 기존 baseline 자동화 호환. replacement guidance에 따라 canonical analyzer/apply로 이관한다. |
| `analyze_quality_generation` · `apply_quality_generation` | 전환 기간 deprecated facade. 내용 생성 요구도 canonical plan의 생성 정책으로 표현한다. |

## 직인/관인 날인 (`place_seal` · `check_seal_compliance`)

공문의 직인은 **발신명의(예: "행정안전부장관 홍길동") 줄의 끝글자**에 도장 중심이 오도록
규칙대로 찍는다. 위치는 한컴이 실제로 글자를 그린 자리를 기준으로 하므로 **한컴 렌더 오라클이
진실원천**이다.

1. `place_seal(filename, sender_text, image_base64, seal_width_mm=25, verify=true)`를 호출한다.
   한컴으로 양식을 렌더해 발신명의 끝글자 anchor를 찾고 직인을 floating으로 찍는다.
2. 결과의 `placement.placed == true`, `openSafety.ok == true`, `sealVerdict.ok == true`를 확인한다.
3. 이미 날인된 문서를 검사만 하려면 `check_seal_compliance(filename, sender_text)`를 사용한다.

- 한컴 오라클이 없으면 `renderChecked=false`로 정직하게 degrade하며 임의 좌표로 완료를 주장하지 않는다.
- 발신명의가 발신·결재 표 안에 있어도 셀까지 탐색한다.

## 공통 주의

- 어떤 경로든 결과 파일의 `openSafety.ok == true`를 확인하기 전에는 handoff하지 않는다.
- 원본을 직접 덮어쓰지 않는다.
- 채움 값에 `<`, `>` 같은 XML 조각을 넣지 않는다.
- 생성된 contract와 실제 health/availability가 다르면 도구를 추측 호출하지 않고 설치 skew를 보고한다.
