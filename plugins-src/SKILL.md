---
name: hwpx
description: "한글 문서(.hwpx/OWPML) 편집·추출·자동화 스킬. '한글 문서 편집해줘', 가정통신문·공문·한글 양식 작성, HWPX 편집, 한글 파일/OWPML 분석, 플레이스홀더 치환, 문서 자동화 요청이면 이 스킬을 반드시 사용하세요."
---

# hwpx (HWPX / OWPML)

`.hwpx`는 ZIP 기반 OWPML 문서다. 기본 생성·편집은 `python-hwpx`로 처리하고, 표를 포함한 전역 치환이나 ZIP 레벨 후처리는 번들 스크립트로 처리한다.

- 기준 라이브러리: `python-hwpx` (import: `hwpx`)
- 최소 호환 기준: `python-hwpx >= 2.6`
- 최근 로컬 검증 버전: `python-hwpx 2.9.0`
- 상세 시그니처와 옵션은 [`references/api.md`](references/api.md)에서 확인한다.

## 시작

```bash
pip install -U python-hwpx lxml
```

## 5분 검증

설치 직후에는 아래 순서로 최소 성공 경로를 먼저 확인한다.

```bash
python3 examples/01_create_and_save.py
python3 examples/02_extract_and_inspect.py examples/out/01_created.hwpx
python3 scripts/text_extract.py examples/out/01_created.hwpx
```

치환 흐름까지 확인하려면:

```bash
python3 examples/03_template_replace.py examples/out/01_created.hwpx examples/out/03_replaced.hwpx --replace "학부모님께 안내드립니다.=학부모님께 수정 안내드립니다."
python3 examples/02_extract_and_inspect.py examples/out/03_replaced.hwpx
```

## 빠른 의사결정

1. **텍스트만 추출한다**  
   `python3 scripts/text_extract.py input.hwpx`  
   표 안 문단까지 포함하려면 `--include-nested`, 구조화된 결과가 필요하면 `--format json`을 사용한다.

2. **새 문서를 만들거나 본문을 간단히 편집한다**  
   `HwpxDocument`를 사용한다. 문단 추가, 표 생성, 메모 삽입, 내보내기는 [`references/api.md`](references/api.md)와 [`examples/01_create_and_save.py`](examples/01_create_and_save.py)를 본다.

3. **문서 구조를 조사한다**  
   텍스트 노드, 표 개수, 특정 OWPML 태그 분포를 확인할 때는 `ObjectFinder`를 사용한다. 예시는 [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)를 본다.

4. **플레이스홀더를 일괄 치환한다**  
   표 셀까지 포함한 전역 치환이면 `python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{기관명}=OO구청" "{담당자}=홍길동"`을 사용한다. 치환 직후 네임스페이스 정리까지 하려면 `--auto-fix-ns`를 붙인다.

5. **ZIP-level 수정 후 네임스페이스만 다시 정리한다**  
   `python3 scripts/fix_namespaces.py input.hwpx --inplace --backup`

## 작업 패턴

### 1) 가정통신문·공문·한글 양식 작성

- 새 파일이면 `HwpxDocument.new()`로 시작한다.
- 기존 양식을 채우는 작업이면 템플릿을 열고 문단과 표를 수정한다.
- 표 셀 입력은 `doc.add_table(...)`의 반환값에서 `set_cell_text(...)`를 호출한다.
- 저장은 `save_to_path(path)`를 사용한다. `save()`는 deprecated wrapper다.

관련 예제:
- [`examples/01_create_and_save.py`](examples/01_create_and_save.py)
- [`references/api.md`](references/api.md)

### 2) 문서 텍스트 추출·검수·분석

- 텍스트만 필요하면 `scripts/text_extract.py`를 우선 사용한다.
- 하위 구조까지 포함한 문단 목록이 필요하면 `--format json --include-nested`를 사용한다.
- 표 개수, 특정 태그, 플레이스홀더 흔적을 조사할 때는 `ObjectFinder.find_all()`을 사용한다.

관련 예제:
- [`scripts/text_extract.py`](scripts/text_extract.py)
- [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)

### 3) 플레이스홀더 치환 전략

- **본문 런(run) 수준 치환만 필요하다**  
  `replace_text_in_runs()`를 사용한다. 색상·밑줄 같은 스타일 필터도 줄 수 있다.

- **표 셀까지 포함한 전역 치환이 필요하다**  
  `scripts/zip_replace_all.py`를 사용한다. 이 스크립트는 `mimetype` 엔트리를 `ZIP_STORED`로 유지하고, 입력/출력 경로가 같으면 임시 파일로 안전하게 처리한다.

- **치환 키에 XML 조각이 들어 있다**  
  `<`, `>`, `</`가 포함된 치환 키는 문서를 깨뜨릴 수 있다. 태그가 아닌 텍스트 플레이스홀더로 바꾼 뒤 치환한다.

관련 예제:
- [`scripts/zip_replace_all.py`](scripts/zip_replace_all.py)
- [`examples/03_template_replace.py`](examples/03_template_replace.py)

### 4) 불안정한 영역

- `set_header_text()`와 `set_footer_text()`는 문서/버전 조합에 따라 레이아웃이 흔들릴 수 있다.
- 자동화 파이프라인에서는 결과 파일을 다시 열어 반드시 검수한다.
- 헤더/푸터가 문제를 일으키면 템플릿에서 고정하고, 본문·표·메모만 자동화한다.

## 번들 리소스

- [`references/api.md`](references/api.md)  
  `HwpxDocument`, `TextExtractor`, `ObjectFinder`, `HwpxPackage`의 시그니처와 주의사항만 모아둔 API 레퍼런스.

- [`scripts/text_extract.py`](scripts/text_extract.py)  
  원커맨드 텍스트 추출 CLI. 에이전트가 가장 먼저 시도하기 좋은 안전한 읽기 경로.

- [`scripts/zip_replace_all.py`](scripts/zip_replace_all.py)  
  표 포함 전역 치환용 CLI 겸 import 가능한 함수 모듈.

- [`scripts/fix_namespaces.py`](scripts/fix_namespaces.py)  
  ZIP-level 수정 후 XML 네임스페이스 선언을 다시 정리하는 후처리 스크립트.

- [`examples/01_create_and_save.py`](examples/01_create_and_save.py)  
  새 문서 생성, 문단/표 추가, 저장 예제.

- [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)  
  텍스트 추출과 구조 조사 예제.

- [`examples/03_template_replace.py`](examples/03_template_replace.py)  
  템플릿 치환부터 namespace 정리까지의 전체 파이프라인 예제.

## 실행 전 체크리스트

- `python-hwpx`와 `lxml`이 설치되어 있는지 확인한다.
- 결과 파일을 덮어쓸 때는 `--backup`을 사용한다.
- 자동화 결과물은 가능한 한 한 번 다시 열어본다.
- API 세부 옵션이나 최신 시그니처가 필요하면 항상 [`references/api.md`](references/api.md)를 먼저 읽는다.

## 제안서/기획안 생성 workflow

사용자가 “제안서”, “기획안”, “계획서” 형태의 새 HWPX 생성을 요청하면 저수준 XML 조작보다 `python-hwpx`의 proposal preset을 먼저 사용한다.

1. 자연어 요청을 `ProposalSpec` JSON으로 정규화한다.
2. `from hwpx.presets import create_proposal_document, inspect_proposal_quality`를 사용한다.
3. 생성 직후 `inspect_proposal_quality()`로 구조, 표, payload, validation, rubric 점수, `sample_match`를 확인한다.
4. 평균 점수 4.0 미만, `sample_match.pass == false`, 특정 sample-match dimension 실패, 필수 섹션 누락이면 `ProposalSpec`을 보강해 다시 생성한다.
5. 샘플에서 배운 anti-pattern: 큰 BMP 이미지에 의존하는 문서, 표/메타데이터가 이미지처럼 박힌 문서, 연락처/이메일/주소 등 PII가 redaction 없이 예제에 노출되는 문서는 피한다.
6. `visual_review_required=True`는 렌더러/픽셀 diff 없이 sample-derived proxy metric만 통과했다는 제한으로 해석한다.

예제: `examples/04_create_proposal.py`
검증: `python3 scripts/quickcheck.py --proposal`
