# 대량생산·계산·비교·생성기 워크플로

메일머지, 표 계산, 문서 비교/신구대조표, 고급 생성기 3종, 스타일 프로파일/템플릿
레지스트리의 상세 계약.

## 1. 메일머지 대량생산 — `mail_merge`

템플릿 HWPX 1개에 `{{student}}`, `${teacher}`, `<<class_name>>` 같은 placeholder가 있고
CSV/JSON/**XLSX(명부)**/행 데이터로 학생별 가정통신문, 상장, 수료증, 안내장처럼 N부를
만들 때는 반복 치환 대신 `mail_merge`를 사용한다. placeholder는 본문뿐 아니라 **표 셀**
(발신·결재/안내 박스) 안에 있어도 치환된다.

```
mail_merge(template_filename, data_rows=...|data_filename=..., output_dir=...,
    filename_pattern="{index:03d}-{student}.hwpx", zip_filename=...,
    fit_mode="keep", max_lines=1)
```

- 사전 점검: `inspect_mail_merge_placeholders(filename)`로 placeholder key를 확인한다.
- 확인할 응답 키: `createdCount`, `rowCount`, `rowsWithIssues`, `rows[].missingKeys`,
  `rows[].unresolvedPlaceholders`, `rows[].openSafety.ok`,
  `verification.openSafety.checkedCount`, `zip.entryCount`.
- 기본 `strict=false`: 결측이 있어도 산출물을 만들고 row report에 남긴다. 결측 행 생성을
  막으려면 `strict=true`.
- **fit-aware 배치 (`fit_mode` 지정)**: 좁은 셀에 긴 값이 들어가 넘치는지 템플릿에서 한 번
  측정해(template-once-measure) 레코드별로 격리한다. `fitAware=true`, `needsReview[]`
  (넘침·결측 등 생성됐지만 검토 필요), `skipped[]`(strict에서 결측으로 미생성)를 확인하고,
  `needsReview[].reasons`(`overflow`/`missing_required`/…)로 후속 조치한다. `fit_mode`는
  keep(값 보존+넘침만 보고)·shrink(글꼴 축소)·wrap_then_shrink 등. 넘치는 행을 자동으로
  잘라내지 않으므로 값 단축이나 `fit_mode="shrink"`로 재시도한다.
- 한 행이라도 결측 placeholder가 있으면 `ok=false`일 수 있지만 산출물의 openSafety는
  별도로 확인한다.

예제: `python3 examples/14_mail_merge_table_compute.py`.

## 2. 일반 표 계산 — `table_compute`

표의 합계·평균·소계 행/열 요청은 수동 계산 대신 `table_compute`를 사용하고
`evidence[]`를 근거로 남긴다.

```
table_compute(table, value_columns=[...], operations=["subtotal", "sum", "average"],
    group_by=..., label_column=..., append="rows|columns|both", labels=...)
```

- 입력: plan v2 table(`header`/`rows`), plan v1 table(`columns`/`rows`), list-of-dicts.
- `value_columns` 생략 시 숫자 열 자동 탐지.
- 응답 `computedTable`은 document-plan table block으로 재사용 가능. `evidence[]`에는
  operation, axis, sourceRowCount/sourceValueCount, result가 들어간다.

## 3. 문서 비교 — `doc_diff` / 신구대조표 — `create_comparison_table_document`

두 문서(또는 문단 목록)의 신구 비교 요청:

```
doc_diff(old_filename=..., new_filename=...)            # 또는
doc_diff(old_paragraphs=[...], new_paragraphs=[...])
```

LCS 기반 paragraph diff를 반환한다. `summary.counts.{changed, added, ...}`로 변경 규모를
파악한다.

"신구대조표 만들어줘"는 diff 결과를 좌우 대조표 HWPX로 바로 생성한다:

```
create_comparison_table_document(filename, old_filename=.../new_filename=... |
    old_paragraphs=.../new_paragraphs=..., title="신구대조표", include_equal=True,
    verbosity="compact")
```

- `include_equal=false`이면 변경된 행만 표에 남긴다.
- 응답 키: `created`, `document_plan`, `plan_validation`, `verification.openSafety.ok`.
  `created=false`이면 `plan_validation`을 읽고 입력을 보정한다.
- 생성 preset은 `government_report`라서 행정문서 표 스타일이 적용된다.

## 4. 고급 생성기 3종 (block + document_plan 반환)

세 도구 모두 문서를 직접 만들지 않고 plan v2 block과 생성 가능한 `document_plan`을
반환한다. 응답의 `next_tool == "create_document_from_plan"`을 따라
`create_document_from_plan(filename, document_plan)`으로 마무리한다.

### 사진대지 — `build_image_grid`

```
build_image_grid(images, columns=2, image_width_mm=None, title="사진대지")
```

`images`는 `[{"path": "...", "caption": "현장 사진"}]` 목록. `image_grid` block과
document_plan을 반환한다.

### 회의 명패 — `build_meeting_nameplates`

```
build_meeting_nameplates(names, size="150x70", columns=2, title="회의 명패")
```

참석자 명단을 명패 table block으로 변환한다 (`block.rows`가 columns 단위로 배치된다).

### 조직도 — `build_organization_chart`

```
build_organization_chart(hierarchy, max_depth=3, title="조직도")
```

`hierarchy`는 `{"name": "위원장", "children": [{"name": "기획팀", "children": [...]}]}`
형태의 2~3단 계층. 표 기반 조직도 block으로 변환한다.

## 5. 참조 문서 서식 이식·스타일 프로파일

"이 문서 서식대로", "참조 파일과 같은 양식으로" 요청:

1. `extract_style_profile(filename)` — 페이지 크기·여백·폰트·표 열너비 프로파일 추출.
2. `apply_style_profile_to_plan(document_plan, style_profile=...)`로 새 plan에 적용.
3. `create_document_from_plan`으로 생성.
4. `compare_style_profiles(reference_filename=..., candidate_filename=...)`의 `pass=true`와
   `verification.openSafety.ok=true`를 evidence로 남긴다.

문서 구조를 서식까지 읽어야 할 때만 `hwpx_extract_json(..., format_detail=true)`를
사용한다. 기본 `format_detail=false`는 토큰 절약용이다.

## 6. 템플릿 레지스트리

반복 사용할 양식은 등록해 둔다:

- `register_template(name, source_filename, registry_path=...)` — 등록.
- `list_templates(registry_path=...)` — 목록.
- `describe_template(name, values=...)` — style profile과 placeholder 미충전 리포트.
  `placeholderReport.missingKeys`가 비어 있지 않으면 채우기 전에 값을 보강한다.

## 7. 정합성 lint — `inspect_reference_consistency`

붙임 참조(`붙임 2 참조` vs 실제 붙임 목록)와 표/그림 번호 연속성을 의미 수준에서
검사한다. 입력은 `filename`, `paragraphs`, `document_plan` 중 하나.
응답 `pass`, `violations[].rule`(`attachment-reference`, `table-numbering` 등)을 확인하고
위반을 고친 뒤 재검사한다.
