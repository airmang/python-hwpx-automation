---
name: hwpx
description: "한글 문서(.hwpx/OWPML) 편집·추출·자동화 스킬. '한글 문서 편집해줘', 가정통신문·공문·한글 양식 작성, HWPX 편집, 한글 파일/OWPML 분석, 플레이스홀더 치환, 문서 자동화 요청이면 이 스킬을 반드시 사용하세요. 줄간격·여백·쪽번호·머리글 등 서식 변경, 그림 삽입/교체, 문서 비교·신구대조표, 메일머지 대량생산(상장·수료증·가정통신문), 사진대지·회의명패·조직도 생성, 표 합계/소계 계산 요청도 모두 이 스킬의 대상입니다."
---

# hwpx (HWPX / OWPML)

`.hwpx`는 ZIP 기반 OWPML 문서다. 모든 작업은 `hwpx-mcp-server`의 MCP 도구를 1차 경로로 사용한다.
MCP가 없을 때의 local Python(`python-hwpx >= 2.29.0`) 대안과 번들 스크립트는 references 문서에만 있다.

일반적인 읽기·편집·양식 채움·문서 생성처럼 여러 단계를 거치는 작업은 서버가 상태와 안전 정책을
강제하는 `start_workflow`를 1차 경로로 쓴다. `get_workflow`·`continue_workflow`로 진행하고,
`decision`에서만 `approve_workflow_decision`을 호출한다. 중단·재개는 `cancel_workflow`·`resume_workflow`를
쓴다. 큰 결과의 `resultRef`는 `get_workflow_result`로 회수한다. typed 입력과 영수증 계약은
[workflows-autonomous](references/workflows-autonomous.md)를 본다.
primitive 도구는 workflow가 지원하지 않는 전문 작업 또는 진단용 escape hatch다. 단, 처음 보는
기존 문서의 semantic 구조를 탐색하고 블록 이동·복사를 포함한 이종 편집을 한 번에 적용하는 요청은
`get_document_node` → `query_document_nodes` → `apply_document_commands` 경로를 쓴다.
지원되는 문서·하위 트리를 다른 HWPX로 이식할 때는 같은 경로로 source/target canonical path를
확정한 뒤 `dump_document_blueprint` → manifest의 unsupported/fidelity 검토 →
`replay_document_blueprint`(dry-run → commit)를 쓴다.

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
| 낯선 기존 문서의 구조 탐색 + 본문·표·블록 이종 편집·이동·복사 | `get_document_node` → `query_document_nodes` → `apply_document_commands` (dry-run → commit) | [workflows-agent-document](references/workflows-agent-document.md) |
| 지원 문서·결재/양식 블록을 다른 HWPX로 안전하게 이식 | `get_document_node`/`query_document_nodes` → `dump_document_blueprint` → `replay_document_blueprint` (dry-run → commit) | [workflows-agent-blueprint](references/workflows-agent-blueprint.md) |
| 일반 복합 HWPX 읽기·편집·양식 채움·생성 | `start_workflow` → `continue_workflow` → 필요 시 `approve_workflow_decision` | [workflows-autonomous](references/workflows-autonomous.md) |
| 비공개 코퍼스의 단일 합성 문서편집 연습 | `start_practice_scenario` → `apply_practice_scenario(confirm=false)` → 검토 후 `confirm=true` | [workflows-private-practice](references/workflows-private-practice.md) |
| 비공개 코퍼스의 내구성 합성 캠페인 연습 | `start_practice_campaign` · `get_practice_campaign` · `continue_practice_campaign` · `cancel_practice_campaign` · `export_practice_campaign` | [workflows-private-practice](references/workflows-private-practice.md) |
| 최종 산출물을 실제 한컴으로 렌더·검증 | `render_health` → `render_submit` → `render_status` | [workflows-real-hancom-render](references/workflows-real-hancom-render.md) |
| 페이지 PNG fixture 전 페이지 결함 검수·제한적 자동수정 | `visual_review_fixture` → 안전한 항목만 `visual_repair_fixture` | [workflows-visual-fixture-qa](references/workflows-visual-fixture-qa.md) |
| 합성 fixture 블라인드 실무평가·공개 projection | `run_fixture_benchmark` → 독립 `agent_judge` 2회 → `export_fixture_benchmark` | [workflows-fixture-benchmark](references/workflows-fixture-benchmark.md) |
| 양식 채움·기존 좌표 편집용 구조·표·필드·앵커 지도 | `get_document_map` | [workflows-editing](references/workflows-editing.md) |
| 텍스트·개요·표 내용 읽기 | `get_document_text` · `get_document_outline` · `get_table_text` | [api](references/api.md) |
| Markdown/HTML/JSON 변환·추출 | `hwpx_to_markdown` · `hwpx_to_html` · `hwpx_extract_json` · `document_to_markdown` · `document_extract_json` | [api](references/api.md) |
| 런서식(굵게·색·크기·글꼴) + 각주/미주 본문까지 충실 읽기 | `hwpx_extract_json` (`format_detail`·`doc.notes[]`) · `hwpx_to_markdown` (각주 부록) | [workflows-reading](references/workflows-reading.md) |
| 텍스트 위치·라벨 옆 셀 찾기 | `find_text` · `find_cell_by_label` | [workflows-editing](references/workflows-editing.md) |
| 이미 인덱스·앵커가 확정된 본문·표 좌표 편집 (2건 이상) | `apply_edits` (dry_run → 확정) | [workflows-editing](references/workflows-editing.md) |
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
- **blueprint 정직성**: `unsupported`가 비었고 strict `fidelity.ok == true`인 replayable bundle만
  이식한다. raw XML·ZIP 내부 XML·package path를 직접 편집하거나 degraded를 exact로 부르지 않는다.
- **증거 계약**: `visual_review_required=true`이면
  [`references/evidence-contract.md`](references/evidence-contract.md)의 요건
  (`current.status == "observed_pass"` + `current.screenshot_path`)을 충족하기 전에는
  최종 제출 가능 상태라고 주장하지 않는다.
- 깨졌거나 열리지 않는 파일은 편집 전에 `repair_hwpx`로 복구 복사본을 만든다.
- 치환 키에 `<`, `>` 같은 XML 조각을 넣지 않는다. 태그가 아닌 텍스트 플레이스홀더만 치환한다.

## 낯선 문서 구조 편집 루프

1. `get_document_node(filename, path="/", depth=2)`로 bounded 구조와 `revision`을 얻는다.
2. `query_document_nodes(..., limit=<bounded>)`로 후보를 좁히고 한 canonical path를 확정한다.
   여러 후보 중 첫 항목을 임의 선택하거나 `volatilePath`를 다른 revision에서 재사용하지 않는다.
3. 관련 변경을 한 `apply_document_commands(..., dry_run=true)` batch로 검토한다.
4. diff가 맞으면 **새 idempotency key**로 commit한다. commit 재시도에만 같은 key를 쓴다.
5. `ok`, `rolledBack == false`, `openSafety.ok`, 선언한 검증 영수증을 확인한다.

스키마·오류 복구·CLI replay는
[`references/workflows-agent-document.md`](references/workflows-agent-document.md)를 본다. 양식·시험·PII·
메일머지·lint 같은 도메인 작업은 이 generic 경로로 낮추지 않고 전문 도구를 유지한다.

## 블루프린트 이식 루프

1. source와 target을 각각 `get_document_node`/`query_document_nodes`로 읽어 revision-bound canonical
   path를 확정한다. 여러 후보 중 첫 항목을 임의 선택하지 않는다.
2. 교차 문서 이식은 `mode="portable"`로 `dump_document_blueprint`를 호출한다. 같은 source fingerprint에만
   재생할 때만 `source-bound`를 쓴다.
3. 반환 manifest의 `unsupported`, `fidelity`, dependency/resource 수, `blueprintHash`를 검토한다.
   inspect/edit가 필요하면 `hwpx dump --inspect`로 typed JSON만 꺼내고 `hwpx dump --repack`으로 안전하게
   재포장한다. ZIP/XML을 직접 고치지 않는다.
4. `replay_document_blueprint`에 bundle hash, target input/output, targetParent, position, mode,
   `expectedRevision`, strict mapping, idempotency key, 검증 요구사항을 모두 넣고 먼저 `dryRun=true`로 실행한다.
5. dry-run의 node/dependency map, `exact|mapped|degraded|unsupported` fidelity와 semantic diff를 확인한다.
   commit에는 새 idempotency key를 쓰고, 동일 요청 재시도에만 같은 key를 쓴다.
6. commit에서 `rolledBack == false`, package/reopen/reference/resource/byte preservation,
   `openSafety.ok`, domain 영수증을 확인한다. 실패하면 output이 보존됐는지 확인하고 성공으로 간주하지 않는다.
7. 실제 한컴 검증이 요구되면 `render_health` → `render_submit` → `render_status`의 matching full-page
   영수증까지 받아야 한다. oracle unavailable/mismatch는 `unverified`다.

전체 envelope·CLI·실패 처리와 전문 workflow 경계는
[`references/workflows-agent-blueprint.md`](references/workflows-agent-blueprint.md)를 본다.

## 확정 좌표 편집 표준 루프

1. `get_document_map(filename)` — 개요·표·양식 필드·앵커와 `document_revision`을 확보한다.
2. `apply_edits(filename, operations, dry_run=true)` — `semanticDiff`와 `openSafety.ok`를 확인한다.
3. diff가 의도와 일치하면 `apply_edits(filename, operations, expected_revision=<1의 document_revision>)`로 확정한다.
4. 응답의 `ok`, `openSafety.ok`, `semanticDiff`를 확인한다.
   `reason: "document revision mismatch"`면 문서를 다시 읽고 새 revision으로 재시도한다.
5. 결과가 잘못됐으면 `undo_last_edit(filename)`로 직전 저장 전 상태로 되돌린다.
6. 재시도 위험이 있는 자동화에서는 `idempotency_key`를 부여해 중복 적용을 막는다.

연산 스키마와 응답 키 상세는 [`references/workflows-editing.md`](references/workflows-editing.md)를 본다.

## 참조 인덱스

- [`references/workflows-autonomous.md`](references/workflows-autonomous.md) — 서버 강제 5-family workflow, decision/재개/needs_review/사전 렌더 영수증 계약.
- [`references/workflows-agent-document.md`](references/workflows-agent-document.md) — 낯선 문서 semantic view/query, canonical path, 원자 set/add/remove/move/copy batch, structured failure와 CLI replay.
- [`references/workflows-agent-blueprint.md`](references/workflows-agent-blueprint.md) — typed `.hwpxbp` dump/inspect/repack, portable/source-bound dependency mapping, atomic replay, strict fidelity와 real-Hancom 검증.
- [`references/workflows-private-practice.md`](references/workflows-private-practice.md) — 비공개 원본 경로·평가 gold를 노출하지 않는 단일 scenario와 내구성 campaign 실행. `needs_review`·`unverified`를 성공으로 올리지 않으며 개선안 자동 채택·게시·병합·릴리스를 하지 않는다.
- [`references/workflows-real-hancom-render.md`](references/workflows-real-hancom-render.md) — 비동기 실한컴 제출·폴링·artifact provenance·취소·degraded 처리.
- [`references/workflows-visual-fixture-qa.md`](references/workflows-visual-fixture-qa.md) — fixture 전 페이지 검수, 원시 finding·evidence ledger, 최대 3회 안전수정, unsafe/unmapped escalation. **fixture는 절대 `renderChecked=true`가 아니다.**
- [`references/workflows-fixture-benchmark.md`](references/workflows-fixture-benchmark.md) — 72개 합성 work order, 동일 workflow 계약의 세 fixture profile, 익명 artifact, 독립 agent-judge 서식과 단일 manifest projection. **사람·실제 agent·실한컴·대체 주장 증거가 아니다.**
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
