# Changelog

## 0.1.28 — 2026-07-12

- S-070 합성 블라인드 qualification fixture를 추가했다: 6개 family의 work order 72개,
  must-abstain 12개, 동일 workflow 계약의 versioned fixture profile 3개, 익명 artifact 216개.
- 독립 `agent_judge` 2회용 빈 템플릿과 단일 result manifest 기반 report/gallery/scorecard
  projection 및 drift gate를 추가했다. 사람/실제 agent/실한컴/대체 주장은 모두 fail-closed다.
- 설치 MCP 표면의 `run_fixture_benchmark`와 `export_fixture_benchmark`를 검증하는 E2E를 추가했다.
- 번들 기준을 `python-hwpx==2.27.0`, `hwpx-mcp-server==2.21.0`, 스킬 `0.1.28`로 갱신했다.

## [Unreleased]

### Added
- 문서 투영·조회·원자 명령을 하나의 경로로 묶는 agent document workflow와
  `get_document_node`, `query_document_nodes`, `apply_document_commands` 3도구 라우팅.
- 페이지 PNG fixture의 전 페이지 결함 검수, append-only evidence ledger, 최대 3회 안전수정과
  unsafe/unmapped escalation을 안내하는 스킬 라우팅 및 설치 MCP leap-demo 하네스.
- fixture 영수증은 절대 `renderChecked=true` 또는 실한컴 검증으로 승격하지 않는 hard rule.
- 비동기 실한컴 `render_health` → `render_submit` → `render_status`/`render_cancel` 라우팅과
  입력·출력 hash, Hancom build, worker provenance, PDF/페이지 PNG 검증 절차.
- 설치 플러그인 MCP E2E에 4개 render 도구와 honest unavailable/선택적 real-render 게이트 추가.

### Changed
- 다음 설치 후보 결속을 `python-hwpx==2.28.0`, `hwpx-mcp-server==2.22.0`,
  스킬 `0.1.29`로 올려 새 통합 계약보다 낮은 구성은 capability handshake에서 거부한다.
- 번들 기준을 `python-hwpx==2.26.0`, `hwpx-mcp-server==2.20.0`, 스킬 `0.1.27`으로 갱신.

## [0.1.25] - 2026-07-10
### Fixed
- FastMCP 2.18.1 핫픽스를 고정해 universal form-fill 7도구가 설치 플러그인 표면에서 실제 호출되도록 복구.
- 런처가 실제 스킬 버전 0.1.25를 capability handshake에 전달하고, clean-install smoke용
  local-editable 비활성화/패키지 override를 지원.
- ToolSpec에서 생성한 default/advanced/필수 도구 API 인덱스를 4호스트 번들에 포함.

## [0.1.24] - 2026-07-09
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.18.0`으로 갱신.


## [0.1.21] - 2026-07-06
### Fixed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.16.0`(`python-hwpx>=2.23.0`)으로 갱신. **styled-run 글자속성 픽스**를 배포: `add_paragraph`/`insert_paragraph`/`add_table`가 새 run에 문단 스타일의 글자속성을 실어 준다(기존엔 `charPrIDRef="0"` 기본값 → 0번이 제목용 큰 글자인 양식에서 본문이 통째로 커지는 버그; 예: KACE 투고양식은 charPr 0 = 17pt라 `j-본문` 본문이 17pt로 샜음 → 이제 9pt). 회귀 가드(`_enforce_run_char_pr`)로 재확인. 부수적으로 `hwpx-mcp-server` 2.16.0의 Spec 013 document ingest + Markdown-plan bridge 포함.

## [0.1.20] - 2026-07-03
### Added
- `references/workflows-forms.md` ④ 경로에 **폰트 shrink-to-fit** 안내: `fill_cell`의 `max_lines`로 셀을 N줄 안에 맞게 폰트 축소(열 너비 부족 시 세로 축소). 폼 기본 폰트가 작으면 autofit(가로)이 주력임을 명시.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.15.0`(폰트 축소맞춤)으로 갱신, `python-hwpx>=2.23.0` 필요.
- README 정비 471→178줄(5개 설치 섹션을 호스트별 1개로 통합, 긴 예제·중복 제거, 버전 최신화).

## [0.1.19] - 2026-07-03
### Added
- `references/workflows-forms.md` ④ 경로에 **열 너비 조정**: `apply_table_ops`의 `autofit_columns`(내용에 맞춰 열너비 재균형, 긴 텍스트의 세로 cramping 완화)·`set_column_widths`(명시적 지정) 안내. 한컴이 행 높이는 자동으로 늘리므로 autofit은 가로 재분배 미용 단계임을 명시.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.14.0`(열너비 op)으로 갱신, `python-hwpx>=2.22.0` 필요.

## [0.1.18] - 2026-07-03
### Added
- `references/workflows-forms.md` **④ 구조 변경 보존 채움** 경로 (M10/S-064): 채우며 표 구조를 바꿔야 하는 양식(안 쓰는 표·열 삭제, 내용에 맞춰 행 증설)을 `apply_table_ops`(fill_cell + delete_column/delete_row/delete_table + insert_row_by_clone)로 **원본 서식 보존한 채** 수술하고 `verify_form_fill`(실한컴 렌더 게이트)로 검증. "표 재생성 금지" 철칙 배너 + 매 학기 재사용 레시피(빈 양식 + 콘텐츠 md + 규칙). SKILL.md 라우팅 추가.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.13.0`(M10 form-fill 도구)으로 갱신, `python-hwpx>=2.21.0`(`hwpx.table_patch`) 필요.

## [0.1.15] - 2026-07-01
### Added
- `references/workflows-pii.md` — 개인정보(PII) 마스킹 워크플로 (M5/S-059). 양식채움·메일머지·추출이 기계검증 PII(주민등록번호·휴대폰·이메일·카드)를 **기본 마스킹**하고, `scan_personal_info` 로 감사. 기계세트=항상-on, 맥락형=라벨게이트 low-confidence(과마스킹 방지). SKILL.md 라우터 + 참조 목록 연결.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.10.0`(PII 마스킹 표면)으로 갱신, `python-hwpx>=2.18.0`(`hwpx.tools.pii`) 필요.

## [0.1.14] - 2026-06-30
### Added
- `references/workflows-redline.md` — 변경추적(redline) 저작 워크플로 (M4/S-058). `add_tracked_edit`(insert/delete/replace + 코멘트)로 에이전트가 redline을 저작하고 사람이 한컴 검토 리본에서 수락/거부. verify 영수증(render_checked 정직 강등)·byte-identity/수락방식의 정직 한계 명시. SKILL.md 라우터 + 참조 목록에 연결.
### Changed
- 번들 런처/MCP 설치 핀을 `hwpx-mcp-server==2.9.0`(`add_tracked_edit` redline 표면)으로 갱신, `python-hwpx>=2.17.0`(redline 저작 API + 메모 본문 픽스) 필요.

## [0.1.13] - 2026-06-29
### Added
- `references/workflows-authoring.md` + SKILL.md routing row — M3 document authoring (S-057): 공문/보고서/가정통신문 작성 루프(`create_document_from_plan` with `metadata.document_type` + `gyeolmun`), 공문 구조 hard-gate 해석, 맞춤법/각주 정직 라벨, HWPX-only. Added to `packaging/hosts.json` sharedAssets; 4 host bundles rebuilt.
### Changed
- Launcher pins `hwpx-mcp-server==2.8.0` (M3 surface: document_type routing, 결문 IR, 공문 hard-gate, `render_checked`; pulls `python-hwpx>=2.16.0`).

## [0.1.12] - 2026-06-27
### Added
- Route 시험지 조판(출제 md를 학교 양식에 재조판) → `compose_exam` · `verify_question_splits` and a new `references/workflows-exam.md`: 문항 keep-together(단/쪽 경계 미분리), 관리박스·머리글/꼬리글 무손실 보존, `[그림N]`/`[표N]`은 텍스트 placeholder, 한컴 커브-export 양식의 정직 게이트(`splits=null`+`needsReview` → `render_preview` 시각 증거, 텍스트 0 사칭 금지). 4개 호스트 번들에 reference 동봉. leap 데모: `demo/exam-typesetting/`.
### Changed
- 번들 Codex/Claude/OpenClaw/Hermes 런처 + MCP 설치 문서 핀을 `hwpx-mcp-server==2.7.0`(시험지 조판 `compose_exam`/`verify_question_splits` + keep-together)으로 갱신, `python-hwpx>=2.15.0`(`hwpx.exam`) 필요 (S-056 다운스트림 릴리스).

## [0.1.11] - 2026-06-25
### Added
- Route 직인/관인 날인 → `place_seal` · `check_seal_compliance` (발신명의 끝글자에 도장, 한컴 오라클로 0.12pt 검증; 오라클 없으면 `renderChecked=false` 정직 degrade) and a new `references/workflows-forms.md` ④ 날인 경로.
- Route fit-aware 메일머지 + 명부(CSV/XLSX) + 표 셀 placeholder → `mail_merge` `fit_mode` (셀 넘침/결측 행을 `needsReview[]`/`skipped[]`로 격리, `fitAware`).
### Fixed
- Pin bundled Codex/Claude/OpenClaw/Hermes launchers + MCP install docs to `hwpx-mcp-server==2.6.0` (place_seal/check_seal_compliance/mail_merge fit_mode + `[oracle]` extra), which requires `python-hwpx>=2.14.0`.

## [0.1.10] - 2026-06-25
### Fixed
- Pin bundled Codex/Claude launchers and MCP install docs to `hwpx-mcp-server==2.5.0` (Phase F VisualComplete quality contract — fail-closed `visualComplete` gate + capability handshake), which requires `python-hwpx>=2.12.0`.

## [0.1.9] - 2026-06-12
### Fixed
- Pin bundled Codex/Claude launchers and MCP install docs to `hwpx-mcp-server==2.4.1`, which pulls `python-hwpx>=2.11.1`.
- Generated document-plan reports now use real `개요 N`/`Outline N` paragraph styles and visible title/heading hierarchy by default, so one-shot report creation produces structured headings without follow-up prompting.
- Refresh skill/reference compatibility notes and task-eval current profile for the `0.1.9` bundle.

## [0.1.8] - 2026-06-12
### Changed
- SKILL.md를 390줄 매뉴얼 합본에서 99줄 케이스→경로 라우터(단일 라우팅 표 39행)로 재구성 — 발화당 컨텍스트 비용 약 67% 절감. 상세 워크플로는 `references/workflows-{editing,creation,forms,bulk-compare}.md`와 `references/evidence-contract.md`로 분리(증거 계약 4회 중복 → 1곳).
- 2.4.0 도구 표면 중 미안내였던 19종(트랜잭션 편집 `apply_edits`·`undo_last_edit`·revision 가드, 서식 편집 5종, 그림 2종, 신구대조 2종, 고급 생성기 3종, `get_document_map`, `byte_preserving_patch`)의 교육을 추가하고 편집 표준 루프를 1급 케이스로 승격.
- 평가 하니스 guidance 채점을 프로파일 태그 자기신고에서 스킬 번들 본문 검증으로 전환(태그만으로 통과 불가, 단위 테스트 보증). 평가 태스크 32→42개. 신 번들 42/42 vs 0.1.6 33/42 vs 0.1.5 25/42.

## [0.1.7] - 2026-06-12
### Changed
- 플러그인 런처를 `hwpx-mcp-server==2.4.0`(+ `python-hwpx>=2.11.0`)으로 핀 갱신 — 신뢰 루프(트랜잭션 편집·렌더 프리뷰·revision 가드)·서식 편집·누름틀·공문서 lint·고급 생성기·메일머지·서식 이식 도구 전체가 설치 플러그인에 노출된다 (배포 스큐 해소).
- SKILL.md·README·api.md의 호환 기준을 `python-hwpx >= 2.11.0`으로 갱신.

## [0.1.6] - 2026-06-09
### Fixed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.5`, which includes the editor-open safety gate backed by `python-hwpx>=2.10.3`.
- Validate ZIP-level script outputs before replacing targets so `zip_replace_all.py` and `fix_namespaces.py` do not leave editor-unsafe HWPX files behind.
- Make direct `zip_replace_all()` and `fix_namespaces()` helper-function calls use temporary output plus open-safety validation by default before replacing the requested target.
- Remove the public `verify_open_safety=False` bypass from ZIP-level helper functions; unchecked writes are now private implementation details used only before a later validation gate.
- Fail closed when ZIP-level helpers cannot import `validate_editor_open_safety`, instead of falling back to weaker legacy package/open checks.
- Normalize section/header root namespaces and `standalone="yes"` declarations in ZIP-level script outputs, matching the hardened `python-hwpx` save surface.
- Add explicit editor-open safety checks to `quickcheck.py` for the base output and optional proposal, document-plan, builder, operating-plan, and template form-fit outputs.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.6`.

## [0.1.3] - 2026-06-04
### Changed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.3`, which exposes document-plan v2 and government-report MCP tools backed by `python-hwpx>=2.10.1`.
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.3`.

## [0.1.2] - 2026-06-04
### Fixed
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.2`, which clears layout caches for placeholder form-fill text insertion paths.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.2`.

## [0.1.1] - 2026-06-04
### Fixed
- Remove stale HWPX `lineSegArray` layout caches from XML parts changed by `zip_replace_all.py` so Hancom recalculates text layout after replacements.
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.1`, which includes cross-run replacement fixes for overlapping glyphs.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.1`.

## [0.1.0]
### Added
- Added `hwpx.builder` onboarding docs, API reference, example, and quickcheck coverage for the S-013 builder core.

### Changed
- Updated bundled MCP fallback launchers to `hwpx-mcp-server==2.3.0`, which requires `python-hwpx>=2.10.0`.
- License relicensed to Apache-2.0 (sole author, full consent).
- Previous license terms no longer apply to future releases.
