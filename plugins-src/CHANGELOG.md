# Changelog

## [Unreleased]

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
