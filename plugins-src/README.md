<p align="center">
  <h1 align="center">📄 hwpx-skill</h1>
  <p align="center">
    <strong>AI 에이전트가 HWPX 문서를 바로 읽고, 바꾸고, 점검하게 만드는 공식 온보딩 스킬</strong>
  </p>
  <p align="center">
    순수 Python · 한컴오피스 불필요 · 크로스 플랫폼
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/v/python-hwpx?style=flat-square&color=blue" alt="PyPI"></a>
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/pyversions/python-hwpx?style=flat-square" alt="Python"></a>
    <a href="https://github.com/airmang/hwpx-skill"><img src="https://img.shields.io/badge/repo-airmang%2Fhwpx--skill-181717?style=flat-square" alt="Repo"></a>
    <a href="https://github.com/airmang/hwpx-skill/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License"></a>
  </p>
</p>

---

## 🧩 HWPX Stack (3종)

| 계층 | 레포 | 역할 |
|---|---|---|
| 📦 라이브러리 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | 순수 파이썬 HWPX 파싱·편집·생성 코어 |
| 🔌 MCP 서버 | [`hwpx-mcp-server`](https://github.com/airmang/hwpx-mcp-server) | MCP 클라이언트(Claude Desktop, VS Code 등)에서 HWPX 조작 |
| 🎯 에이전트 스킬 | **[`hwpx-skill`](https://github.com/airmang/hwpx-skill)** | 에이전트가 HWPX를 바로 쓰게 해주는 공식 온보딩 스킬 |

---

`hwpx-skill`은 `python-hwpx` 기반의 공식 에이전트 스킬이다. HWPX를 잘 모르는 사용자도 **스킬 설치 후 바로 문서 읽기, 텍스트 추출, 템플릿 치환, 기본 점검**까지 갈 수 있게 만드는 데 초점을 둔다. `.hwpx` 문서를 열고, 텍스트를 추출하고, 표를 포함한 양식을 채우고, 플레이스홀더를 치환하는 작업을 에이전트가 바로 수행할 수 있게 설계했다.

즉, 이 저장소는 단순 설명서가 아니다.
- 에이전트가 따라갈 `SKILL.md`
- 바로 실행해볼 수 있는 예제
- 입문자가 첫 성공을 확인하는 보조 CLI
를 함께 제공하는 **HWPX 자동화 입구**다.

> 대상 포맷은 Open XML 기반 `.hwpx`다. 레거시 바이너리 `.hwp` 직접 편집은 범위 밖이다.

## 지원 에이전트 생태계

- **Claude Code Skills** — `.claude/skills/hwpx-skill/`에 넣어 바로 트리거할 수 있다.
- **Cursor Skills / Rules** — `.cursor/skills/`와 `.cursor/rules/` 조합으로 온보딩할 수 있다.
- **Codex CLI Skills** — `.agents/skills/hwpx-skill/` 경로 기준으로 바로 붙일 수 있다.

## 이 저장소가 바로 해결하는 일

- HWPX 문서 텍스트를 빠르게 추출한다.
- 표를 포함한 문서의 플레이스홀더를 일괄 치환한다.
- 설치 직후 환경이 맞는지 한 번에 확인한다.
- 에이전트가 HWPX 작업에서 어떤 흐름을 따라야 하는지 알려준다.

## 3분 설치

기본 명령:

```bash
python3 -m pip install -U python-hwpx lxml
```

현재 권장 기준:
- Python 3.10+
- 기본 편집 최소 호환 기준: `python-hwpx >= 2.6`
- document-plan 생성 권장 기준: `python-hwpx >= 2.9.1`
- 최근 로컬 검증 기준: `python-hwpx 2.9.1`

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

## Codex plugin bundle

This repository ships a local Codex plugin at `plugins/hwpx-plugin`.
The plugin exposes the same HWPX skill surface plus a companion MCP launcher.

Development smoke:

```bash
python3 scripts/sync_hwpx_plugin.py
python3 scripts/validate_hwpx_plugin.py
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

The plugin MCP launcher prefers sibling local checkouts:

- `../hwpx-mcp-server`
- `../python-hwpx`

Override them with `HWPX_MCP_SERVER_REPO` and `PYTHON_HWPX_REPO` when the checkout layout differs.
If local checkouts are unavailable, the launcher falls back to `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server`.

After changing plugin files, update the manifest cachebuster with:

```bash
python3 /Users/wilycastle/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py plugins/hwpx-plugin
python3 /Users/wilycastle/.codex/skills/.system/plugin-creator/scripts/read_marketplace_name.py
```

Then reinstall from the selected local marketplace. Start a new Codex thread before testing newly installed skills or MCP tools.

## 가장 많이 쓰는 작업

### 1) 문서 텍스트 바로 추출

```bash
python3 scripts/text_extract.py input.hwpx
python3 scripts/text_extract.py input.hwpx --format json --include-nested --out output.json
```

### 2) 플레이스홀더 전역 치환

```bash
python3 scripts/zip_replace_all.py template.hwpx output.hwpx --replace "{학교명}=테스트초" "{담당자}=홍길동" --auto-fix-ns
```

### 3) 예제 문서 생성 후 구조 확인

```bash
python3 examples/01_create_and_save.py
python3 examples/02_extract_and_inspect.py examples/out/01_created.hwpx
```

### 4) 선언형 document-plan에서 새 HWPX 생성

```bash
python3 examples/06_create_from_document_plan.py
python3 scripts/quickcheck.py --document-plan
```

`validate_document_plan`이 실패하면 `issues[].code`, `issues[].path`,
`repairHints[]`를 보고 plan을 고친 뒤 다시 검증한다. `can_create=false`인
MCP 응답에서는 파일 생성을 진행하지 않는다.

### 5) 운영 계획서 제출 후보 생성

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

### 6) 승인된 양식을 보존하며 운영 계획서 채우기

```bash
python3 examples/08_template_formfit.py
python3 scripts/quickcheck.py --template-formfit
```

실제 P6 기준선이 있는 양식은 MCP에서 `analyze_template_formfit` →
`apply_template_formfit` 순서로 처리한다. 분석 단계는 파일을 쓰지 않고,
적용 단계는 원본과 다른 `destination_filename`에만 복사 후 반영한다.
`source.preserved`, package/schema validation, `residual_markers.blocking`,
`visual_review_required`를 handoff 근거로 확인한다.

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

## 프로젝트 구조

```text
hwpx-skill/
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

## Claude Code 설치

프로젝트 로컬 설치:

```text
.claude/skills/hwpx-skill/
```

글로벌 설치:

```text
~/.claude/skills/hwpx-skill/
```

설치 절차:

1. 이 레포를 `hwpx-skill` 폴더째 위 경로 중 하나에 복사한다.
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
.cursor/skills/hwpx-skill/
```

글로벌 설치:

```text
~/.cursor/skills/hwpx-skill/
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
description: HWPX/한글 문서 작업 시 hwpx-skill을 사용
globs:
  - "**/*.hwpx"
alwaysApply: false
---

한글 문서(.hwpx), 가정통신문, 공문, 한글 양식, OWPML, 플레이스홀더 치환, 문서 자동화 요청이면 `.cursor/skills/hwpx-skill/`의 `SKILL.md`를 먼저 읽고 그 워크플로를 따른다.
```

Cursor에서 스킬과 룰을 함께 두면 자연어 요청과 파일 확장자 기준 둘 다 트리거를 걸기 쉽다.

## Codex CLI 설치

프로젝트 로컬 설치:

```text
.agents/skills/hwpx-skill/
```

글로벌 설치:

```text
~/.agents/skills/hwpx-skill/
```

의존성 설치:

```bash
python3 -m pip install -U python-hwpx lxml
```

Codex CLI에서는 `SKILL.md` frontmatter의 `description`이 핵심 트리거 역할을 한다. 따라서 자연어 요청과 도메인 키워드를 충분히 담은 상태로 유지하는 것이 중요하다.

## 빠른 검증

가장 빠른 검증은 `quickcheck.py`다.

```bash
python3 scripts/quickcheck.py
```

수동으로 최소 성공 경로를 밟으려면 아래 셋이면 충분하다.

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

## 빠른 사용 예시

텍스트 추출:

```bash
python3 scripts/text_extract.py input.hwpx
python3 scripts/text_extract.py input.hwpx --format json --include-nested --out output.json
```

플레이스홀더 전역 치환:

```bash
python3 scripts/zip_replace_all.py template.hwpx output.hwpx --replace "{학교명}=테스트초" "{담당자}=홍길동" --auto-fix-ns
```

namespace 정리만 수행:

```bash
python3 scripts/fix_namespaces.py output.hwpx --inplace --backup
```

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
- `replace_text_in_runs()`는 표 셀까지 항상 보장하지 않으므로, 양식 문서 전체 치환은 `zip_replace_all.py`를 우선 고려한다.
- `set_header_text()`와 `set_footer_text()`는 문서별 호환 차이가 있을 수 있으니 자동화 파이프라인에서 결과 검수를 포함한다.

## 작성자

**고규현** (airmang)  
- GitHub: <https://github.com/airmang>
- Base Library: <https://github.com/airmang/python-hwpx>

## 제안서/기획안 생성

`python-hwpx`의 proposal preset이 설치된 환경에서는 자연어 요청을 `ProposalSpec`으로 정리한 뒤 HWPX 제안서를 바로 생성할 수 있다.

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
