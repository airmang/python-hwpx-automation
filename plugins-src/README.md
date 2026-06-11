<p align="center">
  <h1 align="center">📄 hwpx-plugins</h1>
  <p align="center">
    <strong>AI 에이전트가 HWPX 문서를 바로 읽고, 바꾸고, 점검하게 만드는 공식 온보딩 스킬</strong>
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

`hwpx-plugins`은 `python-hwpx` 기반의 공식 에이전트 스킬이다. HWPX를 잘 모르는 사용자도 **스킬 설치 후 바로 문서 읽기, 텍스트 추출, 템플릿 치환, builder 기반 새 문서 조립, repair/recover, 기본 점검**까지 갈 수 있게 만드는 데 초점을 둔다. `.hwpx` 문서를 열고, 텍스트를 추출하고, 표를 포함한 양식을 채우고, 플레이스홀더를 치환하고, 머리글/쪽번호/병합 표가 있는 새 문서를 조립하고, 깨진 ZIP 패키지를 복구하는 작업을 에이전트가 바로 수행할 수 있게 설계했다.

즉, 이 저장소는 단순 설명서가 아니다.
- 에이전트가 따라갈 `SKILL.md`
- 바로 실행해볼 수 있는 예제
- 입문자가 첫 성공을 확인하는 보조 CLI
를 함께 제공하는 **HWPX 자동화 입구**다.

> 대상 포맷은 Open XML 기반 `.hwpx`다. 레거시 바이너리 `.hwp` 직접 편집은 범위 밖이다.

## 지원 에이전트 생태계

- **Claude Code Skills** — `.claude/skills/hwpx-plugins/`에 넣어 바로 트리거할 수 있다.
- **Cursor Skills / Rules** — `.cursor/skills/`와 `.cursor/rules/` 조합으로 온보딩할 수 있다.
- **Codex CLI Skills** — `.agents/skills/hwpx-plugins/` 경로 기준으로 바로 붙일 수 있다.

## 이 저장소가 바로 해결하는 일

- HWPX 문서 텍스트를 빠르게 추출한다.
- 한컴에서 열리지 않는 HWPX를 `hwpx-repair`/MCP `repair_hwpx`로 복구 복사본에 재패킹한다.
- `hwpx.builder`로 머리글/바닥글, 쪽번호, 리치 런, 목록, 병합/음영/열너비 표, 이미지, 페이지 나눔이 있는 새 HWPX를 조립한다.
- 표를 포함한 문서의 플레이스홀더를 일괄 치환한다.
- 설치 직후 환경이 맞는지 한 번에 확인한다.
- 에이전트가 HWPX 작업에서 어떤 흐름을 따라야 하는지 알려준다.

## 이렇게 쓰세요 — 에이전트에게 말 걸기

설치하고 나면 사용자가 직접 파이썬 스크립트를 칠 일은 거의 없다. Claude Code·Cursor·Codex 같은 에이전트에게 **자연어로 말하면** 스킬이 트리거되고, 에이전트가 `SKILL.md`의 의사결정 트리를 따라 알맞은 스크립트나 MCP 도구를 알아서 호출한다.

| 이렇게 말하면 | 에이전트가 하는 일 |
|---|---|
| "이 hwpx 텍스트 전부 뽑아줘" | 문서 텍스트 추출 (표 안 문단 포함) |
| "`{학교명}`·`{담당자}` 자리표시자 전부 바꿔줘" | 표까지 포함한 플레이스홀더 전역 치환 |
| "머리글·쪽번호 들어간 운영 계획서 새로 만들어줘" | `hwpx.builder`로 레이아웃 민감 문서 조립 |
| "이 양식은 그대로 두고 내용만 채워줘" | 승인된 양식 보존 form-fit |
| "한컴에서 안 열리는 hwpx인데 복구해줘" | repair/recover 복구 복사본 생성 |
| "이 hwpx 구조랑 표 개수 점검해줘" | 구조·품질 점검 |

예를 들면 이런 식이다.

> **사용자:** 첨부한 가정통신문 양식에서 학교명이랑 날짜만 우리 학교 걸로 바꿔서 새 파일로 줘.
>
> **에이전트:** 원본을 보존한 채 form-fit으로 플레이스홀더를 채우고, 패키지·스키마 검증을 거친 새 파일을 돌려준다.

에이전트는 요청 성격에 따라 builder / document-plan / form-fit / repair 중 무엇을 쓸지 스스로 판단한다. 머리글·쪽번호·표처럼 레이아웃에 민감한 작업에서는 `visual_review_required`가 켜지므로, 에이전트는 최종 제출 전 열린 문서 시각 검토 evidence까지 같이 남긴다.

> 명령줄에서 직접 같은 작업을 돌리거나 결과를 손으로 검증하고 싶으면 아래 [직접 실행하기](#직접-실행하기-수동-검증고급-사용)를 본다.

## 3분 설치

기본 명령:

```bash
python3 -m pip install -U python-hwpx lxml
```

현재 권장 기준:
- Python 3.10+
- 기본 편집 최소 호환 기준: `python-hwpx >= 2.11.0`
- document-plan 생성 권장 기준: `python-hwpx >= 2.11.0`
- builder 생성 권장 기준: `python-hwpx >= 2.11.0` (builder core 포함)
- repair/recover 권장 기준: `python-hwpx >= 2.11.0`
- 최근 로컬 검증 기준: `python-hwpx 2.11.0 + editor-open safety guard`

0.1.7 번들의 MCP 서버(`hwpx-mcp-server==2.4.0`)가 노출하는 주요 표면:
- **신뢰 루프**: `apply_edits`(원자 적용·dry_run·revision 가드·멱등키), `undo_last_edit`, `render_preview`(페이지 PNG 자기검증)
- **서식 편집**: `set_paragraph_format`·`set_page_setup`·`set_header_footer`·`set_page_number`·`set_list_format` (인간 단위)
- **양식**: 누름틀 1급(`list_form_fields`/`fill_form_field`) + 매칭 신뢰도 등급
- **공문서**: `inspect_official_document_style` lint·결재란 프리셋·장르 레시피, 신구대조표(`doc_diff`/`create_comparison_table_document`)
- **생산성**: `mail_merge` 대량 생산·`table_compute`, 서식 이식(`extract_style_profile`)·템플릿 레지스트리, 고급 생성기(사진대지·명패·조직도)

워크플로 사용법은 [SKILL.md](SKILL.md)와 [references/api.md](references/api.md)를 본다.

## 5분 성공 확인

설치 후 이 명령 하나부터 돌린다.

```bash
python3 scripts/quickcheck.py
```

이 스크립트는 다음을 한 번에 확인한다.
- Python 버전
- `python-hwpx`, `lxml` import
- 예제 문서 생성
- 생성 문서 구조 점검
- CLI 텍스트 추출

정상이라면 마지막에 아래 문구가 나온다.

```text
[OK] basic hwpx skill workflow passed
```

선언형 document-plan 생성까지 확인하려면:

```bash
python3 scripts/quickcheck.py --document-plan
```

조립형 builder 생성까지 확인하려면:

```bash
python3 scripts/quickcheck.py --builder
```

운영 계획서 품질 프로필까지 확인하려면:

```bash
python3 scripts/quickcheck.py --operating-plan
python3 scripts/quickcheck.py --visual-review
python3 scripts/quickcheck.py --visual-review --operating-plan
```

양식 보존 form-fit 경로까지 확인하려면:

```bash
python3 scripts/quickcheck.py --template-formfit
```

## Multi-host plugin bundles

This repository is the canonical source for the HWPX skill and builds one bundle per agent host:

| Host | Bundle | Install entry point |
| :--- | :--- | :--- |
| Claude Code | `plugins/claude/hwpx-plugin` | `.claude-plugin/marketplace.json` (repo root) |
| Codex | `plugins/codex/hwpx-plugin` | `.agents/plugins/marketplace.json` (repo root) |
| OpenClaw | `plugins/openclaw/hwpx-plugin` | `openclaw.plugin.json` + `INSTALL-mcp.md` |
| Hermes Agent | `plugins/hermes/hwpx` | `hermes skills publish` + `INSTALL-mcp.md` |

Edit the canonical `SKILL.md`, `references/`, `examples/`, and `scripts/` at the repo root,
then rebuild and validate:

```bash
python3 scripts/build_hwpx_plugins.py
python3 scripts/validate_hwpx_plugin.py
git diff --exit-code -- plugins .claude-plugin .agents   # build must be reproducible and committed
uv run --with lxml --with-editable ../python-hwpx python scripts/quickcheck.py --builder --document-plan --operating-plan --template-formfit --visual-review
```

Host differences (frontmatter, manifests, MCP wiring, skill paths) are declared in
`packaging/hosts.json` with templates in `packaging/templates/`. The MCP launcher prefers local
sibling checkouts (`../hwpx-mcp-server`, `../python-hwpx`), honors `HWPX_MCP_SERVER_REPO` /
`PYTHON_HWPX_REPO`, and otherwise installs `hwpx-mcp-server==2.4.0` into a plugin-local venv
on first MCP start before running it.

Claude Code installs via `claude plugin marketplace add airmang/hwpx-plugins` then
`claude plugin install hwpx-plugin@hwpx`. Codex installs via
`codex plugin marketplace add airmang/hwpx-plugins` then `codex plugin add hwpx-plugin@hwpx`.
Start a fresh agent session after installing so new skills and MCP tools load.

## Claude Code 설치

프로젝트 로컬 설치:

```text
.claude/skills/hwpx-plugins/
```

글로벌 설치:

```text
~/.claude/skills/hwpx-plugins/
```

설치 절차:

1. 이 레포를 `hwpx-plugins` 폴더째 위 경로 중 하나에 복사한다.
2. 아래 명령으로 의존성을 설치한다.

```bash
python3 -m pip install -U python-hwpx lxml
```

3. 아래 명령으로 첫 성공 경로를 확인한다.

```bash
python3 scripts/quickcheck.py
```

에이전트가 `한글 문서 편집`, `가정통신문 작성`, `공문 양식 채우기`, `HWPX 플레이스홀더 치환` 같은 요청을 받으면 스킬이 트리거되도록 `SKILL.md` description을 유지한다.

## Cursor 설치

프로젝트 로컬 설치:

```text
.cursor/skills/hwpx-plugins/
```

글로벌 설치:

```text
~/.cursor/skills/hwpx-plugins/
```

의존성 설치:

```bash
python3 -m pip install -U python-hwpx lxml
```

권장 트리거 룰 파일:

```text
.cursor/rules/hwpx.mdc
```

예시 내용:

```md
---
description: HWPX/한글 문서 작업 시 hwpx-plugins을 사용
globs:
  - "**/*.hwpx"
alwaysApply: false
---

한글 문서(.hwpx), 가정통신문, 공문, 한글 양식, OWPML, 플레이스홀더 치환, 문서 자동화 요청이면 `.cursor/skills/hwpx-plugins/`의 `SKILL.md`를 먼저 읽고 그 워크플로를 따른다.
```

Cursor에서 스킬과 룰을 함께 두면 자연어 요청과 파일 확장자 기준 둘 다 트리거를 걸기 쉽다.

## Codex CLI 설치

Git marketplace 설치:

```bash
codex plugin marketplace add airmang/hwpx-plugins
codex plugin add hwpx-plugin@hwpx
```

의존성 설치:

```bash
python3 -m pip install -U python-hwpx lxml
```

설치 또는 재설치 후에는 새 Codex 세션을 시작해야 새 skill과 MCP 도구가 로드된다.

## 포함 내용

- `SKILL.md`: 에이전트용 의사결정 트리와 실전 워크플로
- `references/api.md`: `python-hwpx` API 레퍼런스
- `scripts/quickcheck.py`: 설치 직후 첫 성공 경로를 점검하는 CLI
- `scripts/text_extract.py`: 텍스트 추출 CLI
- `scripts/zip_replace_all.py`: 플레이스홀더 전역 치환 CLI
- `scripts/fix_namespaces.py`: ZIP-level 수정 후 namespace 정리
- `scripts/visual_review.py`: 열린 문서 시각 검토 evidence 기록 CLI
- `examples/`: 생성, 추출, 템플릿 치환 예제
  - `examples/06_create_from_document_plan.py`: `hwpx.document_plan.v1` 생성 예제
  - `examples/06_mcp_document_plan.md`: MCP document-plan 호출 예시
  - `examples/07_create_operating_plan.py`: 운영 계획서 document-plan + 품질 프로필 예제
  - `examples/07_mcp_operating_plan.md`: MCP 운영 계획서 생성/검증 호출 예시
  - `examples/08_template_formfit.py`: template form-fit local quickcheck 예제
  - `examples/08_mcp_template_formfit.md`: MCP 양식 보존 workflow 예시
  - `examples/09_visual_review_loop.md`: ComputerUse/사람 viewer 시각 검토 반복 workflow
  - `examples/10_create_with_builder.py`: builder 기반 레이아웃 민감 수직 슬라이스 예제

## 프로젝트 구조

```text
hwpx-plugins/
├── SKILL.md
├── README.md
├── references/
│   └── api.md
├── scripts/
│   ├── fix_namespaces.py
│   ├── quickcheck.py
│   ├── text_extract.py
│   ├── visual_review.py
│   └── zip_replace_all.py
└── examples/
    ├── 01_create_and_save.py
    ├── 02_extract_and_inspect.py
    └── 03_template_replace.py
```

## 직접 실행하기 (수동 검증·고급 사용)

> 아래 명령은 평소에 직접 칠 필요가 없다. 에이전트가 내부에서 같은 스크립트·MCP 도구를 호출한다. 결과를 손으로 확인하거나 CI에서 돌리거나, 에이전트 없이 라이브러리만 쓰고 싶을 때 참고한다.

### 문서 텍스트 추출

```bash
python3 scripts/text_extract.py input.hwpx
python3 scripts/text_extract.py input.hwpx --format json --include-nested --out output.json
```

### 플레이스홀더 전역 치환

```bash
python3 scripts/zip_replace_all.py template.hwpx output.hwpx --replace "{학교명}=테스트초" "{담당자}=홍길동" --auto-fix-ns
```

`zip_replace_all.py`는 임시 HWPX를 만든 뒤 `validate_editor_open_safety()`를 통과한 경우에만 output을 교체한다. 검증 실패 시 기존 output은 보존된다.

namespace 정리만 수행:

```bash
python3 scripts/fix_namespaces.py output.hwpx --inplace --backup
```

`fix_namespaces.py`도 같은 open-safety 검증을 통과해야 대상 파일을 교체한다.

### 예제로 최소 성공 경로 확인

```bash
python3 examples/01_create_and_save.py
python3 examples/02_extract_and_inspect.py examples/out/01_created.hwpx
python3 scripts/text_extract.py examples/out/01_created.hwpx
```

플레이스홀더 치환까지 확인하려면:

```bash
python3 examples/03_template_replace.py examples/out/01_created.hwpx examples/out/03_replaced.hwpx --replace "학부모님께 안내드립니다.=학부모님께 수정 안내드립니다."
python3 examples/02_extract_and_inspect.py examples/out/03_replaced.hwpx
```

### 선언형 document-plan에서 새 HWPX 생성

```bash
python3 examples/06_create_from_document_plan.py
python3 scripts/quickcheck.py --document-plan
```

`validate_document_plan`이 실패하면 `issues[].code`, `issues[].path`,
`repairHints[]`를 보고 plan을 고친 뒤 다시 검증한다. `can_create=false`인
MCP 응답에서는 파일 생성을 진행하지 않는다.

### 조립형 builder로 새 HWPX 생성

```bash
python3 examples/10_create_with_builder.py
python3 scripts/quickcheck.py --builder
```

`hwpx.builder`는 `Document`, `Section`, `Heading`, `Paragraph`, `Run`,
`Bullet`, `NumberedList`, `Table`, `Image`, `Header`, `Footer`,
`PageNumber`, `PageBreak`, `Metadata`, `PageSize`, `Margins` 노드를 제공한다.
저장 후 `BuilderSaveReport.hard_gates`에서 `package_validation`,
`document_errors`, `reopen`이 `pass`인지 확인한다. 스키마 warning은
`schema_lint`로 가시화되며 hard error가 아니면 `document_errors`는 pass다.
머리글, 쪽번호, 표, 이미지, 페이지 나눔처럼 layout-sensitive 기능을 쓰면
`visual_review_required=true`가 되므로 최종 제출 전 열린 문서 검토 evidence가 필요하다.

### 운영 계획서 제출 후보 생성

```bash
python3 examples/07_create_operating_plan.py
python3 scripts/quickcheck.py --operating-plan
```

운영 계획서는 `hwpx.document_plan.v1`로 먼저 구조화하고
`quality_profile="operating_plan"`을 켠다. MCP 서버가 있으면
`validate_document_plan` → `analyze_document_plan` → `create_document_from_plan`
→ `inspect_document_authoring_quality` 순서로 진행한다. MCP가 없으면 local
`python-hwpx`의 `inspect_operating_plan_quality()`로 같은 품질 프로필을 확인한다.
생성 또는 form-fit 이후에는 MCP `inspect_operating_plan_quality(filename)` 또는
local `inspect_operating_plan_quality(path)`로 파일만 다시 열어 evidence를 남긴다.
핵심 evidence는 `report_version`, `status`, `score`, `gaps`, `repair_hints`,
`visual_review_required`다. `status="ready"`여도 `visual_review_required=true`이면
최종 제출 전 별도 시각 검토가 필요하다.

`visual_review_required=true`는 파일만 여는 package/schema/text 검사는 통과했지만,
열린 문서의 페이지 나눔, 표 맞춤, 잘림 여부는 아직 확인하지 않았다는 뜻이다.
최종 제출 가능 상태라고 말하려면 ComputerUse 또는 사람이 HWPX viewer에서 문서를
열어본 뒤 `scripts/visual_review.py`로 `--screenshot`이 포함된 `observed_pass`
evidence를 남겨야 한다. `--observation`만으로는 최종 제출 가능 상태가 아니다.
viewer가 없는 CI/컨테이너에서는 `--viewer none --status blocked` fallback evidence를
남기고, 최종 시각 검토 대기 상태로 handoff한다.

### 승인된 양식을 보존하며 운영 계획서 채우기

```bash
python3 examples/08_template_formfit.py
python3 scripts/quickcheck.py --template-formfit
```

실제 P6 기준선이 있는 양식은 MCP에서 `analyze_template_formfit` →
`apply_template_formfit` 순서로 처리한다. 분석 단계는 파일을 쓰지 않고,
적용 단계는 원본과 다른 `destination_filename`에만 복사 후 반영한다.
`source.preserved`, package/schema validation, `residual_markers.blocking`,
`visual_review_required`를 handoff 근거로 확인한다.

## 예제

- `examples/01_create_and_save.py`: 새 문서 생성, 문단/표 추가, 저장
- `examples/02_extract_and_inspect.py`: 텍스트 추출, 문단 순회, 표 개수 확인
- `examples/03_template_replace.py`: 템플릿 치환, namespace 정리, 결과 저장
- `examples/09_visual_review_loop.md`: 열린 문서 시각 검토 evidence와 viewer-missing fallback

## 설치 후 문제를 만나면

먼저 아래를 확인한다.
- `python3 -m pip install -U python-hwpx lxml`를 다시 실행했는가
- `python3 scripts/quickcheck.py`가 통과하는가
- 결과 파일이 `examples/out/` 아래 생성되는가
- 입력 파일이 실제 `.hwpx` ZIP 패키지인가

문제가 재현되면 `quickcheck.py` 출력과 함께 이슈를 남기면 된다.

## 운영 메모

- `save()` 대신 `save_to_path()`를 사용한다.
- 새 문서 조립에는 `hwpx.builder`를 우선 고려하고, 저장 직후 `BuilderSaveReport`의 hard gates와 `visual_review_required`를 확인한다.
- `replace_text_in_runs()`는 표 셀까지 항상 보장하지 않으므로, 양식 문서 전체 치환은 `zip_replace_all.py`를 우선 고려한다.
- `set_header_text()`와 `set_footer_text()`는 문서별 호환 차이가 있을 수 있으니 자동화 파이프라인에서 결과 검수를 포함한다.

## 작성자

**고규현** (airmang)
- GitHub: <https://github.com/airmang>
- Base Library: <https://github.com/airmang/python-hwpx>

## 제안서/기획안 생성

에이전트에게 "이런 제안서/기획안 만들어줘"라고 하면, `python-hwpx`의 proposal preset이 설치된 환경에서 자연어 요청을 `ProposalSpec`으로 정리한 뒤 HWPX 제안서를 생성한다. 직접 돌리려면:

```bash
python3 examples/04_create_proposal.py
python3 scripts/quickcheck.py --proposal
```

권장 흐름:

1. 사용자 요청을 제목, 부제, 기관, 작성자, 핵심 요약, 섹션, 예산 항목, 기대 효과, 마무리 문구로 나눈다.
2. `create_proposal_document(proposal_spec)`로 HWPX를 생성한다.
3. `inspect_proposal_quality(output.hwpx)`로 필수 섹션, 표, validation, rubric 평균, `sample_match` 결과를 확인한다.
4. 평균 4.0 미만, `sample_match.pass == false`, 특정 dimension 실패, 필수 섹션 누락이면 `ProposalSpec`을 보강해 재생성한다.

샘플 기반 주의사항:

- 좋은 예시는 한국식 제안서/계획서의 메타데이터 표, 명확한 제목, 단계적 본문 흐름을 갖는다.
- 나쁜 예시는 과도한 BMP 이미지 payload와 agent가 재현하기 어려운 이미지 중심 구조를 포함한다.
- v2 리포트의 `visual_review_required=True`는 렌더러/픽셀 diff 없이 package/XML/text proxy만 확인했다는 뜻이다.
- 예제/문서에는 이름, 전화번호, 이메일, 주소 등 PII를 redaction 없이 넣지 않는다.

## License
Apache License 2.0. See LICENSE and NOTICE.
