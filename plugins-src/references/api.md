# python-hwpx API 레퍼런스

`hwpx-plugins`에서 반복적으로 참조하는 `python-hwpx` API만 추렸다. 스킬 본문은 워크플로 중심이고, 이 문서는 시그니처와 사용 포인트를 빠르게 확인하는 용도다.

버전 숫자는 세 가지 뜻을 구분한다. 값의 machine-readable 정본은
`packaging/product-identity.json`이다.

| 용어 | 의미 | 현재 값 |
|---|---|---|
| 완전한 공개 트레인 | 마지막으로 plugin 설치까지 함께 검증한 조합 (released 2026-08-03, 양식개체·기안문 장르 트레인) | `python-hwpx 5.7.0` · `python-hwpx-automation 6.7.1` · `hwpx-plugin 1.7.0` |
| 릴리스 상태 | 이 checkout의 train 상태 — `release-approved`: 미발행 후보 승인됨, 원격 진실 관찰 대기 | `python-hwpx 6.0.2` · `python-hwpx-automation 7.0.1` · `hwpx-plugin 2.0.0` |
| 최소 호환 버전 | 1.6 스킬 계약이 지원하는 가장 낮은 조합 | core `>=5.7.0` · automation `>=6.5.0` · skill `>=1.7.0` |
| 플러그인 설치 핀 | 번들이 재현 검증에 사용하는 정확 버전 | `python-hwpx[preview]==6.0.2` · `python-hwpx-automation[mcp,oracle]==7.0.1` |

- import 이름은 `hwpx`다.
- 코어의 공개 성숙도는 `Development Status :: 3 - Alpha`이고 MCP/플러그인의 성숙도는
  아직 선언하지 않았다. 공개 릴리스나 호환성 숫자를 성숙도 주장으로 바꾸지 않는다.
- 최종 산출물을 만들 때는 `validate_editor_open_safety(path).ok == True` 또는 MCP 응답의 `openSafety.ok == true` / `verification.openSafety.ok == true`를 handoff evidence로 남긴다.

## 목차

- 설치와 기본 import
- `HwpxDocument`
- `hwpx_automation.office.authoring.builder`
- `TextExtractor`
- `ObjectFinder`
- `HwpxPackage`
- Document plan authoring
- Template form-fit authoring
- Mail merge and table compute
- MCP 편집·서식·생성 도구 시그니처
- 예외와 주의사항

## 설치와 기본 import

```bash
pip install -U python-hwpx lxml
```

이 스킬의 최종 HWPX 산출물 작성에는 최소 호환 버전인 `python-hwpx >= 6.0.2`이 필요하다.
더 낮은 버전은 현재 계약 밖이므로 handoff용 파일 생성에 사용하지 않는다.

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

현재 공개 문서화 기준(5.0.1) 시그니처:

- `add_table(rows, cols, *, section=None, section_index=None, width=None, height=None, border_fill_id_ref=None, para_pr_id_ref=None, style_id_ref=None, char_pr_id_ref=None, run_attributes=None, inherit_style=False, **extra_attrs) -> HwpxOxmlTable`
- `set_cell_text(row_index, col_index, text, *, logical=False, split_merged=False, preserve_format=True, split_paragraphs=False, fit=None, ledger=None) -> FitResult | None`

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

현재 공개 문서화 기준(5.0.1) 시그니처:

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

현재 공개 문서화 기준(5.0.1) 시그니처:

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

간단한 문자열은 `set_header_text()`와 `set_footer_text()`로 넣을 수 있다. 리치 런과
쪽번호가 필요한 머리글/바닥글은 `hwpx_automation.office.authoring.builder` 또는 아래 facade 메서드를 사용한다.
자동화 경로에서는 적용 후 결과 파일을 다시 열어 확인하는 방식으로 쓴다.

현재 facade:

- `set_header_content(content, *, section_index=0) -> None`
- `set_footer_content(content, *, section_index=0) -> None`
- header/footer 객체의 `add_page_number_field(*, paragraph=None, format="page", position="BOTTOM_CENTER") -> Element`

섹션 관리 facade:

- `add_section(*, after: int | None = None) -> HwpxOxmlSection`
- `remove_section(section: HwpxOxmlSection | int) -> None`

3.2.0 공개 릴리스의 `add_section()`은 인접 섹션의 유효한 용지·여백·단 설정만 복제하고
머리글/바닥글 story는 복제하지 않는다. 새 section part와 manifest/spine 순서,
`Contents/header.xml`의 `secCnt`를 함께 맞추며, 양의 페이지 geometry를 만들 수 없으면
mutation 전에 실패한다. `remove_section()`도 같은 section count 계약을 유지한다.

`content`는 paragraph spec 목록이다. 각 paragraph는 `{"children": [...]}` 형태이고,
child는 `{"type": "run", "text": "...", "bold": True, ...}` 또는
`{"type": "page_number", "format": "page"}`다.

## 문서 빌더 — `hwpx_automation.office.authoring.builder`

`hwpx_automation.office.authoring.builder`는 docx-js처럼 문서를 객체 노드로 조립한 뒤 `HwpxDocument` facade를
통해 HWPX로 lowering하는 새 문서 생성 API다. builder 내부에서 임의 XML을 직접
만들지 않는 것이 계약이다.

공개 노드:

- `Document`, `Section`
- `PageSize`, `Margins`, `Metadata`
- `Heading`, `Paragraph`, `Run`
- `Bullet`, `NumberedList`
- `Table`, `Image`
- `Header`, `Footer`, `PageNumber`, `PageBreak`
- `approval_box`
- `BuilderSaveReport`, `ReopenReport`

기본 예시:

```python
from hwpx_automation.office.authoring.builder import (
    Bullet,
    Document,
    Footer,
    Header,
    Heading,
    Margins,
    Metadata,
    PageBreak,
    PageNumber,
    PageSize,
    Paragraph,
    Run,
    Section,
    Table,
)

report = Document(
    metadata=Metadata(title="2026 AI 교육 운영계획", author="AI교육팀", organization="샘플학교"),
    sections=[
        Section(
            page=PageSize.A4,
            margins=Margins(top_mm=20, right_mm=20, bottom_mm=20, left_mm=20),
            header=Header(
                children=[
                    Paragraph(
                        align="right",
                        children=[Run("샘플학교 - ", bold=True, color="C00000"), PageNumber()],
                    )
                ]
            ),
            footer=Footer(children=[Paragraph(align="center", children=[PageNumber(format="page/total")])]),
            children=[
                Heading(level=1, text="추진 개요"),
                Heading(level=2, text="세부 목표"),
                Paragraph(
                    children=[
                        Run("AI 활용 수업을 "),
                        Run("전 학년", bold=True, color="1F5FBF", font="함초롬바탕", size=12),
                        Run("으로 확산한다."),
                    ]
                ),
                Bullet(items=["교원 연수", "수업 공개"]),
                Table(
                    header=["구분", "내용", "기한"],
                    rows=[["준비", "환경 점검", "3월"], ["운영", "수업 적용", "4월"]],
                    column_widths=[2, 3, 1],
                    header_shading="EAF1FB",
                    merges=["A2:A3"],
                ),
                PageBreak(),
                Paragraph(text="다음 페이지 점검"),
            ],
        )
    ],
).save_to_path("builder-plan.hwpx")

assert report.hard_gates["package_validation"] == "pass"
assert report.hard_gates["document_errors"] == "pass"
assert report.hard_gates["reopen"] == "pass"
```

대표 시그니처:

- `Document(sections=(Section(),), metadata=None, visual_review_required=None)`
- `Document.lower() -> HwpxDocument`
- `Document.save_to_path(path) -> BuilderSaveReport`
- `Section(children=(), page=None, margins=None, header=None, footer=None)`
- `Run(text="", bold=False, italic=False, underline=False, color=None, font=None, size=None, highlight=None, strike=False)`
- `Paragraph(text="", children=(), align=None)`
- `Heading(level, text)` where `level` is 1-3
- `approval_box(labels=None, approver_rows=2, delegated=None) -> Table`
- `Bullet(items, level=0)`
- `NumberedList(items, level=0)`
- `Table(header=(), rows=(), merges=(), header_shading=None, column_widths=())`
- `Image(path, width_mm=None, align=None, caption=None, image_format=None)`
- `PageNumber(format="page")`

`Table.merges`는 `"A2:A3"` 같은 range token을 받는다. `column_widths`는 상대 비율로
해석된다. `Image.path`는 파일 경로 또는 bytes를 받을 수 있다.

`BuilderSaveReport` 주요 필드:

- `path`
- `validate_package`
- `validate_document`
- `reopened`
- `metadata`
- `hard_gates`
- `visual_review_required`
- `feature_flags`
- `to_dict()`

Hard gate 해석:

- `hard_gates.package_validation == "pass"`: package validator 통과
- `hard_gates.document_errors == "pass"`: document validator error 없음
- `hard_gates.schema_lint == "warning"`: schema warning 존재. warning은 가시화 대상이며 hard fail이 아니다.
- `hard_gates.reopen == "pass"`: `HwpxDocument.open(path)` 재오픈 성공
- `hard_gates.id_integrity == "unavailable"`: 현 버전에서 별도 ID integrity gate는 아직 제공되지 않음

`feature_flags`는 생성에 사용된 기능을 기록한다. `header_footer`, `page_number`,
`table`, `image`, `page_break` 같은 layout-sensitive 기능이 있으면 기본적으로
`visual_review_required=True`가 된다. 이 경우 최종 제출 가능 주장 요건은
[`evidence-contract.md`](evidence-contract.md)를 따른다.

검증 예시:

```bash
python3 examples/10_create_with_builder.py
python3 scripts/quickcheck.py --builder
```

### Builder 관련 facade 확장

builder가 사용하는 신규 facade 메서드는 직접 XML을 조작하지 않고도 주요 OWPML gap을
다룰 수 있게 한다.

- `ensure_run_style(bold=False, italic=False, underline=False, color=None, font=None, size=None, highlight=None, strike=None, base_char_pr_id=None) -> str`
- `ensure_numbering(kind="bullet", levels=None) -> list[str]`
- `add_picture(image_data, image_format, *, width=None, height=None, width_mm=None, height_mm=None, align=None, section_index=None, ...) -> HwpxOxmlInlineObject`
- `set_header_content(content, *, section_index=None, page_type="BOTH") -> HwpxOxmlSectionHeaderFooter`
- `set_footer_content(content, *, section_index=None, page_type="BOTH") -> HwpxOxmlSectionHeaderFooter`
- header/footer 객체의 `add_page_number_field(*, paragraph=None, format="page", position="BOTTOM_CENTER") -> Element`

표 객체 확장:

- `table.merge_cells("A2:A3")`
- `table.set_cell_shading(row_index, col_index, "EAF1FB")`
- `table.set_column_widths([2, 3, 1])`

## Mail merge and table compute

### 메일머지 대량생산

템플릿 HWPX 1개와 CSV/JSON/행 데이터로 여러 산출물을 만들 때 사용한다. 지원
placeholder 형식은 `{{field}}`, `${field}`, `<<field>>`다.

```python
from hwpx import inspect_mail_merge_placeholders
from hwpx_automation.office.document_ops import build_mail_merge

placeholders = inspect_mail_merge_placeholders("template.hwpx")
assert "student" in placeholders["keys"]

report = mail_merge(
    "template.hwpx",
    [{"student": "김하나", "class_name": "1-1", "teacher": "이교사"}],
    output_dir="out/notices",
    filename_pattern="{index:03d}-{student}.hwpx",
    zip_path="out/notices.zip",
)

assert report["createdCount"] == report["rowCount"]
assert report["openSafety"]["ok"]
```

MCP가 있으면 `mail_merge(template_filename, data_rows=...|data_filename=..., output_dir=..., filename_pattern=..., zip_filename=...)`를 호출한다.
확인할 반환값:

- `createdCount`, `rowCount`, `rowsWithIssues`
- `rows[].missingKeys`
- `rows[].unresolvedPlaceholders`
- `rows[].openSafety.ok`
- `verification.openSafety.checkedCount`
- `zip.entryCount`

`strict=false`가 기본값이다. 결측 데이터가 있어도 산출물을 만들고 row report에
문제를 남긴다. 결측 행 생성을 막아야 하면 `strict=true`를 사용한다.

### 일반 표 계산

`table_compute()`는 plan v2 table(`header`/`rows`), plan v1 table
(`columns`/`rows`), list-of-dicts 표를 받아 합계·평균·소계 행/열을 추가한다.

```python
from hwpx_automation.office.utilities import table_compute

result = table_compute(
    {
        "type": "table",
        "columns": [
            {"key": "dept", "label": "부서"},
            {"key": "item", "label": "항목"},
            {"key": "amount", "label": "금액"},
        ],
        "rows": [
            {"dept": "교육", "item": "연수", "amount": "1,000"},
            {"dept": "교육", "item": "교재", "amount": "500"},
        ],
    },
    value_columns=["amount"],
    operations=["subtotal", "sum", "average"],
    group_by="dept",
    label_column="item",
)

computed_table = result["computedTable"]
evidence = result["evidence"]
```

주요 옵션:

- `value_columns`: 계산할 열 key/label/index. 생략하면 숫자 열을 자동 탐지한다.
- `operations`: `sum`, `average`, `subtotal`.
- `append`: `rows`, `columns`, `both`.
- `group_by`: `subtotal` 기준 열.
- `label_column`: 합계/평균/소계 label을 넣을 열.
- `labels`: 기본 label을 바꿀 때 사용한다. 예: `{"sum": "총계"}`.

반환된 `computedTable`은 document-plan table block으로 다시 사용할 수 있다.
`evidence[]`는 operation, axis, source columns/rows, source value count, result를
기록하므로 handoff나 검산 근거로 남긴다.

검증 예시:

```bash
python3 examples/14_mail_merge_table_compute.py
```

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

현재 공개 문서화 기준(5.0.1) 시그니처:

- `extract_text(*, paragraph_separator="\n", skip_empty=True, include_nested=True, object_behavior="skip", object_placeholder=None, preserve_breaks=True, annotations=None) -> str`

### 문단 단위 순회

```python
from hwpx import TextExtractor

tex = TextExtractor("input.hwpx")
for paragraph in tex.iter_document_paragraphs(include_nested=True):
    print(paragraph.section.index, paragraph.index, paragraph.path, paragraph.text())
```

현재 공개 문서화 기준(5.0.1) 시그니처:

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

현재 공개 문서화 기준(5.0.1) 시그니처:

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

## Repair/recover tools

HWPX가 한컴에서 열리지 않거나 ZIP central directory가 깨진 경우, 원본을 직접 덮어쓰지 말고 복구 복사본을 만든다.

### Local CLI

```bash
# 일반 repair-repack: mimetype 첫 엔트리/ZIP_STORED 강제 + CRC/package 검증
hwpx-repair input.hwpx repaired.hwpx

# central directory 손상 등 일반 ZIP open 실패 시 Local File Header scan 복구
hwpx-repair --recover broken.hwpx recovered.hwpx
```

### Python API

```python
from hwpx.tools.repair import repair_from_recovered, repair_repack
from hwpx.tools.recover import recover_entries

result = repair_repack("input.hwpx", "repaired.hwpx")
assert result.crc_ok is True

recovered = repair_from_recovered("broken.hwpx", "recovered.hwpx")
assert recovered.recovered is True
```

확인할 필드:

- `reordered`: `mimetype` 순서나 압축 방식이 고쳐졌는지
- `crc_ok`: 새 ZIP의 CRC/integrity self-check 통과 여부
- `recovered`: LFH scan 복구 경로를 썼는지
- `entries`: 보존된 ZIP 엔트리 목록

### MCP tool

MCP 서버가 연결되어 있으면 `repair_hwpx`를 우선 사용한다.

```json
{
  "source_filename": "input.hwpx",
  "output_filename": "repaired.hwpx",
  "recover": false,
  "overwrite": false
}
```

central directory 손상으로 일반 open이 실패하면:

```json
{
  "source_filename": "broken.hwpx",
  "output_filename": "recovered.hwpx",
  "recover": true,
  "overwrite": false
}
```

MCP 응답에서 확인할 필드:

- `crcOk == true`
- `validatePackage.ok == true`
- `openSafety.ok == true`
- `reordered`
- `recovered`
- `entryCount`

복구 후에도 최종 제출/납품 전에는 가능하면 Hancom Office HWP 또는 사용 가능한 viewer에서 실제 열람한다.

## MCP 편집·서식·생성 도구 시그니처

6.7.1 후보 `python-hwpx-automation`의 트랜잭션·서식·그림·비교·생성기·문서 지도 도구 요약이다.
사용 절차는 `workflows-agent-document.md` / `workflows-editing.md` /
`workflows-bulk-compare.md`를 본다. 지원 인자와 응답 증거는 도구별로 다르며 아래 표와
`tool-contract.generated.json`의 실제 스키마를 따른다.

| 도구 | 시그니처 (주요 인자) | 핵심 응답 키 |
|---|---|---|
| `apply_document_commands` | `(filename, output, commands, expected_revision, idempotency_key, dry_run, quality, verification_requirements, overwrite)` | `ok`, `rolledBack`, `commandResults[]`, `semanticDiff`, `verificationReport` |
| `apply_edits` | `(filename, operations, dry_run, expected_revision, idempotency_key, quality)` | `ok`, `rolledBack`, `operationsApplied`, `operationResults[]`, `semanticDiff` |
| `undo_last_edit` | `(filename)` | `restored`, `backupPath`, `openSafety`, `semanticDiff` |
| `byte_preserving_patch` | `(filename, patches=[{sectionPath, paragraphIndex, text}], output)` | `changedParts[]`, `byteIdentical`, `skipped[]`, `openSafety` |
| `set_paragraph_format` | `(filename, paragraph_index|paragraph_indexes, alignment, line_spacing_percent, indent_left_mm, indent_right_mm, first_line_indent_mm, spacing_before_pt, spacing_after_pt, outline_level)` | 적용 결과 + `openSafety` |
| `set_page_setup` | `(filename, paper_size, width_mm, height_mm, orientation, margins_mm|margin_*_mm, header_margin_mm, footer_margin_mm, gutter_mm, columns, column_gap_mm, section_index)` | `pageSize.{width,height}`, `openSafety` |
| `set_header_footer` | `(filename, kind="header"|"footer", text|content, section_index, page_type="BOTH")` | `headerFooter.{kind,pageType,id,text,pageNumberCount}` |
| `set_page_number` | `(filename, target="footer", format="page"|"page/total", align, position, prefix, suffix, format_type, section_index)` | `headerFooter.pageNumberCount` |
| `set_list_format` | `(filename, paragraph_index|paragraph_indexes, kind="bullet"|"number", level, bullet_char, number_format, start)` | 적용 결과 + `openSafety` |
| `insert_picture` | `(filename, image_base64, image_format, width_mm, height_mm, section_index, align, output)` | `picture.binaryItemIDRef`, `pictureReferences[]`, `idIntegrity.ok` |
| `replace_picture` | `(filename, image_base64, image_format, picture_index, binary_item_id_ref, remove_orphaned, output)` | `replacement.{geometryPreserved, old_binaryItemIDRef, new_binaryItemIDRef, removedOldImage}` |
| `doc_diff` | `(old_filename, new_filename | old_paragraphs, new_paragraphs)` | `summary.counts.{changed, added, ...}` (읽기 전용) |
| `create_comparison_table_document` | `(filename, old_*|new_*, title="신구대조표", include_equal, verbosity)` | `created`, `document_plan`, `plan_validation`, `verification.openSafety.ok` |
| `build_image_grid` | `(images=[{path, caption}], columns, image_width_mm, title="사진대지")` | `block`, `document_plan`, `next_tool="create_document_from_plan"` |
| `build_meeting_nameplates` | `(names, size="150x70", columns, title)` | `block`, `document_plan`, `next_tool` |
| `build_organization_chart` | `(hierarchy={name, children}, max_depth, title)` | `block`, `document_plan`, `next_tool` |
| `get_document_map` | `(filename, max_preview_chars=80)` | `info`, `outline`, `sections[]`, `tables`, `formFields`, `anchors`, `document_revision` (읽기 전용) |
| `document_to_markdown` | `(filename, output="full"|"chunks", chunk_strategy, max_chars_per_chunk, mask)` | `ok`, `markdown`, `meta.{source_format,engine}`, `warnings`, `attempts[]` |
| `document_extract_json` | `(filename, output="full"|"chunks", chunk_strategy, max_chars_per_chunk, mask)` | `ok`, `doc.{markdown,sections,tables,metadata}`, `meta`, `attempts[]` |
| `markdown_to_document_plan` | `(markdown, title, metadata, style_preset)` | `ok`, `can_create`, `document_plan`, `validation`, `warnings`, `next_tool` |

`apply_document_commands`는 공개 node catalog를 바꾸지 않으면서 command-only 경로
`/section[N]/header[@page-type="BOTH"|"EVEN"|"ODD"]` 또는
`/section[N]/header[@id="..."]`로 **이미 존재하는 단순 머리글**의 텍스트를 본문·표 셀과
같은 batch에서 바꿀 수 있다. rich run, control, 모호한 selector, 새 머리글 생성은 generic
우회 없이 `unsupported_content`·`ambiguous_target`·`not_found`로 닫힌다. 성공 시
`verificationReport.storyPreservation`에서 stable identity와 reopen text 일치를 확인한다.

`document_revision`을 반환하는 도구에서는 이 값(`"sha256:..."`)을 낙관적 동시성
토큰으로 사용한다. 생성 계약에 `expected_revision`이 선언된 쓰기 도구에 넘기면 외부
변경 시 `reason: "document revision mismatch"`로 차단된다. `idempotency_key`는
이를 선언한 `apply_document_commands`, `apply_edits`, `search_and_replace`,
`batch_replace` 등의 중복 적용 방지 키다.

일반 문서 ingest: HWPX는 `python-hwpx` engine으로 변환된다. 비-HWPX는 서버가
`python-hwpx-automation[ingest]`(또는 옛 이름 `hwpx-mcp-server[ingest]`) extra로 설치되어 있을 때 MarkItDown adapter가 처리한다.
adapter 결과는 구조 읽기용 Markdown이며 레이아웃 충실도는 주장하지 않는다.

## 예외와 주의사항

```python
from hwpx.opc.package import HwpxPackageError, HwpxStructureError
```

- 손상된 ZIP/OWPML 구조를 다룰 때는 `HwpxPackageError`, `HwpxStructureError`를 잡는다.
- `.hwp`는 대상이 아니다. `.hwpx`만 지원한다.
- ZIP-level 문자열 치환은 `scripts/zip_replace_all.py`를 사용한다. 이 helper는 임시 파일을 만든 뒤 `validate_editor_open_safety()`를 통과한 경우에만 target을 교체한다.
- namespace 정리만 필요하면 `scripts/fix_namespaces.py`를 사용한다. 이 helper도 open-safety 검증 실패 시 기존 target을 보존한다.
- ZIP 자체가 열리지 않거나 `mimetype` 첫 엔트리/CRC 오류가 있으면 편집 전에 `repair_hwpx` 또는 `hwpx-repair`로 복구 복사본을 만든다.

## Document plan authoring

`hwpx.document_plan.v1`은 agent가 자연어 요청을 OWPML이 아닌 JSON 계획으로 정리한 뒤, `python-hwpx`가 공개 API만 사용해 HWPX를 생성하는 경로다.

```python
from hwpx_automation.office.authoring import (
    create_document_from_plan,
    inspect_document_authoring_quality,
    inspect_operating_plan_quality,
    validate_document_plan,
)

document_plan = {
    "schemaVersion": "hwpx.document_plan.v1",
    "title": "2026 AI Education Operating Plan",
    "metadata": {"organization": "Sample School", "date": "2026-05-09"},
    "blocks": [
        {"type": "heading", "level": 1, "text": "Executive Summary"},
        {"type": "paragraph", "text": "The plan connects lessons, training, and review."},
        {"type": "bullets", "items": ["Run grade-band AI lessons.", "Review outcomes each term."]},
        {
            "type": "table",
            "caption": "Budget Plan",
            "columns": [
                {"key": "item", "label": "Item", "widthWeight": 2},
                {"key": "amount", "label": "Amount", "widthWeight": 1},
            ],
            "rows": [{"item": "AI devices", "amount": "5,000,000 KRW"}],
        },
    ],
    "qualityGates": {
        "validatePackage": True,
        "validateDocument": True,
        "reopen": True,
        "visualReviewRequired": True,
    },
}

validation = validate_document_plan(document_plan)
if not validation.ok:
    for issue in validation.to_dict()["issues"]:
        print(issue["code"], issue["path"], issue["message"])
    for hint in validation.to_dict()["repairHints"]:
        print(hint["action"], hint["path"], hint["message"])
    raise SystemExit(1)

doc = create_document_from_plan(document_plan)
doc.save_to_path("agent-plan.hwpx")
doc.close()

from hwpx.tools import validate_editor_open_safety

report = inspect_document_authoring_quality("agent-plan.hwpx", plan=document_plan)
assert report["pass"] is True
assert report["validation"]["validate_package"]["ok"] is True
assert report["validation"]["validate_document"]["ok"] is True
assert validate_editor_open_safety("agent-plan.hwpx").ok is True
```

주요 함수:

- `validate_document_plan(plan) -> PlanValidationReport`
- `normalize_document_plan(plan) -> DocumentPlan`
- `create_document_from_plan(plan, *, preset="standard_korean_business") -> HwpxDocument`
- `inspect_document_authoring_quality(source, *, plan=None, quality_profile=None) -> dict`
- `inspect_operating_plan_quality(source, *, plan=None, profile=None) -> dict`
- `inspect_official_document_style(source) -> dict`

`PlanValidationReport.to_dict()` 주요 필드:

- `ok`: error가 없으면 `True`. warning만 있으면 생성 가능하다.
- `errors`, `warnings`: 기존 문자열 호환 필드.
- `issues`: `PlanValidationIssue` 목록. 각 issue는 `code`, `path`, `message`, `severity`, `suggestion`을 가진다.
- `repairHints`: agent가 다음 수정에 바로 사용할 수 있는 `{path, code, action, message}` 목록.

대표 issue code:

- `invalid_schema_version`, `missing_blocks`, `unsupported_block_type`
- `invalid_heading_level`, `missing_text`, `missing_bullet_items`
- `missing_table_columns`, `missing_table_rows`, `invalid_table_row`
- `duplicate_table_column_key`, `table_row_missing_cells`, `table_row_extra_cells`
- `unknown_style_token`, `invalid_width_weight`

지원 block:

- `heading`: `level` 1-3, `text`
- `paragraph`: `text`
- `bullets`: `items`
- `table`: `caption`, `columns`, `rows`
- `page_break`
- `memo`

검증 리포트에서 반드시 확인할 필드:

- `pass`
- `validation.reopened`
- `validation.validate_package.ok`
- `validation.validate_package.issues`
- `validation.validate_document.ok`
- `validation.validate_document.issues`
- MCP 생성 응답의 `verification.openSafety.ok`
- `recovery.repair_hints`
- `recovery.next_actions`
- `visual_review_required`

`visual_review_required=True`는 구조/스키마 검증은 통과했지만 렌더러나 사람의 시각 검수는 별도로 필요하다는 뜻이다.

패키징 오류(`mimetype` 순서/압축, manifest/version 참조 등)나 schema 오류가 있으면
`validation.*.issues[]`의 `part`, `message`, `suggestion`을 따라 재저장 또는 plan
재생성을 수행한 뒤 `inspect_document_authoring_quality()`를 다시 실행한다.

### Operating plan quality profile

운영 계획서는 `quality_profile="operating_plan"`을 켜서 구조 검증과
제출 후보 품질 검증을 분리한다.

```python
report = inspect_document_authoring_quality(
    "operating-plan.hwpx",
    plan=document_plan,
    quality_profile="operating_plan",
)
profile = report["profiles"]["operating_plan"]
assert profile["pass"] is True

direct = inspect_operating_plan_quality("operating-plan.hwpx", plan=document_plan)
assert direct["profile_version"] == "operating-plan-quality-v1"
```

MCP 운영 계획서 경로에서 확인할 필드:

- `analyze_document_plan(..., quality_profile="operating_plan")`
- `create_document_from_plan(..., quality_profile="operating_plan")`
- `handoff_status`: `ready` 또는 `needs_revision`
- `next_action`: 다음 조치 안내
- `quality.profiles.operating_plan.pass`
- `quality.profiles.operating_plan.score`
- `quality.profiles.operating_plan.gaps[]`
- `quality.profiles.operating_plan.repair_hints[]`

운영 계획서 handoff 기준:

- `plan_validation.ok == true`
- `quality.validation.reopened == true`
- `quality.validation.validate_package.ok == true`
- `quality.validation.validate_document.ok == true`
- `verification.openSafety.ok == true`
- `quality.profiles.operating_plan.pass == true`
- `visual_review_required == true`이면 최종 제출 전 렌더링 또는 사람의 시각 검토 필요

## Template form-fit authoring (호환 — DEPRECATED, 5.0 경계 확정)

> **새 양식 채움 작업은 canonical `analyze_form_fill` → `apply_form_fill` →
> `verify_form_fill` 경로를 사용한다** —
> [workflows-forms.md](workflows-forms.md) 참조. 이 template-formfit 쌍은 5.0
> 경계에서 `ToolClassification.DEPRECATED`로 확정됐다: 기존 baseline 자동화
> 호환으로 계속 동작하지만 새 사용은 금지이며, 제거는 다음 major다. 회귀 자산은
> `examples/08_template_formfit.py`(quickcheck `--template-formfit` 게이트)다.

`hwpx.template-formfit.baseline.v1`은 승인된 HWPX 양식을 보존하면서 특정
anchor 아래의 placeholder scaffold와 표 영역만 채우는 계약이다.

**DEPRECATED** 호환 함수 — 구조적 채움은 `apply_table_ops`(`fill_cells` 등)로,
mixed-form 채움은 canonical `analyze_form_fill`/`apply_form_fill`/`verify_form_fill`로
대체한다:

- `analyze_template_formfit(source, *, baseline, content, destination=None, options=None) -> dict`
- `apply_template_formfit(*, analysis=None, source=None, baseline=None, content=None, destination=None, confirm=True) -> dict`

**DEPRECATED** MCP 도구 — 대체는 위와 동일:

- `analyze_template_formfit(source_filename, baseline, content, destination_filename=None)`
- `apply_template_formfit(analysis=None, source_filename=None, baseline=None, content=None, destination_filename=None, confirm=True)`

handoff 기준:

- `analysis.mutated == false`
- `analysis.source.unchanged_after_analysis == true`
- `analysis.unresolved_count == 0`
- `result.handoff_status == "ready"`
- `result.source.preserved == true`
- `result.validation.validate_package.ok == true`
- `result.validation.validate_document.ok == true`
- `result.validation.openSafety.ok == true`
- `result.residual_markers.blocking == []`

제한:

- source와 destination이 같으면 apply는 거부된다.
- anchor가 없거나 둘 이상이면 apply 전 `unresolved`로 막는다.
- 이미지/평면도/픽셀 단위 레이아웃은 자동 보장하지 않는다.
- `visual_review_required=True`이면 최종 제출 전에 열린 문서 또는 사람의 시각 검토가 필요하다.

### Visual review evidence

visual-review v1 증거 계약(상태 규칙, screenshot 요건, blocked fallback, 재생성 연결,
`ready_for_submission_claim`)은 [`evidence-contract.md`](evidence-contract.md) 한 곳에만
있다. `visual_review_required=true`가 나오면 그 문서의 요건을 따른다.

## Multi-host plugin bundles

`plugins/<host>/` holds generated, committed bundles for Claude Code, Codex, OpenClaw, and
Hermes Agent, built from the repo-root skill assets by `scripts/build_hwpx_plugins.py` and
checked by `scripts/validate_hwpx_plugin.py`.

New bundles use the host-local key `hwpx` and canonical launcher
`scripts/hwpx-automation-mcp`, which executes the
`hwpx-automation-mcp` console. The old `scripts/hwpx-mcp-server` path remains
only as a 6.x wrapper that delegates to the canonical launcher; neither host
key is the FastMCP protocol identity. The canonical launcher resolves, in order:

1. explicitly configured `HWPX_AUTOMATION_REPO` / `PYTHON_HWPX_REPO`
   editable checkouts (`HWPX_MCP_SERVER_REPO` is the 6.x compatibility alias)
2. an immutable plugin-local runtime fingerprinted by the exact package pair
   from the install pin above, plus the skill, Python ABI, and platform values
3. an exact-version `uvx` fallback when `uv` is unavailable

Sibling repositories are never auto-discovered; candidate verification must not
silently select an unrelated checkout. Codex uses the same exact package pair
directly through `uvx`. Neither host
template sets `cwd`, so the server inherits the user's active workspace. For a
deterministic single or multi-root policy, set `HWPX_AUTOMATION_WORKSPACE_ROOTS` to a
JSON array of absolute directories. Relative tool paths resolve under the first
root; absolute paths are accepted under any listed root.

Run `python3 scripts/build_hwpx_plugins.py` after changing `SKILL.md`, `references`, `examples`,
or skill scripts, then `python3 scripts/validate_hwpx_plugin.py`.

## Proposal preset

`python-hwpx`의 proposal preset은 agent-first 제안서/기획안 생성을 위한 고수준 API다.

```python
from hwpx_automation.office.authoring.presets import (
    create_proposal_document,
    inspect_proposal_quality,
)

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
