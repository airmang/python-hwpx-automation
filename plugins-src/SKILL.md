---
name: hwpx
description: "한글 문서(.hwpx/OWPML) 편집·추출·자동화 스킬. '한글 문서 편집해줘', 가정통신문·공문·한글 양식 작성, HWPX 편집, 한글 파일/OWPML 분석, 플레이스홀더 치환, 문서 자동화 요청이면 이 스킬을 반드시 사용하세요."
---

# hwpx (HWPX / OWPML)

`.hwpx`는 ZIP 기반 OWPML 문서다. 기본 생성·편집은 `python-hwpx`로 처리하고, 표를 포함한 전역 치환이나 ZIP 레벨 후처리는 번들 스크립트로 처리한다.

- 기준 라이브러리: `python-hwpx` (import: `hwpx`)
- 기본 편집 최소 호환 기준: `python-hwpx >= 2.11.0`
- document-plan 생성 권장 기준: `python-hwpx >= 2.11.0` 로컬 스택
- builder 생성 권장 기준: `python-hwpx` S-013 builder core 포함 버전 또는 로컬 checkout
- 최근 로컬 검증 버전: `python-hwpx 2.11.0 + editor-open safety guard`
- 상세 시그니처와 옵션은 [`references/api.md`](references/api.md)에서 확인한다.

## 시작

MCP 서버가 연결되어 있으면 작업 전에 `mcp_server_health()`를 먼저 호출한다.
확인할 값은 `version`, `pythonHwpxVersion`, `skillBundleVersion`,
`toolSurface.status`, `toolSurface.actualFastMcpToolCount`,
`toolSurface.expectedFastMcpToolCount`, `toolSurface.missingKeyTools`다.
`toolSurface.status != "ok"`이거나 핵심 도구가 누락되면 플러그인 재설치
(`codex plugin remove hwpx-plugin@hwpx` 후 `codex plugin add hwpx-plugin@hwpx`)
또는 stale plugin venv/cache 제거 후 **새 호스트 세션**을 시작하라고 안내한다.

```bash
pip install -U python-hwpx lxml
```

## 5분 검증

설치 직후에는 아래 순서로 최소 성공 경로를 먼저 확인한다.

```bash
python3 examples/01_create_and_save.py
python3 examples/02_extract_and_inspect.py examples/out/01_created.hwpx
python3 scripts/text_extract.py examples/out/01_created.hwpx
```

치환 흐름까지 확인하려면:

```bash
python3 examples/03_template_replace.py examples/out/01_created.hwpx examples/out/03_replaced.hwpx --replace "학부모님께 안내드립니다.=학부모님께 수정 안내드립니다."
python3 examples/02_extract_and_inspect.py examples/out/03_replaced.hwpx
```

## 레이아웃 프리뷰 self-check

MCP 서버에 `render_preview`가 있으면 레이아웃 민감 작업마다 생성→프리뷰→수정
루프를 돈다.

1. 문서를 생성하거나 편집한 직후 `render_preview(filename, outputDir=..., mode="pages", screenshot="auto")`를 실행한다.
2. 반환된 `status`, `htmlPath`, `manifestPath`, `visualReviewPath`, `pages[].screenshotPath`, `screenshotEngine.backend`를 확인한다.
3. `status == "ok"`이면 PNG를 보고 페이지 박스, 여백, 표 테두리, 열너비, 정렬, 잘림을 확인한다. 문제가 있으면 문서를 수정하고 `render_preview`를 다시 실행한다.
4. `status == "blocked"` 또는 `status == "partial"`이면 `htmlPath`를 열어 HTML 프리뷰를 확인하고, 필요하면 Playwright browser 또는 Chrome 경로(`HWPX_MCP_CHROME_PATH`)를 준비한 뒤 다시 실행한다.
5. `visualReviewPath`는 `hwpx.visual-review.v1` evidence다. 이것은 빠른 렌더 프리뷰 evidence이며, 최종 제출 가능 상태를 주장할 때는 여전히 Hancom Office HWP, ComputerUse, 또는 사람 viewer의 열린 문서 검토 evidence가 필요하다.

## 라우팅 원칙

- 사용자가 코드 수준 레이아웃 제어, 머리글/바닥글, 쪽번호, 리치 런, 이미지, 페이지 나눔을 요구하면 `hwpx.builder` 경로를 우선한다.
- 사용자가 데이터·구조를 제공하고 새 문서를 만들라고 하면 먼저 `hwpx.document_plan.v1` 또는 `hwpx.document_plan.v2`로 정규화한 뒤 validate → create → inspect 순서로 간다.
- 사용자가 정부보고서, 범정부오피스식 보고, 공문형 보고서, □/○/※ 불릿, 단위 표기 표를 요구하면 `government_report` preset과 `tableProfile="government"`를 우선한다. MCP가 있으면 `parse_government_report_text` → `compute_report_value` → `create_government_report_document` 경로를 사용한다.
- 사용자가 템플릿 1개와 CSV/JSON/행 데이터를 주고 학생별 가정통신문, 상장, 수료증, 안내장처럼 N부 생성을 요구하면 반복 `fill_template` 호출 대신 `mail_merge`를 우선한다.
- 사용자가 일반 표의 합계, 평균, 소계 행/열을 요구하면 수동 계산 대신 `table_compute`를 사용하고 `evidence[]`를 근거로 남긴다.
- 사용자가 "이 문서 서식대로", "참조 파일과 같은 양식으로", "템플릿 등록해 둬"라고 하면 `extract_style_profile` → `apply_style_profile_to_plan` → `create_document_from_plan` → `compare_style_profiles` 흐름을 우선한다. 반복 사용할 양식은 `register_template`로 등록하고 `list_templates`/`describe_template`로 조회한다.

## 빠른 의사결정

0. **HWPX가 깨졌거나 한컴에서 열리지 않는다**
   원본을 직접 덮어쓰지 말고 먼저 repair/recover 복사본을 만든다. MCP 서버가 있으면 `repair_hwpx(source_filename, output_filename, recover=false)`를 실행하고, 일반 ZIP open이 실패하거나 central directory 손상이 의심되면 `recover=true`로 다시 시도한다. MCP가 없으면 `hwpx-repair input.hwpx output.hwpx` 또는 `hwpx-repair --recover broken.hwpx repaired.hwpx`를 사용한다. 반환값/출력에서 `crc_ok` 또는 `crcOk`, `validatePackage.ok`, `openSafety.ok`, `reordered`, `recovered`를 evidence로 기록하고, 가능하면 Hancom Office HWP에서 실제 열람한다. 자세한 API는 [`references/api.md`](references/api.md)의 repair/recover 섹션을 본다.

1. **텍스트만 추출한다**
   `python3 scripts/text_extract.py input.hwpx`
   표 안 문단까지 포함하려면 `--include-nested`, 구조화된 결과가 필요하면 `--format json`을 사용한다.

2. **새 문서를 만들거나 본문을 간단히 편집한다**
   `HwpxDocument`를 사용한다. 문단 추가, 표 생성, 메모 삽입, 내보내기는 [`references/api.md`](references/api.md)와 [`examples/01_create_and_save.py`](examples/01_create_and_save.py)를 본다.

3. **머리글·쪽번호·리치 런·병합 표가 있는 새 문서를 조립한다**
   `hwpx.builder`의 `Document`, `Section`, `Paragraph`, `Run`, `Heading`, `Bullet`, `NumberedList`, `Table`, `Image`, `Header`, `Footer`, `PageNumber`, `PageBreak`를 사용한다. builder는 내부 XML을 직접 만들지 않고 `HwpxDocument` facade로 lowering하며, `save_to_path()`가 `BuilderSaveReport`를 반환한다. `hard_gates.package_validation`, `hard_gates.document_errors`, `hard_gates.reopen`, `hard_gates.editor_open_safety`가 `pass`인지 확인한다. `schema_lint`는 warning 가시화이고 하드 실패 기준이 아니다. `visual_review_required=True`이면 열린 문서 검토 evidence까지 남긴다. 예시는 [`examples/10_create_with_builder.py`](examples/10_create_with_builder.py), API는 [`references/api.md`](references/api.md)의 builder 섹션을 본다.

4. **정부보고서·공문형 보고서를 작성한다**
   붙여넣은 텍스트는 `parse_government_report_text`로 plan v2로 바꾸고, 금액/비율/증감률/날짜는 `compute_report_value`로 계산한다. 생성은 `create_government_report_document(filename, document_plan)`을 사용해 `government_report` preset과 품질 프로필을 자동 적용한다. MCP가 없으면 local Python에서 `create_document_from_plan(plan)`에 `preset="government_report"`인 plan v2를 넘기고 `inspect_document_authoring_quality(..., quality_profile="government_report")`로 확인한다. 예시는 [`examples/10_create_government_report.py`](examples/10_create_government_report.py), [`examples/10_mcp_government_report.md`](examples/10_mcp_government_report.md)를 본다.

4-1. **공문서 작성규정 lint와 결재란을 적용한다**
   공문, 내부 결재문서, 가정통신문, 회의록, 품의서처럼 행정문서 성격이 강하면 생성 후 `inspect_official_document_style()`을 실행한다. MCP 서버가 있으면 `inspect_official_document_style(filename=...)`를 사용하고, MCP가 없으면 local Python에서 `inspect_official_document_style(path_or_paragraphs)`를 호출한다. 규칙 근거는 [`references/official-document-rules.md`](references/official-document-rules.md)를 본다.

   확인할 항목:
   - 항목 표시는 `1.` -> `가.` -> `1)` -> `가)` -> `(1)` -> `(가)` 순서를 건너뛰지 않는다.
   - `끝.` 표시는 마지막 위치에 둔다. 붙임이 있으면 붙임 목록 뒤에 단독 `끝.` 문단을 둔다.
   - 붙임은 `붙임 1. 세부계획서 1부.`처럼 문서명, 부수, 마침표를 포함한다.
   - 날짜는 `2026. 6. 11.` 형식을 사용하고, 금액은 `1,000,000원`처럼 천 단위 구분을 둔다.
   - 콜론과 물음표 앞에는 공백을 두지 않는다.

   결재란은 builder에서는 `approval_box()`를 넣고, document-plan v2에서는 `{"type": "approval_box"}` block을 넣는다. 기본 열은 `기안`, `검토`, `결재`, `전결`이며 서명 영역은 병합 표로 생성된다.

   장르 레시피:
   - 외부 공문: `approval_box` -> `1. 관련` -> `2. 요청 사항` -> `붙임 ... 1부.` -> `끝.`
   - 내부 결재문서: `approval_box(labels=["기안", "검토", "결재"], delegated="전결")` -> 점검 개요 -> 조치 계획 -> `끝.`
   - 가정통신문: 안내 사항 -> 협조 요청 -> 날짜는 `2026. 6. 11.` 표기 -> `끝.`
   - 회의록: 회의 개요 -> 주요 논의 -> 참석자/일시 문단 -> `끝.`
   - 구입 품의서: 구입 목적 -> 소요 예산(`1,250,000원`) -> 견적서 붙임 -> `끝.`

   예제 생성과 open-safety/lint 검증:
   `python3 examples/11_official_document_recipes.py`

4-2. **메일머지 대량생산과 일반 표 계산을 수행한다**
   템플릿 HWPX에 `{{student}}`, `${teacher}`, `<<class_name>>` 같은 placeholder가 있고 CSV/JSON/행 데이터로 여러 부를 만들어야 하면 MCP의 `mail_merge(template_filename, data_rows=...|data_filename=..., output_dir=..., filename_pattern=..., zip_filename=...)`를 사용한다. 반환값에서 `createdCount`, `rowsWithIssues`, 각 `rows[].missingKeys`, `rows[].unresolvedPlaceholders`, `openSafety.ok`, `verification.openSafety.checkedCount`를 확인한다. 한 행이라도 결측 placeholder가 있으면 `ok=false`일 수 있지만 산출물의 openSafety는 별도로 확인한다.

   일반 표 계산은 MCP의 `table_compute(table, value_columns=[...], operations=["subtotal", "sum", "average"], group_by=..., label_column=..., append="rows|columns|both")`를 사용한다. 반환된 `computedTable`은 document-plan table block으로 다시 넣을 수 있고, `evidence[]`에는 operation, axis, sourceRowCount/sourceValueCount, result가 들어간다. MCP가 없으면 local Python에서 `mail_merge()`, `inspect_mail_merge_placeholders()`, `table_compute()`를 직접 호출한다.

   예제 생성과 open-safety 검증:
   `python3 examples/14_mail_merge_table_compute.py`

4-3. **참조 문서 서식을 이식하거나 템플릿을 등록한다**
   사용자가 참조 HWPX를 주며 같은 계열의 서식으로 새 문서를 만들라고 하면 MCP의 `extract_style_profile(filename)`로 페이지 크기·여백·폰트·표 열너비 프로파일을 뽑는다. 새 document-plan에 `apply_style_profile_to_plan(document_plan, style_profile=...)`을 적용한 뒤 `create_document_from_plan`으로 생성한다. 결과는 `compare_style_profiles(reference_filename=..., candidate_filename=...)`의 `pass=true`와 `verification.openSafety.ok=true`를 evidence로 남긴다.

   반복 사용할 양식은 `register_template(name, source_filename, registry_path=...)`로 등록한다. `list_templates(registry_path=...)`는 목록용, `describe_template(name, values=...)`는 style profile과 placeholder 미충전 리포트 확인용이다. `placeholderReport.missingKeys`가 비어 있지 않으면 채우기 전에 사용자 또는 데이터 소스에 값을 보강한다.

   문서 구조를 서식까지 읽어야 할 때만 `hwpx_extract_json(..., format_detail=true)`를 사용한다. 기본 `format_detail=false` 응답은 토큰 절약용으로 유지하며, 상세 옵션에서는 paragraph/run의 `charPrIDRef`, 글자색, underline, 표 셀 width/height/span/address 같은 format block을 확인한다.

5. **운영 계획서를 작성한다**
   먼저 요청을 `hwpx.document_plan.v1` JSON으로 정규화하고, `quality_profile="operating_plan"`을 켠다. MCP 서버가 연결되어 있으면 `validate_document_plan` → `analyze_document_plan` → `create_document_from_plan` → `inspect_document_authoring_quality` 순서로 간다. MCP가 없으면 `python-hwpx`의 `validate_document_plan()`, `create_document_from_plan()`, `inspect_document_authoring_quality(..., quality_profile="operating_plan")`, `inspect_operating_plan_quality()`를 직접 사용한다. `visual_review_required=true`이면 `scripts/visual_review.py` evidence에서 `current.status == "observed_pass"`와 `current.screenshot_path`까지 확인해야 제출 준비 완료라고 말할 수 있다. 예시는 [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py), [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md), [`examples/09_visual_review_loop.md`](examples/09_visual_review_loop.md)를 본다.

6. **승인된 양식을 보존하며 운영 계획서를 채운다**
   사용자가 특정 HWPX 양식이나 P6 기준선 기반 운영 계획서 작성을 요청하면 document-plan 새 문서 생성보다 template form-fit 경로를 우선한다. MCP 서버가 있으면 `analyze_template_formfit`으로 원본이 변하지 않았고 `unresolved_count == 0`인지 확인한 뒤, `apply_template_formfit(confirm=True)`로 원본과 다른 destination에만 적용한다. 결과에서 `source.preserved`, `validation.validate_package.ok`, `validation.validate_document.ok`, `validation.openSafety.ok`, `residual_markers.blocking == []`를 확인한다. `visual_review_required=True`이면 최종 제출 전 열린 문서/사람 검토 evidence가 필요하며, `current.status == "observed_pass"`가 아니거나 `current.screenshot_path`가 없으면 최종 제출 가능 상태라고 주장하지 않는다. 예시는 [`examples/08_template_formfit.py`](examples/08_template_formfit.py), [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md), [`examples/09_visual_review_loop.md`](examples/09_visual_review_loop.md)를 본다.

6-1. **누름틀/FORM 양식을 채운다**
   기존 HWPX 양식에 한글 누름틀 또는 FORM field가 있을 수 있으면 표 라벨 추론 전에 `list_form_fields`를 먼저 호출한다. 필드가 있으면 `fill_form_field` 또는 `analyze_form_fill`의 `kind="form-field"` 매핑을 우선 사용한다. `analyze_form_fill` 결과의 `confidenceGrade`가 `label-exact`이면 바로 진행할 수 있지만, `label-fuzzy` 또는 `position-guess`이면 적용 전에 사용자 확인을 받는다. `formFields.available=false`와 `fallback="table-label"`이 명시된 문서만 기존 표 라벨 경로로 처리한다.

7. **자연어 요청으로 새 문서를 완성한다**
   먼저 요청을 `hwpx.document_plan.v1` JSON으로 정규화한다. MCP 서버가 연결되어 있으면 `validate_document_plan` → `create_document_from_plan` → `inspect_document_authoring_quality` 순서로 간다. MCP가 없으면 `python-hwpx`의 `create_document_from_plan()`을 직접 사용한다. 예시는 [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)를 본다.

8. **문서 구조를 조사한다**
   텍스트 노드, 표 개수, 특정 OWPML 태그 분포를 확인할 때는 `ObjectFinder`를 사용한다. 예시는 [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)를 본다.

9. **플레이스홀더를 일괄 치환한다**
   표 셀까지 포함한 전역 치환이면 `python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{기관명}=OO구청" "{담당자}=홍길동"`을 사용한다. 치환 직후 네임스페이스 정리까지 하려면 `--auto-fix-ns`를 붙인다.

10. **ZIP-level 수정 후 네임스페이스만 다시 정리한다**
   `python3 scripts/fix_namespaces.py input.hwpx --inplace --backup`

## 작업 패턴

### 1) 가정통신문·공문·한글 양식 작성

- 새 파일이면 `HwpxDocument.new()`로 시작한다.
- 기존 양식을 채우는 작업이면 먼저 `list_form_fields`로 누름틀/FORM 필드를 확인한다. 필드가 있으면 `fill_form_field` 또는 `analyze_form_fill`의 form-field 매핑을 우선하고, 필드가 없을 때만 표/문단을 수정한다.
- 표 셀 입력은 `doc.add_table(...)`의 반환값에서 `set_cell_text(...)`를 호출한다.
- 저장은 `save_to_path(path)`를 사용한다. `save()`는 deprecated wrapper다.

관련 예제:
- [`examples/01_create_and_save.py`](examples/01_create_and_save.py)
- [`references/api.md`](references/api.md)

### 1-0) 조립형 builder 기반 새 문서 생성

문단 몇 개를 추가하는 수준을 넘어서 머리글/바닥글, 쪽번호, 리치 런, 다단계 목록, 병합/음영/열너비 표, 이미지, 페이지 나눔을 한 번에 조립해야 하면 `hwpx.builder`를 사용한다.

1. `Document(metadata=..., sections=[Section(...)])`로 객체모델을 만든다.
2. 본문은 `Heading`, `Paragraph(children=[Run(...)])`, `Bullet`, `NumberedList`, `Table`, `Image`, `PageBreak`로 구성한다.
3. 머리글/바닥글은 `Header`/`Footer` 안에 `Paragraph(children=[Run(...), PageNumber(...)])`를 넣는다.
4. `report = document.save_to_path(path)`를 호출한다.
5. `report.hard_gates["package_validation"] == "pass"`, `report.hard_gates["document_errors"] == "pass"`, `report.hard_gates["reopen"] == "pass"`를 확인한다.
6. `report.hard_gates["schema_lint"] == "warning"`은 스키마 warning 가시화이며, hard error가 아니면 `document_errors`는 pass다.
7. `report.visual_review_required=True`이면 Hancom Office HWP, ComputerUse, 또는 사람 viewer로 연 문서 검토 evidence를 남긴다.

관련 예제:
- [`examples/10_create_with_builder.py`](examples/10_create_with_builder.py)
- 검증: `python3 scripts/quickcheck.py --builder`

### 1-1) 선언형 document-plan 기반 새 문서 생성

사용자가 "회의록/운영계획서/가정통신문/보고서 초안을 HWPX로 만들어줘"처럼 새 문서 생성을 요청하면, 바로 저수준 XML을 만들지 말고 `hwpx.document_plan.v1`을 먼저 작성한다.

1. 제목, 메타데이터, heading, paragraph, bullets, table block으로 계획을 정규화한다.
2. MCP 서버가 있으면 `validate_document_plan(document_plan)`으로 비파괴 검증을 먼저 수행한다.
3. `ok=false`이면 `issues[].code`, `issues[].path`, `repairHints[]`를 읽고 plan을 수정한 뒤 `validate_document_plan`을 다시 실행한다. `can_create=false` 상태에서는 생성하지 않는다.
4. 검증이 통과하면 `create_document_from_plan(filename, document_plan)`으로 HWPX를 생성한다.
5. 반환된 `quality.validation.reopened`, `validate_package.ok`, `validate_document.ok`, `verification.openSafety.ok`, `visual_review_required`를 확인한다.
6. MCP가 없으면 local Python에서 `create_document_from_plan()`과 `inspect_document_authoring_quality()`를 사용한다.

관련 예제:
- [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)
- [`examples/06_mcp_document_plan.md`](examples/06_mcp_document_plan.md)
- 검증: `python3 scripts/quickcheck.py --document-plan`

주의:
- v1은 headings, paragraphs, bullets, tables, page break 중심이다.
- 깨진 table은 `columns[].key`와 `rows[]`의 key를 먼저 맞춘다. 누락된 row key는 빈 셀로 생성되지만, 의도한 데이터라면 plan에서 보강한다.
- `unknown_style_token` 같은 style warning은 지원 token(`body`, `title`, `subtitle`, `heading`, `bullet`, `table_header`, `table_cell`)으로 바꾸거나 style을 생략한다.
- `validate_package.ok=false`, `validate_document.ok=false`, 또는 `verification.openSafety.ok=false`이면 `validation.*.issues[]`와 `recovery.repair_hints[]`를 확인하고 재저장/재생성한 뒤 다시 검사한다. 이 상태의 파일은 handoff하지 않는다.
- ZIP 자체가 열리지 않거나 `mimetype` 첫 엔트리/CRC 문제가 의심되면 편집 전에 `repair_hwpx` 또는 `hwpx-repair`로 복구 복사본을 만든 뒤 다시 검사한다.
- binary `.hwp`, 임의 OWPML 삽입, 복잡한 레이아웃 재현은 범위 밖이다.
- `visual_review_required=True`는 구조 검증은 통과했지만 렌더러/픽셀 검수는 하지 않았다는 뜻이다.

### 1-2) 운영 계획서 제출 후보 작성

사용자가 “운영 계획서”, “사업 운영 계획”, “학교 운영 계획”, “AI 중점학교 운영계획서”처럼 제출 가능한 계획서 작성을 요청하면 generic document-plan보다 운영 계획서 프로필을 우선한다.

1. 사용자 요청을 `hwpx.document_plan.v1`로 정규화한다.
2. 필수 구조를 포함한다: 신청 목적, 운영 계획, 추진 일정, 사업비/자원 사용 계획, 교육과정 또는 운영 체계, 기대 효과/성과 관리, 제출/확인 마감 문구.
3. 표는 최소 2개를 권장한다: `추진 일정`, `사업비 사용 계획`.
4. placeholder, `TODO`, `작성 필요`, `□□□□`, `○○` 같은 drafting marker를 남기지 않는다.
5. MCP가 있으면:
   - `validate_document_plan(document_plan)`
   - `analyze_document_plan(document_plan, quality_profile="operating_plan")`
   - `create_document_from_plan(filename, document_plan, quality_profile="operating_plan")`
   - `get_document_text(filename)` 및 `get_table_text(filename, table_index)`로 readback
6. MCP가 없으면:
   - `validate_document_plan(plan)`
   - `create_document_from_plan(plan)`
   - `inspect_document_authoring_quality(path, plan=plan, quality_profile="operating_plan")`
   - `inspect_operating_plan_quality(path, plan=plan)`
7. handoff 전 evidence를 확인한다:
   - `plan_validation.ok == true`
   - `quality.validation.reopened == true`
   - `quality.validation.validate_package.ok == true`
   - `quality.validation.validate_document.ok == true`
   - `verification.openSafety.ok == true`
   - file-only `inspect_operating_plan_quality(path).report_version == "operating-plan-quality-v1"`
   - file-only `inspect_operating_plan_quality(path).status == "ready"`
   - `quality.visual_review_required == true`이면 `scripts/visual_review.py` evidence 또는 ComputerUse/사람이 연 문서 검토 evidence가 있어야 함
   - visual-review evidence `schemaVersion == "hwpx.visual-review.v1"`
   - visual-review evidence `current.status == "observed_pass"`
   - visual-review evidence `current.screenshot_path`가 있어야 함 (`--observation`만으로는 부족)
   - visual-review evidence `summary.ready_for_submission_claim == true`
8. `status="needs_revision"` 또는 `gaps[]`가 있으면 `repair_hints[]`를 반영해 plan을 보강하고 다시 검증한다.
9. HWPX viewer가 없는 CI/컨테이너에서는 아래처럼 blocked evidence를 남기고, 제출 준비 완료가 아니라 viewer 검토 대기 상태로 handoff한다.

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_fallback.json --viewer none --status blocked --notes "No HWPX viewer is available in this environment." --layout-risk "Rendered page breaks and table fit require opened-document review."
```

예제:
- [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py)
- [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md)

검증:
- `python3 scripts/quickcheck.py --operating-plan`

### 1-3) P6 기준선 기반 양식 보존 form-fit

사용자가 승인된 AI 융합형 교육실 운영계획서 양식, P6 baseline, 또는 “기존 양식 그대로 채워줘”라고 요청하면 원본 양식을 직접 수정하지 않는다.

1. 먼저 `list_form_fields`로 누름틀/FORM 필드를 확인한다. 필드가 있으면 native field 채움 경로를 우선하고, `analyze_form_fill`의 `confidenceGrade`가 `label-fuzzy` 또는 `position-guess`인 항목은 사용자 확인 없이는 적용하지 않는다.
2. 기준선 JSON과 구조화된 content를 준비한다.
3. MCP 서버가 있으면 `analyze_template_formfit(source_filename, baseline, content, destination_filename)`을 먼저 호출한다.
4. `mutated=false`, `source.unchanged_after_analysis=true`, `unresolved_count=0`이 아니면 apply하지 않는다.
5. `apply_template_formfit(analysis=..., confirm=true)`를 호출한다.
6. handoff 전 evidence를 확인한다:
   - `handoff_status == "ready"`
   - `source.preserved == true`
   - `validation.validate_package.ok == true`
   - `validation.validate_document.ok == true`
   - `validation.openSafety.ok == true`
   - `residual_markers.blocking == []`
   - file-only `inspect_operating_plan_quality(destination).status == "ready"` 또는 남은 gap이 제출 전 수동 보완 가능하다는 근거
7. `visual_review_required=true`이면 `scripts/visual_review.py` evidence 또는 ComputerUse/사람이 연 문서 검토 evidence를 남긴다. evidence `schemaVersion == "hwpx.visual-review.v1"`이고 `current.status == "observed_pass"`이며 `current.screenshot_path`가 있을 때만 최종 제출 가능 상태라고 말한다. `--observation`만으로는 부족하다. HWPX viewer가 없으면 `--viewer none --status blocked` fallback evidence를 남기고, 열린 문서 검토가 필요하다고 handoff한다.

예제:
- [`examples/08_template_formfit.py`](examples/08_template_formfit.py)
- [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md)

검증:
- `python3 scripts/quickcheck.py --template-formfit`

### 2) 문서 텍스트 추출·검수·분석

- 텍스트만 필요하면 `scripts/text_extract.py`를 우선 사용한다.
- 하위 구조까지 포함한 문단 목록이 필요하면 `--format json --include-nested`를 사용한다.
- 표 개수, 특정 태그, 플레이스홀더 흔적을 조사할 때는 `ObjectFinder.find_all()`을 사용한다.

관련 예제:
- [`scripts/text_extract.py`](scripts/text_extract.py)
- [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)

### 3) 플레이스홀더 치환 전략

- **본문 런(run) 수준 치환만 필요하다**
  `replace_text_in_runs()`를 사용한다. 색상·밑줄 같은 스타일 필터도 줄 수 있다.

- **표 셀까지 포함한 전역 치환이 필요하다**
  `scripts/zip_replace_all.py`를 사용한다. 이 스크립트는 `mimetype` 엔트리를 `ZIP_STORED`로 유지하고, 임시 파일에 먼저 쓴 뒤 `validate_editor_open_safety()`를 통과한 경우에만 대상 HWPX를 교체한다. open-safety 검증이 실패하면 기존 output은 보존되며 handoff하지 않는다.

- **치환 키에 XML 조각이 들어 있다**
  `<`, `>`, `</`가 포함된 치환 키는 문서를 깨뜨릴 수 있다. 태그가 아닌 텍스트 플레이스홀더로 바꾼 뒤 치환한다.

관련 예제:
- [`scripts/zip_replace_all.py`](scripts/zip_replace_all.py)
- [`examples/03_template_replace.py`](examples/03_template_replace.py)

### 4) 불안정한 영역

- `set_header_text()`와 `set_footer_text()`는 문서/버전 조합에 따라 레이아웃이 흔들릴 수 있다.
- 자동화 파이프라인에서는 결과 파일을 다시 열어 반드시 검수한다.
- 헤더/푸터가 문제를 일으키면 템플릿에서 고정하고, 본문·표·메모만 자동화한다.

## 번들 리소스

- [`references/api.md`](references/api.md)
  `HwpxDocument`, `TextExtractor`, `ObjectFinder`, `HwpxPackage`의 시그니처와 주의사항만 모아둔 API 레퍼런스.

- [`references/official-document-rules.md`](references/official-document-rules.md)
  공문서 항목 표시, 끝 표시, 붙임, 날짜/금액, 문장부호, 결재란 규칙 근거.

- [`scripts/text_extract.py`](scripts/text_extract.py)
  원커맨드 텍스트 추출 CLI. 에이전트가 가장 먼저 시도하기 좋은 안전한 읽기 경로.

- [`scripts/zip_replace_all.py`](scripts/zip_replace_all.py)
  표 포함 전역 치환용 CLI 겸 import 가능한 함수 모듈.

- [`scripts/fix_namespaces.py`](scripts/fix_namespaces.py)
  ZIP-level 수정 후 XML 네임스페이스 선언을 다시 정리하는 후처리 스크립트.

- [`examples/01_create_and_save.py`](examples/01_create_and_save.py)
  새 문서 생성, 문단/표 추가, 저장 예제.

- [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)
  텍스트 추출과 구조 조사 예제.

- [`examples/03_template_replace.py`](examples/03_template_replace.py)
  템플릿 치환부터 namespace 정리까지의 전체 파이프라인 예제.

- [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)
  `hwpx.document_plan.v1` JSON에서 검증 가능한 HWPX를 생성하는 예제.

- [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py)
  운영 계획서 `document_plan`을 생성하고 `operating_plan` 품질 프로필까지 확인하는 예제.

- [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md)
  MCP 서버에서 운영 계획서를 검증, 분석, 생성, 품질 확인하는 호출 흐름.

- [`examples/08_template_formfit.py`](examples/08_template_formfit.py)
  baseline 기반 양식 보존 생성 local 예제.

- [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md)
  MCP 서버에서 `analyze_template_formfit` → `apply_template_formfit`로 원본을 보존하며 채우는 호출 흐름.

- [`examples/09_visual_review_loop.md`](examples/09_visual_review_loop.md)
  ComputerUse 또는 사람 viewer로 연 문서 시각 검토 evidence를 남기고, viewer가 없을 때 blocked fallback을 기록하는 반복 workflow.

- [`examples/10_create_with_builder.py`](examples/10_create_with_builder.py)
  `hwpx.builder`로 머리글/쪽번호, 리치 런, 목록, 병합/음영/열너비 표, 이미지, 페이지 나눔을 포함한 수직 슬라이스를 생성하는 예제.

- [`examples/11_official_document_recipes.py`](examples/11_official_document_recipes.py)
  외부 공문, 내부 결재문서, 가정통신문, 회의록, 품의서 예제와 open-safety/lint 검증.

## 실행 전 체크리스트

- `python-hwpx`와 `lxml`이 설치되어 있는지 확인한다.
- 결과 파일을 덮어쓸 때는 `--backup`을 사용한다.
- 자동화 결과물은 가능한 한 한 번 다시 열어본다.
- API 세부 옵션이나 최신 시그니처가 필요하면 항상 [`references/api.md`](references/api.md)를 먼저 읽는다.
- builder 예제를 쓰려면 `python-hwpx`가 S-013 builder core를 포함하는지 확인한다. 확인 명령은 `python3 scripts/quickcheck.py --builder`다.

## 제안서/기획안 생성 workflow

사용자가 “제안서”, “기획안”, “계획서” 형태의 새 HWPX 생성을 요청하면 저수준 XML 조작보다 `python-hwpx`의 proposal preset을 먼저 사용한다.

1. 자연어 요청을 `ProposalSpec` JSON으로 정규화한다.
2. `from hwpx.presets import create_proposal_document, inspect_proposal_quality`를 사용한다.
3. 생성 직후 `inspect_proposal_quality()`로 구조, 표, payload, validation, rubric 점수, `sample_match`를 확인한다.
4. 평균 점수 4.0 미만, `sample_match.pass == false`, 특정 sample-match dimension 실패, 필수 섹션 누락이면 `ProposalSpec`을 보강해 다시 생성한다.
5. 샘플에서 배운 anti-pattern: 큰 BMP 이미지에 의존하는 문서, 표/메타데이터가 이미지처럼 박힌 문서, 연락처/이메일/주소 등 PII가 redaction 없이 예제에 노출되는 문서는 피한다.
6. `visual_review_required=True`는 렌더러/픽셀 diff 없이 sample-derived proxy metric만 통과했다는 제한으로 해석한다.

예제: `examples/04_create_proposal.py`
검증: `python3 scripts/quickcheck.py --proposal`

## 양식 + 아이디어 기반 고품질 생성 workflow

사용자가 양식 HWPX와 대략적인 아이디어만 주고 “완성도 있게 작성해줘”라고 요청하면, 목표 품질 샘플을 매번 요구하지 않는다. 우선 `hwpx-mcp-server`의 MCP 품질 파이프라인을 사용한다.

1. 양식 파일을 `form_filename`으로 지정하고 사용자 요청을 `idea_brief` 또는 구조화된 content spec으로 정리한다.
2. `analyze_quality_generation(form_filename, idea_brief, destination_filename)`을 먼저 호출한다. 이 단계는 원본 양식을 변경하지 않고, 내장 품질 프로필과 생성 계획을 반환한다.
3. 분석 결과가 적절하면 `apply_quality_generation(analysis=..., confirm=True)`를 호출한다.
4. 결과의 `validation`과 `quality.gaps`, `revision_history`를 확인한다. 품질이 부족하면 같은 파이프라인으로 보강된 브리프나 수정 계획을 적용해 다시 생성한다.
5. 이 workflow의 일반 입력은 **양식 + 아이디어**다. 좋은 품질 샘플은 캘리브레이션/평가용으로만 쓰며 매번 필요한 입력으로 취급하지 않는다.

예시 MCP 호출 개념:

```json
{
  "form_filename": "inputs/form-template.hwpx",
  "idea_brief": "초등학생 AI 기초 소양과 교원 AI 수업 설계 역량을 강화하는 2026년 AI 중점학교 운영계획서를 작성한다.",
  "destination_filename": "outputs/ai-school-plan.hwpx"
}
```
