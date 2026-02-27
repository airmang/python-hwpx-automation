<p align="center">
  <h1 align="center">📄 hwpx-skill</h1>
  <p align="center">
    <strong>한글(HWPX) 문서를 AI가 안전하게 읽고·편집하고·치환하는 프로덕션용 Skill</strong>
  </p>
  <p align="center">
    한글 워드프로세서 없이 · 순수 파이썬 · 크로스 플랫폼
  </p>
  <p align="center">
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/v/python-hwpx?style=flat-square&color=blue" alt="PyPI"></a>
    <a href="https://pypi.org/project/python-hwpx/"><img src="https://img.shields.io/pypi/pyversions/python-hwpx?style=flat-square" alt="Python"></a>
    <a href="https://github.com/airmang/hwpx-skill"><img src="https://img.shields.io/badge/repo-airmang%2Fhwpx--skill-181717?style=flat-square" alt="Repo"></a>
    <a href="https://smithery.ai/"><img src="https://img.shields.io/badge/registry-Smithery-6f42c1?style=flat-square" alt="Smithery"></a>
  </p>
</p>

---

**hwpx-skill**은 `python-hwpx` 기반의 Agent Skill로, `.hwpx` 문서를 실무에서 안전하게 처리하도록 설계되었습니다.  
단순 편집부터 대량 치환(표 포함), 네임스페이스 정리까지 한 번에 다룹니다.

> **Note** — 대상 포맷은 Open XML 기반 `.hwpx`입니다. 레거시 바이너리 `.hwp`는 직접 편집 대상이 아닙니다.

<br>

## Why hwpx-skill?

- ✅ **실측 API 기반**: `TextExtractor.extract_text()`, `iter_document_paragraphs()+p.text()`
- ✅ **안전한 저장 전략**: `save_to_path()` 중심 (deprecated 경로 명시)
- ✅ **표 포함 전역 치환 대응**: ZIP-level replace + `scripts/fix_namespaces.py`
- ✅ **실파일 검증 완료**: 실제 학교 양식 HWPX로 테스트 PASS

<br>

## Core Features

- 텍스트 추출: `TextExtractor.extract_text()`
- 문단 순회: `iter_document_paragraphs()` + `p.text()`
- 문서 편집: `HwpxDocument.open()`, `add_paragraph()`, `save_to_path()`
- 구조 탐색: `ObjectFinder.find_all(tag="...")`
- 대량 치환: ZIP-level XML replace
- 후처리: `scripts/fix_namespaces.py`

<br>

## Verified Real-file Tests

- 텍스트 추출 / 구조 스캔 / 문단 추가 저장: PASS
- 실토큰 치환 + 네임스페이스 정리: PASS
- 테스트 리포트: `mcp_files/hwpx_test_results_20260227/TEST_REPORT_REAL.md`

<br>

## Project Structure

```text
hwpx-skill/
├── SKILL.md
├── references/
│   └── api.md
└── scripts/
    └── fix_namespaces.py
```

<br>

## Quick Start

### 의존성

```bash
python3 -m pip install -U python-hwpx lxml
```

### 사용 원칙

- 일반 편집: `HwpxDocument`
- 표 포함 전역 치환: ZIP-level replace → `fix_namespaces.py`

<br>

## Compatibility Notes

- `save()`는 deprecated wrapper이므로 `save_to_path()` 권장
- `replace_text_in_runs()`는 표 셀 치환이 비보장일 수 있음
- 헤더/푸터 API는 버전 이슈가 있을 수 있어 실패 시 ZIP-level 전략 권장

<br>

## Author

**고규현** (airmang)  
- GitHub: <https://github.com/airmang>
- Base Library: <https://github.com/airmang/python-hwpx>
