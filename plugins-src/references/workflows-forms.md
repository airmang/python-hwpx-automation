# 양식 워크플로 (3경로 결정표·누름틀·form-fit·품질 생성)

기존 HWPX 양식을 채우는 요청은 아래 결정표로 경로를 먼저 고른다. 어떤 경로든
**원본 양식은 변경하지 않고** 사본/destination에만 적용한다.

## 양식 3경로 결정표

| 경로 | 선택 조건 | 도구 순서 |
|---|---|---|
| ① 누름틀/FORM 필드 채움 | `list_form_fields`에 필드가 있음 | `list_form_fields` → `fill_form_field` 또는 `analyze_form_fill` → `apply_form_fill` |
| ② 양식 보존 채움 (form-fit) | 필드 없음 + 원본 서식·구조 보존이 핵심 요구 + 채울 내용이 구조화되어 있음(baseline 사용 가능) | `analyze_template_formfit` → `apply_template_formfit(confirm=True)` |
| ③ 양식 + 아이디어 고품질 생성 | 필드 유무와 무관하게 내용 생성 자유도가 높음("알아서 완성도 있게") | `analyze_quality_generation` → `apply_quality_generation(confirm=True)` |

구분 기준:

- **필드 유무**: 누름틀/FORM 필드가 있으면 항상 ①을 먼저 시도한다. 표 라벨 추론보다
  native field가 정확하다.
- **원본 보존 요구**: "승인된 양식 그대로", "P6 기준선", "서식 변경 금지"가 있으면 ②.
- **생성 자유도**: 사용자가 아이디어/브리프만 주고 문장 생성을 맡기면 ③.

## ① 누름틀/FORM 필드 경로

1. `list_form_fields(filename)` — 필드 목록과 현재 값. `formFields.available=false`와
   `fallback="table-label"`이 명시된 문서만 표 라벨 경로(아래 fallback)로 처리한다.
2. 단건은 `fill_form_field(filename, value, field_index|field_id|name, dry_run, expected_revision)`.
3. 여러 값 매핑은 `analyze_form_fill(source_filename, input_json=..., destination_filename=...)`
   → 계획 확인 → `apply_form_fill(analysis=..., confirm=True)`. analyze는 파일을 변경하지
   않고, apply는 **복사본에만** 적용하고 구조/패키지를 검증한다.

### `analyze_form_fill` 신뢰도 등급 처리

- `confidenceGrade == "label-exact"`: 바로 진행 가능.
- `confidenceGrade == "label-fuzzy"` 또는 `"position-guess"`: 적용 전 **사용자 확인 필수**.
  확인 없이 apply하지 않는다.

### fallback: 표 라벨 경로

필드가 없는 표 기반 양식은 `find_cell_by_label(filename, label_text, direction)`으로 라벨
옆 셀을 찾고 `fill_by_path(filename, {"라벨 > right": "값"})` 또는
`set_table_cell_text`로 채운다.

## ② 양식 보존 form-fit 경로

1. 기준선 JSON(`hwpx.template-formfit.baseline.v1`)과 구조화된 content를 준비한다.
2. `analyze_template_formfit(source_filename, baseline, content, destination_filename)` 호출.
3. `mutated == false`, `source.unchanged_after_analysis == true`, `unresolved_count == 0`이
   아니면 apply하지 않는다. anchor가 없거나 둘 이상이면 `unresolved`로 막힌다.
4. `apply_template_formfit(analysis=..., confirm=True)` — source와 destination이 같으면
   거부된다.
5. handoff 전 확인 (전체 증거 계약은 [`evidence-contract.md`](evidence-contract.md)):
   - `handoff_status == "ready"`, `source.preserved == true`
   - `validation.validate_package.ok == true`, `validation.validate_document.ok == true`
   - `validation.openSafety.ok == true`, `residual_markers.blocking == []`
   - file-only `inspect_operating_plan_quality(destination).status == "ready"` 또는 남은
     gap이 제출 전 수동 보완 가능하다는 근거
6. `visual_review_required=true`이면 열린 문서 검토 evidence
   ([`evidence-contract.md`](evidence-contract.md))까지 있어야 최종 제출 가능 상태를 주장한다.

예제: `examples/08_template_formfit.py`, `examples/08_mcp_template_formfit.md`.
검증: `python3 scripts/quickcheck.py --template-formfit`.

## ③ 양식 + 아이디어 고품질 생성 경로

`analyze_quality_generation(form_filename, idea_brief, destination_filename)` →
`apply_quality_generation(analysis=..., confirm=True)`. 상세 절차와 입력 정규화는
[`workflows-creation.md`](workflows-creation.md) §6을 따른다. analyze 단계는 원본 양식을
변경하지 않으며, 결과의 `validation`·`quality.gaps`·`revision_history`를 확인한다.

## ④ 직인/관인 날인 경로 (`place_seal` · `check_seal_compliance`)

공문의 직인은 **발신명의(예: "행정안전부장관 홍길동") 줄의 끝글자**에 도장 중심이 오도록
규칙대로 찍는다. 위치는 한컴이 실제로 글자를 그린 자리를 기준으로 하므로 **한컴 렌더 오라클이
진실원천**이다.

1. `place_seal(filename, sender_text, image_base64, seal_width_mm=25, verify=true)` 호출.
   한컴으로 양식을 렌더해 발신명의 끝글자(앵커)를 찾고, 직인을 그 위에 floating으로 찍는다
   (`textWrap=IN_FRONT_OF_TEXT` — 겹친 글자를 밀지 않고 위에 스탬프). `verify=true`면 저장 후
   재렌더로 `sealVerdict`(중심 오차·가림 글자)를 함께 반환한다.
2. 결과의 `placement.placed == true`, `openSafety.ok == true`, `sealVerdict.ok == true`를 확인.
3. 이미 날인된 문서를 검사만 하려면 `check_seal_compliance(filename, sender_text)` — 잘 찍힌
   직인은 pass, 어긋난 직인은 fail로 **차별** 판정한다(평가자가 그대로 돌릴 수 있는 검사).

- **오라클 없는 환경**: 한컴(macOS)이 없으면 `renderChecked=false`로 정직하게 degrade한다.
  임의로 찍지 않는다 — 앵커 PDF 좌표를 안다면 `anchor_x`/`anchor_y`로 직접 지정해 날인만 수행.
- 발신명의가 **발신·결재 표 박스 안**에 있어도 `place_seal`이 셀까지 탐색해 찾는다.

## 공통 주의

- 어떤 경로든 결과 파일의 `openSafety.ok == true`를 확인하기 전에는 handoff하지 않는다.
- 채움 값에 `<`, `>` 같은 XML 조각을 넣지 않는다.
- 누름틀 값 채움 후 표기 정규화가 필요하면 `search_and_replace`를 이어서 사용한다.
- 직인 날인 결과는 `sealVerdict.ok`(또는 `check_seal_compliance`)로 발신명의 정합을 확인한다.
