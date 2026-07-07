# 양식 워크플로 (4경로 결정표·누름틀·form-fit·품질 생성·구조 변경 보존 채움)

기존 HWPX 양식을 채우는 요청은 아래 결정표로 경로를 먼저 고른다. 어떤 경로든
**원본 양식은 변경하지 않고** 사본/destination에만 적용한다.

> **철칙 (2026-07-03 교훈): 표를 절대 재생성하지 않는다.** 균등 열너비·범용
> paraPr/charPr로 표를 새로 만들면 원본의 정교한 서식(열너비·행높이·병합·정렬·음영)이
>파괴돼 "개판"이 된다. 채움은 **원본을 보존한 채 셀 텍스트만 바꾸고**, 구조 변경은
> **바이트보존 프리미티브**(④)로만 한다.

## ⓪ 처음 보는 양식 — 정찰·상의 (필수 선행)

**두뇌는 AI(이 스킬을 읽는 너)다. 도구는 감각과 손일 뿐이다.** 양식마다 관례가 다르다
— 색 범례가 있는 양식, 회색 예시체를 쓰는 양식, [대괄호]/◯◯◯ placeholder, 안내
상자, 아무 표식 없이 예시 내용이 채워진 양식까지. **어떤 관례든 네가 직접 읽고
추론해서 적응해야 한다.** 특정 관례를 하드코딩한 판단에 기대는 순간 새 양식에서
실패한다.

1. **감각 확보 (비변형)**:
   - `hwpx_to_markdown(path)` — 셀 내부 포함 **색·서식이 보이는** 원문 통독. 이것이
     1차 감각이다. 긴 양식은 `get_document_map(detail="summary")`로 표 골격부터.
   - `scan_form_guidance(path)` — 휴리스틱 **힌트**: 색 범례가 선언된 양식이면 색→
     행동 바인딩과 지울 것/placeholder/빈 셀(라벨+서식 컨텍스트)/조건부 블록 후보를
     table_patch 좌표로 준다. **힌트는 네 분석의 상한이 아니다** — 힌트가 비어도
     "지울 것 없음"이 아니라 "이 양식은 다른 관례를 쓴다"는 뜻이다.
2. **추론 (동적 — 네 일)**: 원문을 읽고 이 양식의 관례를 추정하라. 무엇이 안내문·
   예시인가(지울 것/바꿀 것), 무엇이 라벨·골격인가(둘 것), 어디가 채울 자리이고
   그 자리의 서식(글꼴 크기·굵기·정렬)은 무엇인가. **판단마다 근거를 붙여라**
   (예: "회색 이탤릭 + '예:' 접두 → 예시체"). 확신 없는 곳은 추측하지 말고 질문으로.
3. **상의**: 판단표(지울 것/채울 것/둘 것 + 질문 목록)를 사용자에게 제시하고 합의한다.
   **사용자 승인 없이 delete_table/delete_column 등 파괴적 op를 실행하지 않는다.**
4. 합의 후 아래 결정표로 실행 경로(①~④)를 고른다. 조건부 선택 블록("2개 중 하나만
   남기고 삭제")을 지울 때는 **딸린 헤딩·캡션·설명 문단도 함께** 지워야 고아 헤딩이
   안 남는다(2026-07-06 평가계획 산출물 실패 사례).
5. **제출 확언 금지 규칙**: 스코어/verify 통과는 필요조건일 뿐이다. "제출 가능"은
   렌더 PDF를 사람이 전 페이지 확인한 뒤에만 말한다.

### ⓪-2 fill-plan 상의 절차 (판단표 합의 후, 실행 전)

**Stage 2의 본질은 "어디에 뭘 어떻게 채울지"를 사용자와 항목별로 같이 정하는 것이다.**
방향 승인("해줘")은 계획 승인이 아니다 — 계획표 없이 실행으로 건너뛰지 마라(생략은
사용자가 명시적으로 "계획 생략하고 바로 해"라고 할 때만).

1. **fill-plan = 항목별 결정표(네 초안, 같이 확정)**: 각 행에 위치(앵커 우선) ·
   넣을/지울 내용(콘텐츠 초안 포함) · 서식 · op · 근거 · 상태(제안/확정)를 담아
   사용자에게 제시한다. 사용자가 행 단위로 승인/수정/거부한다. 내용 창작이 필요한
   항목은 초안을 넣고 **여러 라운드로 다듬는다**. delete_table은 역순 정렬.
   **서식 열에는 "슬롯 서식 상속 vs 본문 정규화" 판단을 명시하라** — 슬롯 서식이
   최종 서식이면(예: 제목 17pt) 상속, 슬롯 서식이 안내 표시(파란 이탤릭 등)면
   `restyle_text`(색 교체·이탤릭 제거)로 본문화. 사람은 검정 정자로 쓴다
   (2026-07-07 신청서 실측 교훈).
   실행 어휘: 표 안 = `apply_table_ops`, **표 밖 본문 = `apply_body_ops`**
   (replace_text/delete_paragraph/insert_paragraph_by_clone[참조 문단 서식 상속]/
   reorder_paragraphs) — 둘 다 바이트보존·fail-closed.
2. **dry-run**: 확정된 계획을 `apply_table_ops`/`apply_body_ops`의 `dryRun=true`로
   돌려 `transcript`(op별 해석·전후 dims)와 `applied`(old→new 텍스트)를 받는다.
   refused가 있으면 계획을 수정해 다시 dry-run.
3. **승인**: transcript+old→new 표를 사용자에게 보여주고 승인받는다. 승인 없이
   본 실행 금지(특히 delete 계열).
4. **실행·검증**: 승인된 동일 ops로 dryRun 없이 실행(output은 사본) →
   **`inspect_fill_residue(produced, blankPath=원본)`** 잔존물 zero-체크(errors 0
   필수, needsReview는 사람 판단) → `verify_form_fill`(실한컴) → 렌더 PDF 사람 확인.

### ⓪-3 질문 설계 — 매 양식 다른 상황에 맞게 "잘" 묻기

상의 품질은 질문 품질이다. 양식마다 물을 것이 다르므로(네가 판단), 아래 규율로 묻는다:

1. **질문 유형을 구분한다**:
   - **값**(슬롯: 날짜·이름·기관·수치) — 표로 묶어 한 번에.
   - **선택**(양식이 고르라는 조건부 블록) — 선택지와 각각 무엇이 지워지고 남는지를
     보여주고 묻는다. 근거가 있으면 추정 답을 붙인다.
   - **소스/초안**(내용을 무엇으로 채울지) — 사용자의 문서·메모·구두 지시가 있는지
     먼저 묻고, 네가 초안을 만들 수 있으면 **만들어서 보여주며** 묻는다(빈손 질문 금지).
   - **판단**(규정 갈림길·파괴적 op·규칙 위반 가능성: 쪽수 초과, 표기 방식, 저자
     삭제/입력) — 근거·영향을 명시하고 **반드시 답을 받는다(blocking). 기본값으로
     대신하지 않는다.**
2. **기본값이 있는 질문은 기본값과 함께**: "제 제안: X(이유). 다르게 원하시면 지정" —
   침묵해도 진행 가능한 항목과 blocking 항목을 구분 표기한다.
3. **라운드로 묶는다**: ①정찰 직후(방향·소스·blocking 판단) ②결정표 제시(항목별
   승인/수정) ③실행 직전(dry-run 증거 승인). 하나씩 찔끔 묻지도, 수십 개를 한 번에
   쏟지도 않는다 — blocking을 앞 라운드로 당긴다.
4. **답을 반영한 모습을 되보인다**: 답변 → 결정표 행 갱신 → "이렇게 반영했습니다" —
   반영 없이 다음 질문으로 넘어가지 않는다.

실전 예(실사례 기반):
- 평가계획: "분할점수 5단계/3단계 중 남길 것은? (진로선택과목이면 3단계로 추정 —
  맞으면 5단계 표+헤딩+빨간 캡션이 함께 삭제됩니다)" / 수행평가 영역·배점은 초안
  표를 만들어 항목별로.
- 시험지(원안지): 결재표 슬롯 8개(과목명·코드·시행일시·교시·학년·반·매수·묶음)는
  값 표 하나로. "논술형 포함? (미포함이면 유의사항의 논술형 항목을 삭제하라고 양식이
  지시함)".
- 논문(학회): "투고본/게재확정본? — 양식 규칙이 갈립니다(저자 삭제 vs 입력)"는
  blocking. "주제어 7개는 규칙(3~5) 위반 — 제 제안 5개: …" 는 기본값형.

## 양식 4경로 결정표

| 경로 | 선택 조건 | 도구 순서 |
|---|---|---|
| ① 누름틀/FORM 필드 채움 | `list_form_fields`에 필드가 있음 | `list_form_fields` → `fill_form_field` 또는 `analyze_form_fill` → `apply_form_fill` |
| ② 양식 보존 채움 (form-fit) | 필드 없음 + 원본 서식·구조 보존이 핵심 요구 + 채울 내용이 구조화되어 있음(baseline 사용 가능) | `analyze_template_formfit` → `apply_template_formfit(confirm=True)` |
| ③ 양식 + 아이디어 고품질 생성 | 필드 유무와 무관하게 내용 생성 자유도가 높음("알아서 완성도 있게") | `analyze_quality_generation` → `apply_quality_generation(confirm=True)` |
| ④ **구조 변경 보존 채움** | 필드 없음 + 채우면서 **표 구조를 바꿔야** 함(안 쓰는 표·열 삭제, 내용에 맞춰 행 증설) | `get_document_map` → `apply_table_ops`(fill_cell + delete_column/row/table + insert_row_by_clone) → `verify_form_fill` |

구분 기준:

- **필드 유무**: 누름틀/FORM 필드가 있으면 항상 ①을 먼저 시도한다. 표 라벨 추론보다
  native field가 정확하다.
- **원본 보존 요구**: "승인된 양식 그대로", "P6 기준선", "서식 변경 금지"가 있으면 ②.
- **생성 자유도**: 사용자가 아이디어/브리프만 주고 문장 생성을 맡기면 ③.
- **구조 변경 필요**: 양식을 채우려면 표/열/행을 **더하거나 빼야** 하면 ④. 예)
  평가계획 "정기시험 열 삭제·안 쓰는 표 삭제·세부기준 행을 내용 수만큼 증설". ①~③이
  다루지 못하는 유일한 경로 — 없으면 hand-XML 재생성으로 도망쳐 서식이 파괴된다.

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

## ④ 구조 변경 보존 채움 경로 (`apply_table_ops` · `verify_form_fill`)

필드가 없고 **채우면서 표 구조를 바꿔야** 하는 양식(예: 도교육청 평가계획 — 정기시험 열
삭제·안 쓰는 표 삭제·세부기준 행 증설). ②·③으로 안 되는 유일한 경로다. **표를 재생성하지
말고** 바이트보존 프리미티브로 원본 서식을 살린 채 수술한다.

1. `get_document_map(filename)`으로 표 인벤토리(table_index·행/열·병합)를 파악한다.
2. 어떤 표를 지우고, 어떤 열을 빼고, 어떤 표에 행을 몇 개 더할지 op 리스트를 만든다.
3. `apply_table_ops(filename, ops, output=..., render_check="auto")` — 하나의 트랜잭션으로:
   - `{"op":"fill_cell","tableIndex":T,"row":r,"col":c,"text":"..."}` — 원본 셀 서식 보존
     채움(빈 셀·병합 앵커 포함). 미변경 셀·표·섹션은 **바이트 동일**.
   - `{"op":"delete_column","tableIndex":T,"cols":[1,2]}` — 열 삭제 + 남은 열에 폭 재분배 +
     그 열 때문에 빈 행이 생기면 자동 삭제(캐스케이드).
   - `{"op":"delete_table","tableIndex":T}` — 표 통째 삭제. **인덱스가 밀리므로 여러 표는
     tableIndex 큰 것부터(역순) 삭제한다.**
   - `{"op":"insert_row_by_clone","tableIndex":T,"ref_row":k,"count":n}` — 참조 행을 복제해
     n행 증설(서식 보존·균등 재생성 금지). ref_row는 rowSpan==1 데이터 행.
   - `{"op":"autofit_columns","tableIndex":T}` — 내용에 맞춰 **열 너비 재균형**(내용 많은
     열 넓히고 적은 열 좁힘, 표 총폭 보존). 긴 텍스트가 좁은 열에서 촘촘히 wrap될 때 완화.
     명시 지정은 `{"op":"set_column_widths","tableIndex":T,"widths":[..]}`. **채움 후** 별도
     호출(autofit은 새 내용 기준 균형). 참고: 텍스트가 길면 한컴이 행 높이를 자동으로
     늘려 넘침은 없다 — autofit은 세로 cramping을 가로 재분배로 줄이는 미용 단계.
   - `{"op":"fill_cell", ..., "max_lines":N}` — 그 셀을 **N줄 안에 맞추려 폰트를 축소**
     (하한까지). 열 너비로 부족할 때 세로 높이를 줄인다. 폼 기본 폰트가 작으면(예: 9pt)
     축소 여지가 작으니 autofit(가로)이 주 무기, 폰트 축소는 보조.
   - 모든 구조 편집은 grid 검증(overlap/hole/oob) 후 **무효면 거부**(fail-closed)하고
     `skipped`에 사유를 남긴다.
4. `verify_form_fill(filename, before_path=원본, require=false)` — **실제 한컴**으로 before/after를
   렌더해 `renderChecked`·`overflowDetected`·`overlapDetected`(글자겹침)·`pageCountChanged`를
   판정한다. **`renderChecked=false`(오라클 없음)를 "제출 가능"으로 말하지 말 것.** open-safety나
   render_preview는 **한컴 수용의 증거가 아니다**(2026-07-03 과대포장 재발 금지). 제출 확언은
   `renderChecked=true` + overflow/overlap 0일 때만.

### 평가계획 전용 한-방 레시피 — `apply_evalplan_fill` (교수학습운영 및 평가계획)

도교육청 **평가계획** 양식은 ④의 op를 손으로 짜지 말고 **한 번의 호출**로 채운다. 위
프리미티브(delete/clone/fill)를 내부에서 오케스트레이션하는 상위 도구다.

> **요구 버전**: `apply_evalplan_fill` 은 `hwpx-mcp-server >= 2.16.0`. `mcp_server_health()`
> `toolSurface` 에 없으면 아직 미설치(릴리스 대기) — 그 경우 ④ 수동 경로로 처리한다.

```
apply_evalplan_fill(
  path = 빈 양식.hwpx,                 # 도교육청 빈 평가계획 양식(2015개정 or 2022개정 자동판별)
  reviewMd = 검토용.md,               # 아래 계약대로 구조화된 검토용 초안
  renderCheck = "required",           # gold 확언은 실 한컴 render 게이트 필수
  scoreGoldPath = 기제출_동일과목.hwpx  # (선택) 5축 scorecard 동봉
) → { outputPath, contentReport, rubricNeedsReview, needsReviewNotes, renderVerdict, scorecard }
```

한 호출이 하는 일(전부 **바이트보존**, 재생성 금지):
- 빨간 안내문·제출표·★유의·석차등급 표 삭제, **정기시험 열 삭제**, 잉여 예시표 삭제.
- 채움: Ⅰ 운영계획 21주 · 성취기준(상/중/하 or A~E) · 성취수준 · 성취율(3단계 or 5단계) ·
  반영비율(영역·비율·성취기준·평가요소) · 수행평가 rubric(**채점기준 배점 ladder 포함**) ·
  가/나/다 프로세스 섹션. 원본 표 서식(열너비·병합·테두리) 그대로.
- **정직 보고**: `rubricNeedsReview`/`needsReviewNotes` — 검토용 MD에 바이트보존 대응이 없는
  영역(예: 리치 rubric 하위 항목)은 **샘플로 두지 않고 needs_review로 보고**한다(무음 채움 금지).
  선생님이 그 영역만 한글에서 마무리하면 된다.

**검토용 MD 계약**(파서가 읽는 형식 — 시험지 `workflows-exam.md`와 동형):
`# 제목(담당교사: 이름)` · `## Ⅰ. 교수학습 운영 계획`(월/주/단원/성취기준/수업방법/주안점 표) ·
`### 1.`~`### 11.`(목적/기본방향/방침/성취기준·성취수준[가.표+나.표]/성취율/반영비율/수행평가
세부기준[`**① 영역 (N점)**`+평가항목·채점기준 배점 `**N**` ladder]/정의적/결시자/유의사항/결과분석).

**게이트(제출 확언 조건)** — **scorecard의 A축(정밀 overflow-crossing 검출)이 권위 신호**:
`renderVerdict.renderChecked=true` + scorecard `A=30`(overflow crossing 0) + `total ≥ 90` &
`render_checked=true` + `rubricNeedsReview` 확인. open-safety·render_preview는 한컴 수용 증거가
아니다. **주의**: `renderVerdict.overlapDetected`(verify_form_fill의 tall-band 휴리스틱)는 평가계획
같은 **조밀한 표에서 false-positive** 하니 단독으로 실패 판정하지 말고 scorecard A축과 교차확인한다.
미충족이면 정직히 미확언.

**재사용**: 내용 저작(사람)과 폼 채움(기계) 분리 — 다음 학기·과목·학년은 **빈 양식과 검토용
MD만 새로** 주면 같은 recipe로 재실행(gold 품질 유지). 검증됨: 2015개정(3학년)·2022개정(2학년)
두 form-family를 입력 교체만으로 실 한컴 오라클-clean 채움(각각 94.9·94.7/100).

비-평가계획 구조변경 양식(다른 도교육청 폼 등)은 ④ 수동 `apply_table_ops` 경로를 쓴다.

## ⑤ 직인/관인 날인 경로 (`place_seal` · `check_seal_compliance`)

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
