# python-hwpx API 레퍼런스

`hwpx-skill`에서 반복적으로 참조하는 `python-hwpx` API만 추렸다. 스킬 본문은 워크플로 중심이고, 이 문서는 시그니처와 사용 포인트를 빠르게 확인하는 용도다.

| python-hwpx 버전 | 상태 | 비고 |
|---|---|---|
| 2.5+ | ✅ 검증 완료 | 이 스킬의 기준 버전 |
| 2.0–2.4 | ⚠️ 대부분 호환 | 일부 API 시그니처 차이 가능 |
| 1.x | ❌ 비호환 | HwpxDocument API 미지원 |

- import 이름: `hwpx`
- 로컬 실측 버전: `python-hwpx 2.8`

## 목차

- 설치와 기본 import
- `HwpxDocument`
- `TextExtractor`
- `ObjectFinder`
- `HwpxPackage`
- 예외와 주의사항

## 설치와 기본 import

```bash
pip install -U python-hwpx lxml
```

```python
from hwpx import HwpxDocument, HwpxPackage, ObjectFinder, TextExtractor
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```

## HwpxDocument

### 열기, 생성, 저장

```python
from hwpx import HwpxDocument

doc = HwpxDocument.new()
doc.add_paragraph("자동 생성 문서")
doc.save_to_path("output.hwpx")

with HwpxDocument.open("input.hwpx") as doc:
    doc.add_paragraph("추가 문단")
    doc.save_to_path("edited.hwpx")
```

핵심 포인트:

- `HwpxDocument.open(source)`
- `HwpxDocument.new()`
- `save_to_path(path)`를 기본 저장 API로 사용한다.
- `save()`는 deprecated compatibility wrapper다.
- 바이트가 필요하면 `to_bytes()`를 사용한다.

### 문단과 표 추가

```python
from hwpx import HwpxDocument

doc = HwpxDocument.new()
doc.add_paragraph("2026학년도 가정통신문")

table = doc.add_table(2, 2)
table.set_cell_text(0, 0, "학년")
table.set_cell_text(0, 1, "1학년")
table.set_cell_text(1, 0, "담당")
table.set_cell_text(1, 1, "홍길동")

doc.save_to_path("table-example.hwpx")
```

실측 시그니처(2.8):

- `add_table(rows, cols, *, section=None, section_index=None, width=None, height=None, border_fill_id_ref=None, para_pr_id_ref=None, style_id_ref=None, char_pr_id_ref=None, run_attributes=None, **extra_attrs) -> HwpxOxmlTable`
- `set_cell_text(row_index, col_index, text, *, logical=False, split_merged=False) -> None`

주의:

- `set_cell_text()`는 `HwpxDocument` 메서드가 아니라 `add_table()`가 반환한 표 객체의 메서드다.
- 병합 셀에 논리 좌표로 쓰려면 `logical=True`를 사용한다.

### 메모 추가

```python
from hwpx import HwpxDocument

doc = HwpxDocument.new()
paragraph = doc.add_paragraph("검토가 필요한 문장입니다.")

memo, anchor_paragraph, field_value = doc.add_memo_with_anchor(
    "표현을 한 번 더 확인하세요.",
    paragraph=paragraph,
    author="검토자",
)
```

실측 시그니처(2.8):

- `add_memo_with_anchor(text="", *, paragraph=None, section=None, section_index=None, paragraph_text=None, memo_shape_id_ref=None, memo_id=None, char_pr_id_ref=None, attributes=None, field_id=None, author=None, created=None, number=1, anchor_char_pr_id_ref=None) -> tuple[HwpxOxmlMemo, HwpxOxmlParagraph, str]`

### 스타일 기반 런 검색과 치환

```python
with HwpxDocument.open("input.hwpx") as doc:
    red_runs = doc.find_runs_by_style(text_color="#FF0000")

    replaced = doc.replace_text_in_runs(
        "TODO",
        "DONE",
        text_color="#FF0000",
        underline_type="SOLID",
        limit=3,
    )

    doc.save_to_path("output.hwpx")
```

실측 시그니처(2.8):

- `find_runs_by_style(*, text_color=None, underline_type=None, underline_color=None, char_pr_id_ref=None) -> list[HwpxOxmlRun]`
- `replace_text_in_runs(search, replacement, *, text_color=None, underline_type=None, underline_color=None, char_pr_id_ref=None, limit=None) -> int`

주의:

- 빈 검색어는 허용되지 않는다.
- `replace_text_in_runs()`는 런 단위로 동작한다.
- 표 셀까지 보장되는 전역 치환이 필요하면 번들 스크립트 `scripts/zip_replace_all.py`를 사용한다.

### 내보내기

```python
with HwpxDocument.open("input.hwpx") as doc:
    text = doc.export_text()
    html = doc.export_html()
    markdown = doc.export_markdown()
```

실측 메서드:

- `export_text(**kwargs) -> str`
- `export_html(**kwargs) -> str`
- `export_markdown(**kwargs) -> str`

이 메서드들은 내부 exporter로 keyword argument를 그대로 전달한다.

### 헤더와 푸터

`set_header_text()`와 `set_footer_text()`는 일부 문서에서 레이아웃이 흔들릴 수 있다. 자동화 경로에서는 적용 후 결과 파일을 다시 열어 확인하는 방식으로 쓴다.

## TextExtractor

`TextExtractor`는 편집 DOM을 만들지 않고 읽기 전용으로 텍스트를 모을 때 적합하다.

### 전체 텍스트 추출

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
text = tex.extract_text(
    paragraph_separator="\n",
    skip_empty=True,
    include_nested=True,
)
```

실측 시그니처(2.8):

- `extract_text(*, paragraph_separator="\n", skip_empty=True, include_nested=True, object_behavior="skip", object_placeholder=None, preserve_breaks=True, annotations=None) -> str`

### 문단 단위 순회

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
for paragraph in tex.iter_document_paragraphs(include_nested=True):
    print(paragraph.section.index, paragraph.index, paragraph.path, paragraph.text())
```

실측 시그니처(2.8):

- `iter_document_paragraphs(*, include_nested=True) -> Iterator[ParagraphInfo]`

`ParagraphInfo`에서 자주 보는 필드:

- `section.index`
- `index`
- `path`
- `is_nested`
- `text()`

## ObjectFinder

특정 OWPML 태그나 속성을 전수 조사할 때 사용한다.

```python
from hwpx import ObjectFinder

finder = ObjectFinder("input.hwpx")
tables = finder.find_all(tag="tbl")
texts = finder.find_all(tag="t", limit=20)
first_table = finder.find_first(tag="tbl")
```

실측 시그니처(2.8):

- `find_all(*, tag=None, attrs=None, xpath=None, section_filter=None, limit=None) -> list[FoundElement]`
- `find_first(*, tag=None, attrs=None, xpath=None, section_filter=None) -> FoundElement | None`

`FoundElement`에서 자주 보는 필드:

- `tag`
- `path`
- `section.index`
- `text()`
- `get("속성명")`

## HwpxPackage

파트 단위 접근, 복구, 고급 검사에 사용한다.

```python
from hwpx import HwpxPackage

pkg = HwpxPackage.open("input.hwpx")
names = pkg.part_names()
main_xml = pkg.get_xml("Contents/section0.xml")
```

패키지 레벨에서 자주 쓰는 메서드:

- `open(path)`
- `part_names()`
- `get_part(name)`
- `get_xml(name)`
- `set_xml(name, element)`
- `read(name)`
- `write(name, data)`

## 예외와 주의사항

```python
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```

- 손상된 ZIP/OWPML 구조를 다룰 때는 `HwpxPackageError`, `HwpxStructureError`를 잡는다.
- `.hwp`는 대상이 아니다. `.hwpx`만 지원한다.
- ZIP-level 문자열 치환 뒤에는 `scripts/fix_namespaces.py` 또는 `scripts/zip_replace_all.py --auto-fix-ns`로 후처리한다.

## Proposal preset

`python-hwpx`의 proposal preset은 agent-first 제안서/기획안 생성을 위한 고수준 API다.

```python
from hwpx.presets import create_proposal_document, inspect_proposal_quality

proposal_spec = {
    "title": "AI 융합형 교육실 구축 제안서",
    "executive_summary": "핵심 요약을 작성합니다.",
    "sections": [
        {"title": "추진 배경 및 문제 정의", "paragraphs": ["배경 설명"]},
        {"title": "제안 내용", "bullets": ["핵심 제안 1"]},
        {"title": "구축 및 운영 계획", "paragraphs": ["추진 일정"]},
    ],
    "budget_items": [{"item": "기자재", "amount": "5,000,000원", "note": "노트북"}],
    "expected_outcomes": ["수업 참여도 향상"],
    "closing": "검토 후 승인 요청드립니다.",
}

doc = create_proposal_document(proposal_spec)
doc.save_to_path("proposal.hwpx")
doc.close()

report = inspect_proposal_quality("proposal.hwpx")
assert report["rubric_average"] >= 4.0
assert report["sample_match"]["pass"] is True
```

주요 함수:

- `create_proposal_document(spec, *, preset="clean_korean_proposal") -> HwpxDocument`
- `inspect_proposal_quality(source) -> dict`

품질 기준:

- rubric 평균 4.0 이상
- `sample_match.average` 4.0 이상 및 실패 dimension 없음
- critical validation error 없음
- 생성 파일 payload 5MB 미만 권장
- `visual_review_required=True`이면 렌더러/픽셀 diff 없이 proxy 기준만 통과한 상태
