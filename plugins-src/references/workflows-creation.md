# 생성 워크플로 (document-plan·builder·정부보고서·운영계획서·제안서·공문서)

새 HWPX를 만드는 모든 경로의 상세 절차. 증거 요건(openSafety·visual-review·hard gates)은
[`evidence-contract.md`](evidence-contract.md) 한 곳을 따른다.

## 1. document-plan 기반 생성 (기본 경로)

사용자가 데이터·구조를 주고 새 문서를 요청하면 저수준 XML 대신 `hwpx.document_plan.v1`
JSON을 먼저 작성한다.

1. 제목, 메타데이터, `heading`/`paragraph`/`bullets`/`table`/`page_break` block으로 정규화한다.
2. `validate_document_plan(document_plan)` — 비파괴 검증. `ok=false`이면 `issues[].code`,
   `issues[].path`, `repairHints[]`를 읽고 plan을 고친 뒤 재검증한다. `can_create=false`
   상태에서는 생성하지 않는다.
3. `create_document_from_plan(filename, document_plan)`으로 생성한다.
4. 응답의 `quality.validation.reopened`, `validate_package.ok`, `validate_document.ok`,
   `verification.openSafety.ok`, `visual_review_required`를 확인한다.
5. 결과 확인은 `get_document_text`/`get_table_text` readback으로 한다.

주의:

- 깨진 table은 `columns[].key`와 `rows[]`의 key부터 맞춘다.
- `unknown_style_token` warning은 지원 token(`body`, `title`, `subtitle`, `heading`,
  `bullet`, `table_header`, `table_cell`)으로 바꾸거나 style을 생략한다.
- 검증 실패 파일은 handoff하지 않는다. `recovery.repair_hints[]`를 반영해 재생성한다.
- binary `.hwp`, 임의 OWPML 삽입, 복잡한 레이아웃 재현은 범위 밖이다.

MCP가 없으면 local Python에서 `validate_document_plan()` → `create_document_from_plan()` →
`inspect_document_authoring_quality()`를 직접 사용한다 ([`api.md`](api.md)).
예제: `examples/06_create_from_document_plan.py`, `examples/06_mcp_document_plan.md`.
검증: `python3 scripts/quickcheck.py --document-plan`.

## 2. Markdown/비-HWPX 원본에서 HWPX 초안 생성

사용자가 Markdown, PDF/DOCX/XLSX/HTML/TXT 같은 원본을 주고 "한글 문서로 만들어줘"라고
하면 raw Markdown을 바로 쓰지 말고 document-plan bridge를 거친다.

1. HWPX 또는 로컬 원본 파일이면 `document_to_markdown(filename)`으로 Markdown을 만든다.
   HWPX는 `python-hwpx`, 비-HWPX는 서버가 `[ingest]` extra로 설치된 경우 MarkItDown adapter가
   처리한다. `meta.engine`, `warnings`, `attempts[]`를 확인한다.
2. 이미 Markdown 텍스트가 있으면 바로 `markdown_to_document_plan(markdown, title?, metadata?)`.
   이 도구는 파일을 쓰지 않고 `document_plan`, `validation`, `can_create`, `warnings`를 반환한다.
3. `ok=false`이면 `validation.issues[]`/`validation.repairHints[]`를 보고 Markdown 또는 plan을 고친다.
4. `ok=true`이면 `create_document_from_plan(filename, document_plan)`으로 HWPX를 생성한다.
5. 결과는 `document_to_markdown(filename)` 또는 `get_document_text`/`get_table_text`로 readback한다.

정직 라벨:

- MarkItDown adapter 결과는 레이아웃 복원이 아니라 구조 읽기용 Markdown이다.
- `markdown_to_document_plan`은 ATX heading(`#`), 문단, 불릿/번호 목록, GFM table을 보수적으로
  `heading`/`paragraph`/`bullets`/`table` block으로 낮춘다. 번호 목록은 bullet로 바뀌며,
  heading level 4 이상은 document-plan level 3으로 clamp될 수 있다.
- 제출용 파일은 생성 후 기존 openSafety/visual-review evidence 계약을 그대로 따른다.

## 3. builder 조립 생성 (코드 수준 레이아웃 제어)

머리글/바닥글, 쪽번호, 리치 런, 다단계 목록, 병합/음영/열너비 표, 이미지, 페이지 나눔을
한 번에 조립해야 하면 local `hwpx.builder`를 사용한다.

1. `Document(metadata=..., sections=[Section(...)])`로 객체모델을 만든다.
2. 본문은 `Heading`, `Paragraph(children=[Run(...)])`, `Bullet`, `NumberedList`,
   `Table`, `Image`, `PageBreak`로 구성한다.
3. 머리글/바닥글은 `Header`/`Footer` 안에 `Paragraph(children=[Run(...), PageNumber(...)])`.
4. `report = document.save_to_path(path)` — `BuilderSaveReport`의 hard gates 판정은
   [`evidence-contract.md`](evidence-contract.md)를 따른다.

builder는 내부 XML을 직접 만들지 않고 `HwpxDocument` facade로 lowering한다.
이미 만들어진 문서의 머리글/쪽번호만 고치는 경우라면 builder 대신 MCP
`set_header_footer`/`set_page_number`가 빠르다 ([`workflows-editing.md`](workflows-editing.md)).
예제: `examples/10_create_with_builder.py`. 검증: `python3 scripts/quickcheck.py --builder`.

## 4. 정부보고서·공문형 보고서

□/○/※ 불릿, 단위 표기 표, 범정부오피스식 보고가 요구되면:

1. 붙여넣은 텍스트는 `parse_government_report_text(text, title)`로 plan v2로 변환한다.
2. 금액/비율/증감률/날짜는 `compute_report_value(operation, values)`로 계산한다(수동 계산 금지).
3. 반환 plan에 `preset="government_report"`와 필요한 결문·메타데이터를 확인하고
   `validate_document_plan` → `create_document_from_plan`으로 생성한다.
4. `inspect_document_authoring_quality(..., quality_profile="government_report")`로 확인한다.

`create_government_report_document`는 기존 호출자를 위한 compatibility facade다. 새 요청은
위 document-plan 경로를 사용한다. 예제: `examples/10_create_government_report.py`,
`examples/10_mcp_government_report.md`.
열린 문서 검토 항목은 [`government-report-visual-review.md`](government-report-visual-review.md).

## 5. 운영 계획서 제출 후보

"운영 계획서", "사업 운영 계획", "AI 중점학교 운영계획서" 등 제출용 계획서는 generic
plan보다 운영 계획서 프로필을 우선한다. 장르 판단, report typography 상속,
section-chip 번호/형태/accent 변주는
[`workflows-house-style.md`](workflows-house-style.md)를 따른다.

1. 요청을 `hwpx.document_plan.v1`로 정규화하고 필수 구조를 포함한다: 신청 목적, 운영 계획,
   추진 일정, 사업비/자원 사용 계획, 교육과정 또는 운영 체계, 기대 효과/성과 관리,
   제출/확인 마감 문구. 표는 최소 2개(`추진 일정`, `사업비 사용 계획`)를 권장한다.
2. placeholder, `TODO`, `작성 필요`, `□□□□`, `○○` 같은 drafting marker를 남기지 않는다.
3. MCP 호출 순서: `validate_document_plan` →
   `analyze_document_plan(document_plan, quality_profile="operating_plan")` →
   `create_document_from_plan(filename, document_plan, quality_profile="operating_plan")` →
   `get_document_text`/`get_table_text` readback.
4. MCP가 없으면 local에서 `inspect_document_authoring_quality(path, plan=plan,
   quality_profile="operating_plan")`과 `inspect_operating_plan_quality(path, plan=plan)`을 쓴다.
5. handoff 전 [`evidence-contract.md`](evidence-contract.md)의 운영계획서 제출 증거
   체크리스트를 전부 충족한다. `status="needs_revision"` 또는 `gaps[]`가 있으면
   `repair_hints[]`를 반영해 plan을 보강하고 재검증한다.

예제: `examples/07_create_operating_plan.py`, `examples/07_mcp_operating_plan.md`,
`examples/09_visual_review_loop.md`. 검증: `python3 scripts/quickcheck.py --operating-plan`.

## 6. 제안서/기획안 (proposal preset)

"제안서", "기획안" 요청은 proposal 구조를 담은 canonical document plan을 사용한다.

1. 요청을 `hwpx.document_plan.v1`로 정규화하고 제안 배경, 목표, 범위, 실행안, 일정,
   예산/자원, 기대효과를 명시한다.
2. `validate_document_plan` → `analyze_document_plan` → `create_document_from_plan`으로 생성한다.
3. 생성 직후 `inspect_document_quality(filename, rubric="proposal")`(MCP) 또는
   `inspect_proposal_quality()`(local)로 구조·표·payload·validation·rubric 점수·
   `sample_match`를 확인한다.
4. 평균 점수 4.0 미만, `sample_match.pass == false`, 필수 섹션 누락이면 plan을 보강해
   다시 생성한다.
5. anti-pattern: 큰 BMP 의존 문서, 표/메타데이터가 이미지로 박힌 문서, PII가 redaction
   없이 노출되는 예제.

`create_proposal_document`는 기존 `ProposalSpec` 호출을 위한 compatibility facade다. 새 요청의
MCP 경로로 선택하지 않는다.

예제: `examples/04_create_proposal.py`. 검증: `python3 scripts/quickcheck.py --proposal`.

## 7. 양식 + 아이디어 고품질 생성 (quality-profile 생성)

사용자가 완성 대상 양식(HWPX)의 구조와 대략적 아이디어만 주고 "완성도 있게 작성해줘"라고
하면 목표 품질 샘플을 요구하지 말고 document-plan 경로에 품질 프로필을 실어 생성한다.
`analyze_quality_generation`/`apply_quality_generation`은 5.0 경계에서 제거됐다 — 별도
분석 단계 없이 plan schema 자체가 그 역할을 흡수한다.

1. 양식의 구조가 필요하면 `document_to_markdown(form_filename)` 또는 `get_document_map`으로
   섹션·표·필수 항목을 파악한다.
2. 요청과 아이디어를 `hwpx.document_plan.v1`로 정규화하고 파악한 구조를 반영한다.
3. `validate_document_plan(document_plan)`으로 비파괴 검증한다. `ok=false`이면 `issues[]`/
   `repairHints[]`를 반영해 고친다.
4. `create_document_from_plan(destination_filename, document_plan, quality_profile=...)`으로
   생성한다. proposal 성격이면 `create_proposal_document`를 대신 쓴다.
5. `inspect_document_quality(destination_filename, rubric=...)`로 품질을 확인한다.
   점수·`gaps`가 부족하면 plan을 보강해 다시 생성한다.
6. 좋은 품질 샘플은 캘리브레이션/평가용일 뿐 매번 필요한 입력이 아니다.

예제 흐름: `examples/05_mcp_quality_pipeline.md`. 양식 경로 선택 기준은
[`workflows-forms.md`](workflows-forms.md)의 3경로 결정표를 따른다. 5.0 제거 계약은
[`migration-5.0.md`](migration-5.0.md)를 본다.

## 8. 공문서 작성규정 lint와 결재란

공문, 내부 결재문서, 가정통신문, 회의록, 품의서처럼 행정문서 성격이 강하면 생성 후
`inspect_official_document_style(filename)`을 실행한다 (local 동명 함수도 동일).
규칙 근거: [`official-document-rules.md`](official-document-rules.md).

확인 항목:

- 항목 표시 `1.` → `가.` → `1)` → `가)` → `(1)` → `(가)` 순서를 건너뛰지 않는다.
- `끝.` 표시는 마지막 위치. 붙임이 있으면 붙임 목록 뒤 단독 `끝.` 문단.
- 붙임은 `붙임 1. 세부계획서 1부.`처럼 문서명·부수·마침표 포함.
- 날짜 `2026. 6. 12.` / 금액 `1,000,000원` 형식. 콜론·물음표 앞 공백 금지.
- 붙임 참조와 표/그림 번호 연속성은 `inspect_reference_consistency`로 검사한다.

결재란: builder는 `approval_box()`, document-plan v2는 `{"type": "approval_box"}` block.
기본 열은 `기안`, `검토`, `결재`, `전결`.

장르 레시피:

- 외부 공문: `approval_box` → `1. 관련` → `2. 요청 사항` → `붙임 ... 1부.` → `끝.`
- 내부 결재문서: `approval_box(labels=["기안", "검토", "결재"], delegated="전결")` →
  점검 개요 → 조치 계획 → `끝.`
- 가정통신문: 안내 사항 → 협조 요청 → 날짜 표기 → `끝.`
- 회의록: 회의 개요 → 주요 논의 → 참석자/일시 → `끝.`
- 구입 품의서: 구입 목적 → 소요 예산 → 견적서 붙임 → `끝.`

예제와 open-safety/lint 검증: `python3 examples/11_official_document_recipes.py`.
