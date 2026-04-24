<p align="center">
  <h1 align="center">📄 hwpx-skill</h1>
  <p align="center">
    <strong>한글(HWPX) 문서를 AI 에이전트가 안전하게 읽고·편집하고·자동화하는 프로덕션용 스킬</strong>
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

`hwpx-skill`은 `python-hwpx` 기반의 에이전트 스킬이다. `.hwpx` 문서를 열고, 텍스트를 추출하고, 표를 포함한 양식을 채우고, 플레이스홀더를 치환하는 작업을 에이전트가 바로 수행할 수 있게 설계했다.

이 레포의 차별점은 단순한 커뮤니티 래퍼가 아니라는 점이다. `python-hwpx` 라이브러리 저자가 직접 관리하는 공식 스킬이므로, 라이브러리 실제 API와 예제가 함께 유지된다.

> 대상 포맷은 Open XML 기반 `.hwpx`다. 레거시 바이너리 `.hwp` 직접 편집은 범위 밖이다.

## 포함 내용

- `SKILL.md`: 에이전트용 의사결정 트리와 실전 워크플로
- `references/api.md`: `python-hwpx` API 레퍼런스
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
│   ├── text_extract.py
│   └── zip_replace_all.py
└── examples/
    ├── 01_create_and_save.py
    ├── 02_extract_and_inspect.py
    └── 03_template_replace.py
```

## 공통 의존성

모든 플랫폼에서 먼저 Python 의존성을 설치한다.

```bash
python -m pip install -U python-hwpx lxml
```

현재 권장 기준:
- 최소 호환 기준: `python-hwpx >= 2.6`
- 최근 로컬 검증 기준: `python-hwpx 2.9.0`

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
python -m pip install -U python-hwpx lxml
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
python -m pip install -U python-hwpx lxml
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
python -m pip install -U python-hwpx lxml
```

Codex CLI에서는 `SKILL.md` frontmatter의 `description`이 핵심 트리거 역할을 한다. 따라서 자연어 요청과 도메인 키워드를 충분히 담은 상태로 유지하는 것이 중요하다.

## 빠른 검증

설치 직후 최소 성공 경로는 이 셋이면 충분하다.

```bash
python examples/01_create_and_save.py
python examples/02_extract_and_inspect.py examples/out/01_created.hwpx
python scripts/text_extract.py examples/out/01_created.hwpx
```

플레이스홀더 치환까지 확인하려면:

```bash
python examples/03_template_replace.py examples/out/01_created.hwpx examples/out/03_replaced.hwpx --replace "학부모님께 안내드립니다.=학부모님께 수정 안내드립니다."
python examples/02_extract_and_inspect.py examples/out/03_replaced.hwpx
```

## 빠른 사용 예시

텍스트 추출:

```bash
python scripts/text_extract.py input.hwpx
python scripts/text_extract.py input.hwpx --format json --include-nested --out output.json
```

플레이스홀더 전역 치환:

```bash
python scripts/zip_replace_all.py template.hwpx output.hwpx --replace "{학교명}=테스트초" "{담당자}=홍길동" --auto-fix-ns
```

namespace 정리만 수행:

```bash
python scripts/fix_namespaces.py output.hwpx --inplace --backup
```

## 예제

- `examples/01_create_and_save.py`: 새 문서 생성, 문단/표 추가, 저장
- `examples/02_extract_and_inspect.py`: 텍스트 추출, 문단 순회, 표 개수 확인
- `examples/03_template_replace.py`: 템플릿 치환, namespace 정리, 결과 저장

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
