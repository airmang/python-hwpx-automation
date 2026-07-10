---
name: hwpx
description: "한글 문서(.hwpx/OWPML) 편집·추출·자동화 스킬. '한글 문서 편집해줘', 가정통신문·공문·한글 양식 작성, HWPX 편집, 한글 파일/OWPML 분석, 플레이스홀더 치환, 문서 자동화 요청이면 이 스킬을 반드시 사용하세요. 줄간격·여백·쪽번호·머리글 등 서식 변경, 그림 삽입/교체, 문서 비교·신구대조표, 메일머지 대량생산(상장·수료증·가정통신문), 사진대지·회의명패·조직도 생성, 표 합계/소계 계산 요청도 모두 이 스킬의 대상입니다."
---

# hwpx (HWPX / OWPML)

`.hwpx`는 ZIP 기반 OWPML 문서다. 모든 작업은 `hwpx-mcp-server`의 MCP 도구를 1차 경로로 사용한다.
MCP가 없을 때의 local Python(`python-hwpx >= 2.11.1`) 대안과 번들 스크립트는 references 문서에만 있다.

## 시작 체크

MCP 서버가 연결되어 있으면 작업 전에 `mcp_server_health()`를 호출해
`version`, `pythonHwpxVersion`, `toolSurface.status`, `toolSurface.missingKeyTools`를 확인한다.
`toolSurface.status != "ok"`이거나 핵심 도구가 누락되면 플러그인 재설치
(`codex plugin remove hwpx-plugin@hwpx` 후 `codex plugin add hwpx-plugin@hwpx`)
또는 stale plugin venv/cache 제거 후 **새 호스트 세션**을 시작하라고 안내한다.
단위는 인간 단위다: 글자 크기 pt, 줄간격 %, 들여쓰기 mm, 문단 간격 pt, 용지/여백 mm.

## 케이스 → 경로 라우팅 표

| 사용자 요청 패턴 | 1차 경로 (MCP 도구) | 상세 참조 |
|---|---|---|
| 문서 구조·표·양식 필드·앵커를 한 번에 파악 | `get_document_map` | [workflows-editing](references/workflows-editing.md) |
| 텍스트·개요·표 내용 읽기 | `get_document_text` · `get_document_outline` · `get_table_text` | [api](references/api.md) |
| Markdown/HTML/JSON 변환·추출 | `hwpx_to_markdown` · `hwpx_to_html` · `hwpx_extract_json` · `document_to_markdown` · `document_extract_json` | [api](references/api.md) |
| 런서식(굵게·색·크기·글꼴) + 각주/미주 본문까지 충실 읽기 | `hwpx_extract_json` (`format_detail`·`doc.notes[]`) · `hwpx_to_markdown` (각주 부록) | [workflows-reading](references/workflows-reading.md) |
| 텍스트 위치·라벨 옆 셀 찾기 | `find_text` · `find_cell_by_label` | [workflows-editing](references/workflows-editing.md) |
| 본문·표 편집 (기본 경로, 2건 이상이면 필수) | `apply_edits` (dry_run → 확정) | [workflows-editing](references/workflows-editing.md) |
| 단건 치환·문단·표 셀 편집 | `search_and_replace` · `batch_replace` · `insert_paragraph` · `set_table_cell_text` | [workflows-editing](references/workflows-editing.md) |
| 직전 편집 되돌리기 | `undo_last_edit` | [workflows-editing](references/workflows-editing.md) |
| 줄간격·정렬·들여쓰기·문단 간격 변경 | `set_paragraph_format` | [workflows-editing](references/workflows-editing.md) |
| 용지 크기·방향·여백·단 설정 | `set_page_setup` | [workflows-editing](references/workflows-editing.md) |
| 머리글/바닥글 추가·수정 | `set_header_footer` | [workflows-editing](references/workflows-editing.md) |
| 쪽번호 추가·수정 | `set_page_number` | [workflows-editing](references/workflows-editing.md) |
| 기존 문단을 불릿/번호 목록으로 | `set_list_format` | [workflows-editing](references/workflows-editing.md) |
| 그림 삽입 / 그림만 교체 | `insert_picture` · `replace_picture` | [workflows-editing](references/workflows-editing.md) |
| 굵게·색·글꼴 등 글자 서식, 사용자 스타일 | `format_text` · `create_custom_style` · `list_styles` | [workflows-editing](references/workflows-editing.md) |
| 표 병합·분할·머리행 표시 | `merge_table_cells` · `split_table_cell` · `format_table` | [workflows-editing](references/workflows-editing.md) |
| 검토 메모 추가·삭제 | `add_memo` · `add_memo_by_anchor` · `remove_memo` | [workflows-editing](references/workflows-editing.md) |
| 충실도 민감·대형 문서의 문단 텍스트 패치 | `byte_preserving_patch` | [workflows-editing](references/workflows-editing.md) |
| 생성/편집 후 레이아웃 확인 | `render_preview` self-check 루프 | [workflows-editing](references/workflows-editing.md) |
| 자연어 요청으로 새 문서 생성 | `validate_document_plan` → `create_document_from_plan` | [workflows-creation](references/workflows-creation.md) |
| Markdown/비-HWPX 원본에서 HWPX 초안 생성 | `document_to_markdown` → `markdown_to_document_plan` → `create_document_from_plan` | [workflows-creation](references/workflows-creation.md) |
| 공문·보고서·가정통신문 (유형별 한컴 양식 프로파일 + 공문 구조 hard-gate·결문 메타·맞춤법 정직보고) | `create_document_from_plan` (`metadata.document_type` + `gyeolmun`) | [workflows-authoring](references/workflows-authoring.md) |
| 살아있는 목차(한컴이 재계산)·쪽 번호 상호참조 | `add_toc` · `add_cross_reference` · `verify_toc` | [workflows-toc](references/workflows-toc.md) |
| 변경추적 redline 저작 (삽입/삭제/치환 + 코멘트, 사람이 한컴서 수락/거부) | `add_tracked_edit` (+ `add_memo_by_anchor`) | [workflows-redline](references/workflows-redline.md) |
| 개인정보(PII) 탐지·마스킹 (양식채움·메일머지·추출 기본 마스킹, 가명/비식별) | `scan_personal_info` · `masking_policy` param | [workflows-pii](references/workflows-pii.md) |
| 머리글·쪽번호·리치 런·병합 표 조립 생성 | `hwpx.builder` (local) | [workflows-creation](references/workflows-creation.md) |
| 정부보고서·공문형 보고서 (□/○/※ 불릿) | `parse_government_report_text` → `compute_report_value` → `create_government_report_document` | [workflows-creation](references/workflows-creation.md) |
| 운영 계획서 제출 후보 | document-plan + `quality_profile="operating_plan"` | [workflows-creation](references/workflows-creation.md) |
| 제안서·기획안 | `create_proposal_document` → `inspect_document_quality` | [workflows-creation](references/workflows-creation.md) |
| 공문서 작성규정 lint·결재란 | `inspect_official_document_style` | [workflows-creation](references/workflows-creation.md), [규정](references/official-document-rules.md) |
| 직인/관인 날인 (발신명의 끝글자에 도장) · 날인 규정 pass/fail 검사 | `place_seal` · `check_seal_compliance` | [workflows-forms](references/workflows-forms.md) |
| 누름틀/FORM 필드 채움 | `list_form_fields` → `fill_form_field` / `analyze_form_fill` → `apply_form_fill` | [workflows-forms](references/workflows-forms.md) |
| 승인된 양식 보존 채움 (baseline) | `analyze_template_formfit` → `apply_template_formfit` | [workflows-forms](references/workflows-forms.md) |
| 양식 + 아이디어로 고품질 완성 | `analyze_quality_generation` → `apply_quality_generation` | [workflows-forms](references/workflows-forms.md) |
| 채우며 표 구조 변경 (열/표 삭제·행 증설, **재생성 금지**·바이트보존) | `get_document_map` → `apply_table_ops`(fill_cell+delete_column/row/table+insert_row_by_clone) → `verify_form_fill` | [workflows-forms](references/workflows-forms.md) |
| **평가계획(교수학습운영 및 평가계획) 한-방 채움** (빈 양식+검토용 md → gold 채움본, 2015/2022개정 자동·바이트보존·정직 needs_review) | `apply_evalplan_fill`(renderCheck='required'[+scoreGoldPath] → `score_form_fill`) | [workflows-forms](references/workflows-forms.md) |
| 출제 md를 학교 시험지 양식에 재조판 (문항 keep-together, 그림은 placeholder) | `compose_exam` · `verify_question_splits` | [workflows-exam](references/workflows-exam.md) |
| 메일머지 N부 대량생산 (상장·수료증·안내장·명부 CSV/XLSX) · 셀 넘침 격리(fit) | `mail_merge` (`fit_mode`) | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 표 합계·평균·소계 계산 | `table_compute` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 두 문서/문단 비교 (신구 diff) | `doc_diff` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 신구대조표 문서 생성 | `create_comparison_table_document` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 사진대지 생성 | `build_image_grid` → `create_document_from_plan` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 회의 명패 생성 | `build_meeting_nameplates` → `create_document_from_plan` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 조직도 생성 | `build_organization_chart` → `create_document_from_plan` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 참조 문서 서식 이식·템플릿 등록 | `extract_style_profile` · `apply_style_profile_to_plan` · `register_template` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 붙임·표/그림 번호 정합성 검사 | `inspect_reference_consistency` | [workflows-bulk-compare](references/workflows-bulk-compare.md) |
| 깨졌거나 한컴에서 안 열리는 파일 | `repair_hwpx` (복구 복사본 생성) | [api](references/api.md) |
| 원본 보존용 사본 만들기 | `copy_document` | [api](references/api.md) |
| MCP 없음: 텍스트 추출·표 포함 전역 치환 | `scripts/text_extract.py` · `scripts/zip_replace_all.py` | [api](references/api.md) |

## 공통 안전 수칙

- **원본 보존**: 기존 문서를 편집할 때는 원본을 직접 덮어쓰지 말고 `copy_document` 사본 또는
  별도 destination에서 작업한다. 양식 채움은 항상 원본과 다른 destination에만 적용한다.
- **openSafety**: 모든 쓰기 도구 응답의 `openSafety.ok == true`
  (또는 `verification.openSafety.ok == true`)를 확인한다. false인 파일은 handoff하지 않는다.
- **dry_run 우선**: 쓰기 도구는 `dry_run=true`로 `semanticDiff`를 먼저 확인한 뒤 확정 저장한다.
- **증거 계약**: `visual_review_required=true`이면
  [`references/evidence-contract.md`](references/evidence-contract.md)의 요건
  (`current.status == "observed_pass"` + `current.screenshot_path`)을 충족하기 전에는
  최종 제출 가능 상태라고 주장하지 않는다.
- 깨졌거나 열리지 않는 파일은 편집 전에 `repair_hwpx`로 복구 복사본을 만든다.
- 치환 키에 `<`, `>` 같은 XML 조각을 넣지 않는다. 태그가 아닌 텍스트 플레이스홀더만 치환한다.

## 편집 표준 루프

1. `get_document_map(filename)` — 개요·표·양식 필드·앵커와 `document_revision`을 확보한다.
2. `apply_edits(filename, operations, dry_run=true)` — `semanticDiff`와 `openSafety.ok`를 확인한다.
3. diff가 의도와 일치하면 `apply_edits(filename, operations, expected_revision=<1의 document_revision>)`로 확정한다.
4. 응답의 `ok`, `openSafety.ok`, `semanticDiff`를 확인한다.
   `reason: "document revision mismatch"`면 문서를 다시 읽고 새 revision으로 재시도한다.
5. 결과가 잘못됐으면 `undo_last_edit(filename)`로 직전 저장 전 상태로 되돌린다.
6. 재시도 위험이 있는 자동화에서는 `idempotency_key`를 부여해 중복 적용을 막는다.

연산 스키마와 응답 키 상세는 [`references/workflows-editing.md`](references/workflows-editing.md)를 본다.

## 참조 인덱스

- [`references/workflows-editing.md`](references/workflows-editing.md) — 트랜잭션 편집 루프, 서식 5종, 그림, byte patch, render_preview.
- [`references/workflows-creation.md`](references/workflows-creation.md) — document-plan, builder, 정부보고서, 운영계획서, 제안서, 공문서 레시피.
- [`references/workflows-redline.md`](references/workflows-redline.md) — 변경추적 저작(insert/delete/replace + 코멘트), 사람이 한컴서 수락/거부, verify 영수증. `add_tracked_edit`. `hwpx-mcp-server>=2.9.0`.
- [`references/workflows-pii.md`](references/workflows-pii.md) — 개인정보(PII) 탐지·마스킹(양식채움·메일머지·추출 기본 마스킹) + 가명/비식별. `scan_personal_info` · `mask` param. `hwpx-mcp-server>=2.10.0`.
- [`references/workflows-reading.md`](references/workflows-reading.md) — 런서식(굵게·색·크기·글꼴)+각주/미주 본문 충실 읽기. `hwpx_extract_json`(`format_detail`·`doc.notes[]`)·`hwpx_to_markdown` 각주 부록, `document_to_markdown` 로컬 ingest.
- [`references/workflows-toc.md`](references/workflows-toc.md) — 네이티브 자동 차례·상호참조(재페이지네이션 시 한컴이 재번호). `add_toc`·`add_cross_reference`·`verify_toc`. `hwpx-mcp-server>=2.12.0`.
- **처음 이 스킬로 HWPX 작업 시작 시**: `describe_capabilities`로 실제 FastMCP 작업군을 확인한다. 정확한 default/advanced/필수 도구 계약은 자동 생성된 [`tool-contract.generated.md`](references/tool-contract.generated.md)가 정본이다.
- [`references/workflows-forms.md`](references/workflows-forms.md) — 양식 4경로 결정표 + **⓪ 처음 보는 양식 정찰·상의(동적 form-fill)**. `scan_form_guidance`·`apply_body_ops`·`apply_table_ops`(split_cell_vertical·clone_table 등)·`inspect_fill_residue`·`verify_form_fill`. `hwpx-mcp-server>=2.17.0`.
- [`references/workflows-exam.md`](references/workflows-exam.md) — 시험지 조판: 출제 md→학교 양식 재조판, 문항 keep-together, 커브-export 정직 게이트(시각 증거). `hwpx-mcp-server>=2.7.0`.
- [`references/workflows-bulk-compare.md`](references/workflows-bulk-compare.md) — 메일머지, 표 계산, 신구대조, 생성기 3종, 스타일 프로파일/템플릿.
- [`references/evidence-contract.md`](references/evidence-contract.md) — openSafety·visual-review v1·hard gates·제출 증거 계약.
- [`references/api.md`](references/api.md) — python-hwpx 시그니처, MCP 도구 표, repair/recover, 번들 스크립트.
- [`references/official-document-rules.md`](references/official-document-rules.md) — 공문서 항목 표시·끝 표시·붙임·날짜/금액 규칙.
- 설치 직후 최소 검증: `python3 examples/01_create_and_save.py` → `python3 scripts/text_extract.py examples/out/01_created.hwpx`.
