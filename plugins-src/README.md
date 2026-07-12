<p align="center">
  <h1 align="center">📄 hwpx-plugins</h1>
  <p align="center">
    <strong>AI 에이전트가 HWPX 문서를 바로 읽고, 채우고, 만들고, 점검하게 해주는 공식 온보딩 스킬</strong>
  </p>
  <p align="center">
    순수 Python · 한컴오피스 불필요 · 크로스 플랫폼
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/v/python-hwpx?style=flat-square&color=blue" alt="PyPI"></a>
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/pyversions/python-hwpx?style=flat-square" alt="Python"></a>
    <a href="https://github.com/airmang/hwpx-plugins"><img src="https://img.shields.io/badge/repo-airmang%2Fhwpx--plugins-181717?style=flat-square" alt="Repo"></a>
    <a href="https://github.com/airmang/hwpx-plugins/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
</p>

---

## 🧩 HWPX Stack (3종)

| 계층 | 레포 | 역할 |
|---|---|---|
| 📦 라이브러리 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | 순수 파이썬 HWPX 파싱·편집·생성 코어 |
| 🔌 MCP 서버 | [`hwpx-mcp-server`](https://github.com/airmang/hwpx-mcp-server) | MCP 클라이언트(Claude Desktop, VS Code 등)에서 HWPX 조작 |
| 🎯 에이전트 스킬 | **[`hwpx-plugins`](https://github.com/airmang/hwpx-plugins)** | 에이전트가 HWPX를 바로 쓰게 해주는 공식 온보딩 스킬 |

---

## 왜 / 무엇을 하나

`hwpx-plugins`은 `python-hwpx` 기반의 공식 에이전트 스킬이다. HWPX를 잘 모르는 사용자도 **스킬만 설치하면** 에이전트에게 자연어로 말하는 것만으로 한글 문서를 다루게 하는 것이 목표다. 에이전트는 `SKILL.md`의 의사결정 트리를 따라 알맞은 스크립트나 MCP 도구를 스스로 호출한다.

- **읽기·추출** — `.hwpx` 텍스트, 표, 각주까지 추출 (JSON/Markdown)
- **양식 채움** — 승인된 양식을 그대로 두고 바이트 보존으로 셀만 채운다
- **문서 생성** — `hwpx.builder`로 머리글·쪽번호·표·이미지가 있는 새 문서를 조립
- **점검·복구** — 구조/품질 lint, 한컴에서 안 열리는 파일 repair
- 대상 포맷은 Open XML 기반 `.hwpx`다. 레거시 바이너리 `.hwp` 직접 편집은 범위 밖이다.

## 빠른 시작

의존성 설치 (모든 호스트 공통):

```bash
python3 -m pip install -U python-hwpx lxml
```

권장 기준: Python 3.10+ · `python-hwpx >= 2.26.0` · `hwpx-mcp-server >= 2.20.0` · 스킬 번들 `0.1.27`.

설치 직후 첫 성공 경로를 한 번에 확인:

```bash
python3 scripts/quickcheck.py
# [OK] basic hwpx skill workflow passed
```

이 스크립트는 Python 버전 → `python-hwpx`/`lxml` import → 예제 문서 생성 → 구조 점검 → 텍스트 추출을 한 번에 확인한다. 경로별로 더 검증하려면 `--builder`, `--document-plan`, `--operating-plan`, `--template-formfit`, `--visual-review` 플래그를 붙인다.

### 에이전트에게 말 걸기 (핵심 사용법)

설치 후 사용자가 직접 파이썬을 칠 일은 거의 없다. Claude Code·Cursor·Codex 같은 에이전트에게 자연어로 말하면 스킬이 트리거된다.

| 이렇게 말하면 | 에이전트가 하는 일 |
|---|---|
| "이 hwpx 텍스트 전부 뽑아줘" | 표 안 문단·각주 포함 텍스트 추출 |
| "`{학교명}`·`{담당자}` 자리표시자 전부 바꿔줘" | 표까지 포함한 플레이스홀더 전역 치환 |
| "이 양식은 그대로 두고 내용만 채워줘" | 바이트 보존 양식 form-fit (셀 채움·행/열 조정·한컴 검증) |
| "이 평가계획 양식 우리 학교 걸로 채워줘" | 빈 양식+검토용 초안 → 서식 맞춤 채움본(생성 후 검토 필요) |
| "머리글·쪽번호 들어간 운영 계획서 새로 만들어줘" | `hwpx.builder`로 레이아웃 민감 문서 조립 |
| "한컴에서 안 열리는 hwpx인데 복구해줘" | repair/recover 복구 복사본 생성 |
| "이 hwpx 구조랑 표 개수 점검해줘" | 구조·품질 점검 |

> **예시 —** 사용자: "첨부한 가정통신문 양식에서 학교명이랑 날짜만 우리 학교 걸로 바꿔서 새 파일로 줘."
> 에이전트: 원본을 보존한 채 form-fit으로 값을 채우고, 패키지·스키마 검증을 거친 새 파일을 돌려준다.

에이전트는 요청 성격에 따라 builder / document-plan / form-fit / repair 중 무엇을 쓸지 스스로 판단한다. 머리글·쪽번호·표처럼 레이아웃에 민감한 작업에서는 `visual_review_required`가 켜지므로, 에이전트는 최종 제출 전 열린 문서 시각 검토 evidence까지 같이 남긴다.

## 무엇을 하나

에이전트가 트리거하는 주요 기능을 테마별로 정리했다. 전체 도구·워크플로 목록은 [SKILL.md](SKILL.md)와 [references/](references/) 참고.

- **읽기** — 텍스트/표/각주 추출, JSON·Markdown 변환, 런서식 충실 읽기 · [workflows-reading.md](references/workflows-reading.md)
- **양식** — 누름틀(`list_form_fields`/`fill_form_field`) 1급 지원, **바이트 보존 구조적 form-fill**(셀 채움·행/열·표 삽입/삭제·열너비 자동맞춤·폰트 shrink-to-fit·실한컴 검증), 처음 보는 양식은 **정찰→상의→채움** 동적 흐름, **평가계획 한-방 채움**(생성 후 검토 필요) · [workflows-forms.md](references/workflows-forms.md)
- **생성** — `hwpx.builder`(머리글/바닥글·쪽번호·리치 런·목록·병합/음영/열너비 표·이미지·페이지 나눔), 선언형 `hwpx.document_plan.v1`, 공문·보고서·제안서 레시피 · [workflows-creation.md](references/workflows-creation.md) · [workflows-authoring.md](references/workflows-authoring.md)
- **편집** — 원자 적용 `apply_edits`(dry_run·revision 가드·멱등키)·`undo_last_edit`, 인간 단위 서식 편집, 추적 변경(redline) · [workflows-editing.md](references/workflows-editing.md) · [workflows-redline.md](references/workflows-redline.md)
- **공문서** — `inspect_official_document_style` lint·결재란 프리셋·장르 레시피, 신구대조표(`doc_diff`/`create_comparison_table_document`) · [official-document-rules.md](references/official-document-rules.md)
- **자동 TOC·상호참조** — 네이티브 목차 생성·페이지 재계산 트리거 · [workflows-toc.md](references/workflows-toc.md)
- **생산성** — `mail_merge` 대량 생산·`table_compute`, 서식 이식(`extract_style_profile`)·템플릿 레지스트리, 고급 생성기(사진대지·명패·조직도) · [workflows-bulk-compare.md](references/workflows-bulk-compare.md)
- **PII** — 개인정보 마스킹 게이트·scan · [workflows-pii.md](references/workflows-pii.md)
- **신뢰 루프** — `render_preview`(페이지 PNG 자기검증), package/schema/text 검증, 시각 검토 evidence 계약 · [evidence-contract.md](references/evidence-contract.md)

## 설치 (호스트별)

의존성(`python-hwpx lxml`)은 위 [빠른 시작](#빠른-시작)에서 한 번만 설치한다. 아래는 호스트별 진입점이다. **설치·재설치 후에는 새 에이전트 세션을 시작해야** 새 skill과 MCP 도구가 로드된다.

### Claude Code

```bash
claude plugin marketplace add airmang/hwpx-plugins
claude plugin install hwpx-plugin@hwpx
```

수동 설치를 원하면 이 레포를 `hwpx-plugins` 폴더째 프로젝트 로컬 `.claude/skills/hwpx-plugins/` 또는 글로벌 `~/.claude/skills/hwpx-plugins/`에 복사한다.

### Codex CLI

```bash
codex plugin marketplace add airmang/hwpx-plugins
codex plugin add hwpx-plugin@hwpx
```

수동 경로는 `.agents/skills/hwpx-plugins/`.

### Cursor

이 레포를 `.cursor/skills/hwpx-plugins/`(또는 글로벌 `~/.cursor/skills/`)에 복사하고, `.cursor/rules/hwpx.mdc` 트리거 룰을 둔다. 스킬과 룰을 함께 두면 자연어 요청과 `**/*.hwpx` 확장자 둘 다로 트리거된다.

```md
---
description: HWPX/한글 문서 작업 시 hwpx-plugins을 사용
globs:
  - "**/*.hwpx"
alwaysApply: false
---
한글 문서(.hwpx), 가정통신문, 공문, 한글 양식, OWPML, 플레이스홀더 치환, 문서 자동화 요청이면 `.cursor/skills/hwpx-plugins/`의 `SKILL.md`를 먼저 읽고 그 워크플로를 따른다.
```

### OpenClaw · Hermes

각 호스트 번들과 MCP 배선 안내가 함께 들어 있다.

| Host | Bundle | Install entry point |
| :--- | :--- | :--- |
| OpenClaw | `plugins/openclaw/hwpx-plugin` | `openclaw.plugin.json` + `INSTALL-mcp.md` |
| Hermes Agent | `plugins/hermes/hwpx` | `hermes skills publish` + `INSTALL-mcp.md` |

> 이 레포는 HWPX 스킬의 canonical 소스로, 호스트별 번들(Claude Code / Codex / OpenClaw / Hermes)을 한 소스에서 빌드한다. canonical `SKILL.md`, `references/`, `examples/`, `scripts/`를 편집한 뒤 `python3 scripts/build_hwpx_plugins.py`로 재빌드하고 `python3 scripts/validate_hwpx_plugin.py`로 검증한다. MCP 런처는 로컬 sibling checkout(`../hwpx-mcp-server`, `../python-hwpx`)을 우선하고, 없으면 첫 MCP 시작 시 `hwpx-mcp-server==2.20.0`을 플러그인 로컬 venv에 설치한다.

## 직접 실행하기 (수동 검증·고급 사용)

> 평소엔 칠 필요 없다. 에이전트가 내부에서 같은 스크립트·MCP 도구를 호출한다. 결과를 손으로 확인하거나 CI에서 돌릴 때만 참고한다. 전체 예제는 [`examples/`](examples/) 참고.

```bash
# 텍스트 추출
python3 scripts/text_extract.py input.hwpx --format json --include-nested --out output.json

# 플레이스홀더 전역 치환 (표 셀 포함)
python3 scripts/zip_replace_all.py template.hwpx output.hwpx \
  --replace "{학교명}=테스트초" "{담당자}=홍길동" --auto-fix-ns

# 최소 성공 경로: 생성 → 추출
python3 examples/01_create_and_save.py
python3 scripts/text_extract.py examples/out/01_created.hwpx
```

`zip_replace_all.py`와 `fix_namespaces.py`는 임시 HWPX가 `validate_editor_open_safety()`를 통과한 경우에만 대상 파일을 교체한다. 검증 실패 시 기존 output은 보존된다.

builder / document-plan / operating-plan / form-fit 경로는 각각 `examples/10_create_with_builder.py`, `06_create_from_document_plan.py`, `07_create_operating_plan.py`, `08_template_formfit.py`로 확인하며, 대응하는 `quickcheck.py --builder/--document-plan/--operating-plan/--template-formfit` 플래그로 게이트를 검증한다. 자세한 절차와 evidence 계약은 [references/](references/)에 있다.

## 운영 메모

- `save()` 대신 `save_to_path()`를 사용한다.
- 새 문서 조립에는 `hwpx.builder`를 우선하고, 저장 직후 `BuilderSaveReport`의 hard gates(`package_validation`·`document_errors`·`reopen`)와 `visual_review_required`를 확인한다.
- `replace_text_in_runs()`는 표 셀까지 항상 보장하지 않으므로, 양식 전체 치환은 `zip_replace_all.py`(또는 form-fit)를 우선한다.
- `visual_review_required=true`는 package/schema/text 검사는 통과했지만 열린 문서의 페이지 나눔·표 맞춤·잘림은 아직 확인 안 됐다는 뜻이다. 최종 제출을 말하려면 HWPX viewer에서 열어본 뒤 `scripts/visual_review.py`로 `--screenshot`이 포함된 `observed_pass` evidence를 남긴다. viewer가 없는 CI/컨테이너에서는 `--viewer none --status blocked` fallback을 남기고 handoff한다.
- 예제/문서에는 이름·전화번호·이메일·주소 등 PII를 redaction 없이 넣지 않는다.

## 더 보기

- [SKILL.md](SKILL.md) — 에이전트용 의사결정 트리와 실전 워크플로
- [references/](references/) — API 레퍼런스([api.md](references/api.md))·테마별 워크플로·공문서 규칙·evidence 계약
- [examples/](examples/) — 생성·추출·치환·form-fit·document-plan·mail-merge 예제
- [CHANGELOG.md](CHANGELOG.md) — 버전 변경 이력

## 설치 후 문제를 만나면

`python3 -m pip install -U python-hwpx lxml`를 다시 실행하고 `python3 scripts/quickcheck.py`가 통과하는지, 결과 파일이 `examples/out/` 아래 생기는지, 입력이 실제 `.hwpx` ZIP 패키지인지 확인한다. 재현되면 `quickcheck.py` 출력과 함께 이슈를 남긴다.

## 작성자

**고규현** (airmang) — GitHub [@airmang](https://github.com/airmang) · Base Library [python-hwpx](https://github.com/airmang/python-hwpx)

## 감사의 말

[python-hwpx](https://github.com/airmang/python-hwpx) · [hwpx-mcp-server](https://github.com/airmang/hwpx-mcp-server) 위에서 동작하며, 아래 공개 표준·프로젝트에 빚지고 있습니다.

- **[OWPML — 개방형 워드프로세서 마크업 언어 (KS X 6101)](https://www.kssn.net/search/stddetail.do?itemNo=K001010119985)** — HWPX가 기반하는 한국 산업 표준
- **[hancom-io/hwpx-owpml-model](https://github.com/hancom-io/hwpx-owpml-model)** — OWPML 요소 구조 참조 모델 · **[neolord0/hwpxlib](https://github.com/neolord0/hwpxlib)** — 오라클 샘플 코퍼스
- **[edwardkim/rhwp](https://github.com/edwardkim/rhwp)** — 멱등성·검증 게이트 설계 영감

## License

Apache License 2.0. See LICENSE and NOTICE.
