# 편집 워크플로 (트랜잭션·서식·그림·패치·프리뷰)

기존 HWPX를 수정하는 주요 경로의 상세 계약. 시그니처와 응답 키는 S-080 공개 릴리스
`hwpx-mcp-server` 4.1.0의 생성 계약과 도구별 테스트를 기준으로 한다. 정확한 현재
시그니처는 `tool-contract.generated.json`을 우선한다.

## 1. 호환 트랜잭션 편집 루프 (`apply_edits`, compatibility facade)

`apply_edits`는 전환기 호환 facade다. 새 이종 편집 흐름은
`workflows-agent-document.md`의 `apply_document_commands`를 우선한다.
특히 본문·표 셀·이미 존재하는 단순 머리글 story를 같은 트랜잭션에서 바꿀 때는
command-only header canonical path와 `verificationReport.storyPreservation` 계약을 그 문서에서
확인한다. 새 머리글 생성이나 rich/control story 편집은 이 generic 경로로 우회하지 않는다.

```
apply_edits(filename, operations, dry_run=False, expected_revision=None, idempotency_key=None, quality=None)
```

호스트 기본 quality policy를 따르려면 `quality=None`을 유지한다. 명시적으로 transparent
검증만 요청할 때에만 `quality="transparent"`를 전달한다.

여러 편집 operation을 **원자적으로** 적용한다. 한 operation이라도 실패하면 파일은
변경되지 않고 `{"ok": false, "rolledBack": true, "failedOperationIndex": N, "error": ...}`가
돌아온다. 성공 응답 키: `ok`, `operationsApplied`, `operationResults[]`(operation별 결과 +
`operationIndex`), `openSafety`, `verificationReport`, `backup`, `semanticDiff`,
`document_revision`.

### operation 스키마

`type`은 snake_case(`replace-text`도 허용). camelCase/snake_case 인자 키 모두 허용된다.

| type | 필수/주요 인자 | operation 결과 키 |
|---|---|---|
| `replace_text` | `findText`, `replaceText` | `replaced_count` |
| `batch_replace` | `replacements` (`[{find, replace}]`) | 치환 리포트 |
| `add_paragraph` | `text`, `style?` | `paragraph_index` |
| `add_heading` | `text`, `level`(1~3) | `paragraph_index` |
| `insert_paragraph` | `paragraphIndex`, `text`, `style?` | `inserted_index` |
| `delete_paragraph` | `paragraphIndex` | `deleted_index`, `remaining_paragraphs` |
| `add_table` | `rows`, `cols`, `data?` | `table_index` |
| `set_table_cell_text` | `tableIndex`, `row`, `col`, `text`, `preserveFormat?`, `splitParagraphs?` | 좌표 echo |
| `fill_by_path` | `mappings` (`{"라벨 > right": "값"}`) | 채움 리포트 |
| `add_page_break` | (없음) | `success` |

### dry_run 응답 읽는 법

`dry_run=true`이면 원본은 저장하지 않고 임시 파일에 저장해 검증만 한다. 확인할 키:

- `dryRun == true`, `wouldSave == true`
- `openSafety.ok == true` — dry-run 산출물도 open-safety를 통과해야 한다.
- `semanticDiff.changed`, `semanticDiff.summary`, `semanticDiff.items[]`,
  `semanticDiff.counts.{paragraphsBefore,paragraphsAfter,tablesBefore,tablesAfter}` —
  의도한 변경만 있는지 여기서 판정한다.

### expected_revision (낙관적 동시성)

revision을 반환하고 `expected_revision`을 받는 도구에서는 확정 저장 시 직전에 읽은
`document_revision`(`"sha256:..."`)을 넘긴다. 파일이 그 사이 바뀌었으면:

```json
{"ok": false, "handoff_status": "blocked", "reason": "document revision mismatch",
 "expected_revision": "...", "document_revision": "...",
 "suggestion": "Re-read the document, ...", "next_tool": "get_document_info"}
```

이때는 문서를 **다시 읽고**(`get_document_map`/`get_document_info`) 외부 변경을 확인한 뒤
새 `document_revision`으로 재시도한다. `documentWarnings[]`에
`possible_document_lock`이 있으면 편집기에서 열려 있을 수 있으니 사용자에게 알린다.

### idempotency_key

`apply_edits`/`search_and_replace`/`batch_replace`는 `idempotency_key`를 받는다. 같은
key + 같은 인자로 재호출하면 도구를 다시 실행하지 않고 저장된 결과를 재생한다.
네트워크 재시도가 있는 자동화에서 중복 적용을 막을 때 부여한다.

### undo (`undo_last_edit`)

```
undo_last_edit(filename)
```

마지막 저장 직전에 만들어진 `.bak` 백업과 현재 파일을 교체한다(1단계 undo).
응답 키: `restored`, `backupPath`, `openSafety`, `verificationReport`, `semanticDiff`.
undo 후 `.bak`에는 직전 상태가 들어가므로 한 번 더 호출하면 redo처럼 동작한다.

## 2. 단건 편집·읽기 도구

루프를 돌 필요 없는 단건 작업은 전용 도구를 쓴다. 지원 인자와 응답 증거는 도구마다
다르므로 생성 계약의 해당 시그니처를 확인한다. `dry_run`, `expected_revision`,
`semanticDiff`, `verificationReport`, `document_revision`은 실제 스키마에 선언된 경우에만
요청하거나 성공 증거로 요구한다.

- 쓰기: `add_paragraph`, `add_heading`, `add_table`, `add_page_break`,
  `insert_paragraph`, `delete_paragraph`, `set_table_cell_text`,
  `search_and_replace`, `batch_replace`, `replace_in_paragraph`,
  `replace_by_anchor`, `fill_by_path`, `add_memo`, `add_memo_by_anchor`,
  `remove_memo`, `create_document`, `copy_document`
- 글자/표 서식: `format_text`(문단 내 구간 bold/italic/underline/font/size/color),
  `create_custom_style`, `list_styles`, `format_table`(머리행),
  `merge_table_cells`, `split_table_cell`
- 읽기: `get_document_map`(개요+표+양식 필드+앵커 통합), `get_document_info`,
  `get_document_text`, `get_document_outline`, `get_paragraph_text`,
  `get_paragraphs_text`, `get_location_text`, `get_table_text`, `get_table_map`,
  `find_text`, `find_cell_by_label`, `list_available_documents`,
  `hwpx_extract_json`(서식까지 필요하면 `format_detail=true`)

`get_document_map(filename, max_preview_chars=80)` 응답:
`info.{sections,paragraphs,tables}`, `outline`, `sections[]`, `tables`,
`formFields`, `anchors.{paragraphs,tables,figures}`, `document_revision`.
편집 전 한 번 호출하면 paragraph index·table index·앵커·필드를 한 번에 얻는다.

## 3. 서식 편집 5종 (인간 단위)

단위 정책: 글자 크기 **pt**, 줄간격 **%**, 들여쓰기 **mm**, 문단 간격 **pt**,
용지/여백 **mm**. HWP 내부 단위는 노출되지 않는다.

### 문단 서식 — `set_paragraph_format`

```
set_paragraph_format(filename, paragraph_index=None, paragraph_indexes=None,
    alignment=None, line_spacing_percent=None, indent_left_mm=None,
    indent_right_mm=None, first_line_indent_mm=None, spacing_before_pt=None,
    spacing_after_pt=None, outline_level=None, keep_with_next=None, keep_lines=None,
    page_break_before=None, dry_run=False, expected_revision=None)
```

"줄간격 160%로 바꿔줘" 예시:

```json
{"filename": "doc.hwpx", "paragraph_index": 3, "line_spacing_percent": 160}
```

여러 문단은 `paragraph_indexes=[2,3,4]`. 정렬은 `alignment="center"` 등.
응답의 `openSafety.ok == true`를 확인한다.

### 용지/여백 — `set_page_setup`

```
set_page_setup(filename, paper_size=None, width_mm=None, height_mm=None,
    orientation=None, margins_mm=None, margin_left_mm=None, margin_right_mm=None,
    margin_top_mm=None, margin_bottom_mm=None, header_margin_mm=None,
    footer_margin_mm=None, gutter_mm=None, columns=None, column_gap_mm=None,
    section_index=None, dry_run=False, expected_revision=None)
```

예: A4 가로 + 여백 `{"paper_size": "A4", "orientation": "landscape", "margin_left_mm": 20,
"margin_right_mm": 15, "margin_top_mm": 12, "margin_bottom_mm": 12}`.
응답 `pageSize.width/height`로 적용 결과를 확인한다.

### 머리글/바닥글 — `set_header_footer`

```
set_header_footer(filename, kind, text=None, content=None, section_index=None,
    page_type="BOTH", dry_run=False, expected_revision=None)
```

`kind`는 `"header"` 또는 `"footer"`. 단순 문자열은 `text`, 리치 런은 `content`
(paragraph spec 목록: `{"children": [{"type": "run", "text": ..., "bold": true},
{"type": "page_number", "format": "page"}]}`). 응답
`headerFooter.{kind,pageType,id,text,pageNumberCount}`를 확인한다.

### 쪽번호 — `set_page_number`

```
set_page_number(filename, target="footer", page_type="BOTH", format="page",
    align="CENTER", position="BOTTOM_CENTER", prefix="", suffix="",
    format_type=None, section_index=None, dry_run=False, expected_revision=None)
```

`format="page/total"`이면 `n / 전체` 필드 2개가 들어가 응답
`headerFooter.pageNumberCount == 2`가 된다.

### 목록 서식 — `set_list_format`

```
set_list_format(filename, paragraph_index=None, paragraph_indexes=None,
    kind="bullet", level=1, bullet_char=None, number_format=None, start=None,
    dry_run=False, expected_revision=None)
```

기존 문단에 불릿(`bullet_char="※"` 등) 또는 번호 목록(`kind="number"`,
`number_format`, `start`) 서식을 적용한다.

## 4. 그림 — `insert_picture` / `replace_picture`

```
insert_picture(filename, image_base64, image_format="png", width=None, height=None,
    width_mm=None, height_mm=None, section_index=None, align=None, output=None,
    dry_run=False, expected_revision=None)
```

본문에 그림 객체를 삽입하고 BinData/manifest 참조를 함께 기록한다. 크기는
`width_mm`/`height_mm` 권장. 응답: `picture.binaryItemIDRef`, `pictureReferences[]`,
`idIntegrity.ok`, `openSafety`.

```
replace_picture(filename, image_base64, image_format="png", picture_index=0,
    binary_item_id_ref=None, remove_orphaned=True, output=None,
    dry_run=False, expected_revision=None)
```

그림 객체의 **geometry(위치/크기)는 유지**하고 연결된 이미지 asset만 바꾼다.
응답 `replacement.{geometryPreserved, old_binaryItemIDRef, new_binaryItemIDRef,
removedOldImage}`와 `idIntegrity.ok`를 확인한다. 둘 다 `output`을 주면 원본 대신
별도 파일로 저장할 수 있다(원본 보존).

## 5. 충실도 민감 패치 — `byte_preserving_patch`

```
byte_preserving_patch(filename, patches, output=None)
```

section XML 바이트 splice로 문단 텍스트만 바꾼다. 문서 전체를 재직렬화하지 않으므로
서식·ID·레이아웃 충실도가 민감한 문서나 대형 문서의 소규모 텍스트 수정에 적합하다.
patch 항목: `{"sectionPath": "Contents/section0.xml", "paragraphIndex": N, "text": "새 텍스트"}`.

- 응답: `changedParts[]`, `byteIdentical`, `skipped[]`, `openSafety`, `verificationReport`.
- `skipped[]`가 비어 있지 않으면 해당 patch는 적용되지 않고 파일도 변경되지 않는다
  (예: `"line break insertion is unsupported"` — 줄바꿈 삽입은 미지원). 이때는
  `apply_edits`의 `replace_text`/`set_table_cell_text` 경로로 폴백한다.
- open-safety 검증을 통과한 경우에만 대상 파일이 교체된다.

## 6. 레이아웃 프리뷰 self-check — `render_preview`

레이아웃 민감 작업(표 폭, 페이지 나눔, 머리글/그림) 후에는 생성→프리뷰→수정 루프를 돈다.

1. `render_preview(filename, output_dir=..., mode="pages", screenshot="auto")` 실행.
2. `status`, `htmlPath`, `manifestPath`, `visualReviewPath`, `pages[].screenshotPath`,
   `screenshotEngine.backend` 확인.
3. `status == "ok"`이면 PNG에서 페이지 박스·여백·표 테두리·열너비·정렬·잘림을 확인하고,
   문제가 있으면 문서를 수정한 뒤 다시 실행한다.
4. `status == "blocked"`/`"partial"`이면 `htmlPath`를 열어 HTML 프리뷰로 확인하고, 필요하면
   Playwright browser 또는 Chrome(`HWPX_MCP_CHROME_PATH`)을 준비해 재실행한다.
5. `visualReviewPath`는 빠른 렌더 기반 `hwpx.visual-review.v1` evidence다. **최종 제출 가능
   주장에는 부족**하다 — 열린 문서 검토 요건은
   [`evidence-contract.md`](evidence-contract.md)를 따른다.

## 7. MCP가 없을 때 (local Python 대안)

- 동일 기능의 facade 메서드: `HwpxDocument.open(path)` 후 `doc.set_paragraph_format(...)`,
  `doc.set_page_setup(...)`, `doc.set_header_footer(...)`, `doc.set_page_number(...)`,
  `doc.set_list_format(...)`, `doc.add_picture(...)`, `doc.replace_picture(...)` →
  `doc.save_to_path(path)`. 시그니처는 [`api.md`](api.md).
- 런 수준 치환: `doc.replace_text_in_runs(...)`. 표 셀 포함 전역 치환:
  `python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "키=값" [--auto-fix-ns]`
  (open-safety 통과 시에만 대상 교체).
- ZIP-level 수정 후 네임스페이스 정리: `python3 scripts/fix_namespaces.py input.hwpx --inplace --backup`.
- 저장 후에는 항상 `validate_editor_open_safety(path).ok == True`를 확인한다.
