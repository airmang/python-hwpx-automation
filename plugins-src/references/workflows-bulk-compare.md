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
- **fit 정책 선택(두뇌=이 판단)**: 값이 셀에 확실히 들어가면 `keep`. 좁은 칸에 이름·부서
  등 한 줄 값이면 `shrink`(글꼴만 줄여 한 줄 유지). 여러 줄이 허용되는 넓은 칸이면
  `wrap_then_shrink`(먼저 감고, 그래도 넘치면 축소). 행이 늘어도 되는 자유 서술 칸에서만
  `expand_row`. **핵심 원칙**: fit은 이제 셀의 **가로·세로 예산을 모두** 재므로, 최소 글꼴
  (기본 8pt)로도 세로 예산을 못 맞추는 과대 입력은 `overflow="fail"`에서 **typed 거부**로
  돌아온다 — 조용히 행을 키워 페이지를 밀지 않는다. 거부가 오면 값을 줄이거나 칸/정책을
  바꾼다(무음 서식 파괴보다 정직한 거부가 낫다).
- **한계 정직 고지(S-087 실측 갱신)**: 무음 서식파괴의 지배 원인은 **체크박스 등 인라인
  컨트롤이 동거하는 셀**에 값을 넣을 때 폭이 모자라 줄바꿈→행 성장→페이지 연쇄가 나는
  것이었고, 이제 엔진이 컨트롤 폭을 차감해 그런 채움을 **typed 거부**한다(컨트롤 동거
  경고 동반). 거부가 오면 값을 줄이지 말고 **의도된 값 칸을 다시 찾는 것**이 보통 정답이다
  (체크박스 칸은 채움 대상이 아니다). 잔여 리스크: 엔진이 fits로 판정해도 다중 페이지
  양식은 미세한 행 성장이 페이지 경계를 넘길 수 있다(실측 잔여 11/66) — **다중 페이지
  양식 채움은 render-gate(verify_fill/실한컴 렌더)로 전 페이지 검토**하고, 페이지 수
  증가·표 형태 변화가 보이면 `needs_review`로 남긴다.
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

## 3. 문서 비교 — `doc_diff` / 신구대조표 document plan

두 문서(또는 문단 목록)의 신구 비교 요청:

```
doc_diff(old_filename=..., new_filename=...)            # 또는
doc_diff(old_paragraphs=[...], new_paragraphs=[...])
```

LCS 기반 paragraph diff를 반환한다. `summary.counts.{changed, added, ...}`로 변경 규모를
파악한다.

"신구대조표 만들어줘"는 diff 결과를 좌우 대조표 block으로 정규화한 뒤 canonical
document plan으로 생성한다:

```
doc_diff(old_filename=..., new_filename=...)
validate_document_plan(document_plan={... comparison table rows ...})
create_document_from_plan(filename, document_plan)
```

- 변경된 행만 필요하면 diff의 equal 항목을 제외하고 plan을 만든다.
- `validate_document_plan.ok == true`와 생성 응답의 도구별 verification receipt를 확인한다.
- 행정문서 표 스타일이 필요하면 plan에 `government_report` preset을 명시한다.
- `create_comparison_table_document`는 기존 direct-create 호출을 위한 compatibility facade다.

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
