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
- 최소 호환 기준: `python-hwpx >= 2.6`
- 최근 로컬 검증 기준: `python-hwpx 2.9.0`

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

## 가장 많이 쓰는 작업 3개

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

## 포함 내용

- `SKILL.md`: 에이전트용 의사결정 트리와 실전 워크플로
- `references/api.md`: `python-hwpx` API 레퍼런스
- `scripts/quickcheck.py`: 설치 직후 첫 성공 경로를 점검하는 CLI
- `scripts/text_extract.py`: 텍스트 추출 CLI
- `scripts/zip_replace_all.py`: 플레이스홀더 전역 치환 CLI
- `scripts/fix_namespaces.py`: ZIP-level 수정 후 namespace 정리
- `examples/`: 생성, 추출, 템플릿 치환 예제

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

## License
Apache License 2.0. See LICENSE and NOTICE.
