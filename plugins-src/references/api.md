# python-hwpx API 레퍼런스

`hwpx-plugins`에서 반복적으로 참조하는 `python-hwpx` API만 추렸다. 스킬 본문은 워크플로 중심이고, 이 문서는 시그니처와 사용 포인트를 빠르게 확인하는 용도다.

| python-hwpx 버전 | 상태 | 비고 |
|---|---|---|
| 2.9.1+ | ✅ 권장 | document-plan 생성 API 포함 로컬 스택 기준 |
| 2.6–2.9.0 | ✅ 기본 편집 호환 | `HwpxDocument` 기반 생성/편집 가능, document-plan API는 없을 수 있음 |
| 2.0–2.5 | ⚠️ 대부분 호환 | 일부 API 시그니처 차이 가능 |
| 1.x | ❌ 비호환 | HwpxDocument API 미지원 |

- import 이름: `hwpx`
- 로컬 실측 버전: `python-hwpx 2.9.1`

## 목차

- 설치와 기본 import
- `HwpxDocument`
- `TextExtractor`
- `ObjectFinder`
- `HwpxPackage`
- Document plan authoring
- Template form-fit authoring
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

## Document plan authoring

`hwpx.document_plan.v1`은 agent가 자연어 요청을 OWPML이 아닌 JSON 계획으로 정리한 뒤, `python-hwpx`가 공개 API만 사용해 HWPX를 생성하는 경로다.

```python
from hwpx import (
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

report = inspect_document_authoring_quality("agent-plan.hwpx", plan=document_plan)
assert report["pass"] is True
assert report["validation"]["validate_package"]["ok"] is True
assert report["validation"]["validate_document"]["ok"] is True
```

주요 함수:

- `validate_document_plan(plan) -> PlanValidationReport`
- `normalize_document_plan(plan) -> DocumentPlan`
- `create_document_from_plan(plan, *, preset="standard_korean_business") -> HwpxDocument`
- `inspect_document_authoring_quality(source, *, plan=None, quality_profile=None) -> dict`
- `inspect_operating_plan_quality(source, *, plan=None, profile=None) -> dict`

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
- `quality.profiles.operating_plan.pass == true`
- `visual_review_required == true`이면 최종 제출 전 렌더링 또는 사람의 시각 검토 필요

## Template form-fit authoring

`hwpx.template-formfit.baseline.v1`은 승인된 HWPX 양식을 보존하면서 특정
anchor 아래의 placeholder scaffold와 표 영역만 채우는 계약이다.

```python
from hwpx import analyze_template_formfit, apply_template_formfit

analysis = analyze_template_formfit(
    "template.hwpx",
    baseline="template-formfit-baseline.json",
    content={
        "school": {"name": "광교고등학교"},
        "sections": {
            "background_purpose": [
                "AI 융합형 교육실 구축으로 학생 맞춤형 탐구 수업을 확대한다.",
                "교원 공동 설계와 지역 연계를 통해 지속 가능한 운영 체계를 만든다.",
            ],
            "timeline": {
                "rows": [
                    {"월": "3월", "추진 내용": "운영 협의체 구성"},
                    {"월": "4월", "추진 내용": "공간 설계 및 기자재 선정"},
                ]
            },
        },
    },
    destination="filled.hwpx",
)
assert analysis["mutated"] is False
assert analysis["unresolved_count"] == 0

result = apply_template_formfit(analysis=analysis, confirm=True)
assert result["source"]["preserved"] is True
assert result["validation"]["validate_package"]["ok"] is True
assert result["validation"]["validate_document"]["ok"] is True
```

주요 함수:

- `analyze_template_formfit(source, *, baseline, content, destination=None, options=None) -> dict`
- `apply_template_formfit(*, analysis=None, source=None, baseline=None, content=None, destination=None, confirm=True) -> dict`

MCP 도구:

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
- `result.residual_markers.blocking == []`

제한:

- source와 destination이 같으면 apply는 거부된다.
- anchor가 없거나 둘 이상이면 apply 전 `unresolved`로 막는다.
- 이미지/평면도/픽셀 단위 레이아웃은 자동 보장하지 않는다.
- `visual_review_required=True`이면 최종 제출 전에 열린 문서 또는 사람의 시각 검토가 필요하다.

### Visual review evidence

운영 계획서 품질 검사 또는 template form-fit 결과에서 `visual_review_required=True`가
나오면, 파일 단위 검증만으로는 최종 제출 가능 상태를 주장하지 않는다.
ComputerUse 또는 사람이 HWPX viewer에서 문서를 연 뒤 `scripts/visual_review.py`로
`hwpx.visual-review.v1` evidence를 남긴다. `--viewer`는 `auto`, `none`,
`command:open` 같은 viewer 실행 방식이고, ComputerUse는 `--method computer-use`로
기록하는 관찰 방법이다.

viewer가 없는 CI/컨테이너에서는 blocked fallback을 기록한다.

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_fallback.json --viewer none --status blocked --notes "No HWPX viewer is available in this environment." --layout-risk "Rendered page breaks and table fit require opened-document review."
```

로컬 viewer 또는 ComputerUse로 확인한 경우:

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_pass.json --viewer auto --method computer-use --status observed_pass --screenshot examples/out/09_visual_review_page1.png --notes "Opened in local HWPX viewer. Tables fit, page breaks are acceptable, and no clipped placeholders were visible."
```

허용 상태는 `observed_pass`, `needs_review`, `blocked`뿐이다. 최종 제출 가능
시각 검토 주장은 `current.status == "observed_pass"`이고
`current.screenshot_path`가 있으며 `summary.ready_for_submission_claim == true`인
evidence에서만 허용한다. `observed_pass`에는 `--screenshot`이 필수이며,
`--observation`만으로는 최종 제출 가능 상태가 아니다.
`needs_review`는 재생성 또는 레이아웃 보완이 필요하고, `blocked`는 viewer가 없어
열린 문서 검토가 남았다는 뜻이다. 공통 handoff 경로는 `current.timestamp`,
`current.tool_path`, `current.screenshot_path`, `summary.ready_for_submission_claim`이며,
viewer unavailable/disabled/failure fallback에는 `current.fallback_reason`이 추가된다.

`iterations[]`는 같은 target checksum에 대해 같은 evidence 파일을 다시 쓸 때만
이전 `current`가 이동되어 누적된다. 재생성된 HWPX는 path 또는 checksum이 달라질 수
있으므로 새 evidence 파일을 쓰고 `--regenerated-from`에 이전 evidence 경로를 넣어
연결한다. 이 연결은 추적성만 제공하며, 이전 JSON을 새 evidence의 `iterations[]`로
병합하지 않는다.

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan_regenerated.hwpx --evidence examples/out/09_visual_review_pass_after_regen.json --viewer command:open --method computer-use --status observed_pass --screenshot examples/out/09_visual_review_regenerated_page3.png --notes "Regenerated from the overflow evidence. Budget table now fits on page 3." --regenerated-from examples/out/09_visual_review_needs_review.json
```

Evidence schema:

```json
{
  "schemaVersion": "hwpx.visual-review.v1",
  "target": {
    "path": "/Users/wilycastle/Code/projects/hwpx/hwpx-plugins/examples/out/07_operating_plan.hwpx",
    "name": "07_operating_plan.hwpx",
    "size_bytes": 123456,
    "mtime": "2026-05-30T12:00:00Z",
    "sha256": "hex-encoded-sha256"
  },
  "quality": {
    "available": true,
    "report_version": "operating-plan-quality-v1",
    "status": "ready",
    "score": 5.0,
    "pass": true,
    "gaps": [],
    "repair_hints": [],
    "visual_review_required": true
  },
  "viewer": {
    "mode": "auto",
    "available": true,
    "command": "open",
    "launched": false
  },
  "current": {
    "iteration": 2,
    "status": "observed_pass",
    "timestamp": "2026-05-30T12:00:00Z",
    "tool_path": "/Users/wilycastle/Code/projects/hwpx/hwpx-plugins/scripts/visual_review.py",
    "review_method": "computer-use-or-human-viewer",
    "screenshot_path": "/Users/wilycastle/Code/projects/hwpx/hwpx-plugins/examples/out/09_visual_review_page1.png",
    "observations": [
      "Tables fit, page breaks are acceptable, and no clipped placeholders were visible."
    ],
    "layout_risks": [],
    "notes": "Opened in local HWPX viewer.",
    "regenerated_from": ""
  },
  "iterations": [
    {
      "iteration": 1,
      "status": "blocked",
      "timestamp": "2026-05-30T11:50:00Z",
      "tool_path": "/Users/wilycastle/Code/projects/hwpx/hwpx-plugins/scripts/visual_review.py",
      "review_method": "computer-use-or-human-viewer",
      "screenshot_path": null,
      "observations": [],
      "layout_risks": ["Rendered page breaks and table fit require opened-document review."],
      "notes": "No HWPX viewer is available in this environment.",
      "regenerated_from": "",
      "fallback_reason": "viewer disabled by --viewer none"
    }
  ],
  "summary": {
    "resolved_visual_review_required": "observed_pass",
    "ready_for_submission_claim": true,
    "residual_layout_risk_count": 0
  }
}
```

## Multi-host plugin bundles

`plugins/<host>/` holds generated, committed bundles for Claude Code, Codex, OpenClaw, and
Hermes Agent, built from the repo-root skill assets by `scripts/build_hwpx_plugins.py` and
checked by `scripts/validate_hwpx_plugin.py`.

The bundled MCP launcher (`scripts/hwpx-mcp-server` in Claude/Codex bundles) resolves, in order:

1. `HWPX_MCP_SERVER_REPO` / `PYTHON_HWPX_REPO` env overrides
2. a stack root discovered by walking up to sibling `hwpx-mcp-server` and `python-hwpx` checkouts
3. `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server`

Run `python3 scripts/build_hwpx_plugins.py` after changing `SKILL.md`, `references`, `examples`,
or skill scripts, then `python3 scripts/validate_hwpx_plugin.py`.

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
