---
name: hwpx
description: "한글 문서(.hwpx/OWPML) 편집·추출·자동화 스킬. '한글 문서 편집해줘', 가정통신문·공문·한글 양식 작성, HWPX 편집, 한글 파일/OWPML 분석, 플레이스홀더 치환, 문서 자동화 요청이면 이 스킬을 반드시 사용하세요."
---

# hwpx (HWPX / OWPML)

`.hwpx`는 ZIP 기반 OWPML 문서다. 기본 생성·편집은 `python-hwpx`로 처리하고, 표를 포함한 전역 치환이나 ZIP 레벨 후처리는 번들 스크립트로 처리한다.

- 기준 라이브러리: `python-hwpx` (import: `hwpx`)
- 기본 편집 최소 호환 기준: `python-hwpx >= 2.6`
- document-plan 생성 권장 기준: `python-hwpx >= 2.9.1` 로컬 스택
- 최근 로컬 검증 버전: `python-hwpx 2.9.1`
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

3. **운영 계획서를 작성한다**
   먼저 요청을 `hwpx.document_plan.v1` JSON으로 정규화하고, `quality_profile="operating_plan"`을 켠다. MCP 서버가 연결되어 있으면 `validate_document_plan` → `analyze_document_plan` → `create_document_from_plan` → `inspect_document_authoring_quality` 순서로 간다. MCP가 없으면 `python-hwpx`의 `validate_document_plan()`, `create_document_from_plan()`, `inspect_document_authoring_quality(..., quality_profile="operating_plan")`, `inspect_operating_plan_quality()`를 직접 사용한다. 예시는 [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py)와 [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md)를 본다.

4. **승인된 양식을 보존하며 운영 계획서를 채운다**
   사용자가 특정 HWPX 양식이나 P6 기준선 기반 운영 계획서 작성을 요청하면 document-plan 새 문서 생성보다 template form-fit 경로를 우선한다. MCP 서버가 있으면 `analyze_template_formfit`으로 원본이 변하지 않았고 `unresolved_count == 0`인지 확인한 뒤, `apply_template_formfit(confirm=True)`로 원본과 다른 destination에만 적용한다. 결과에서 `source.preserved`, `validation.validate_package.ok`, `validation.validate_document.ok`, `residual_markers.blocking == []`를 확인한다. `visual_review_required=True`이면 최종 제출 전 열린 문서/사람 검토가 필요하다고 명시한다. 예시는 [`examples/08_template_formfit.py`](examples/08_template_formfit.py)와 [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md)를 본다.

5. **자연어 요청으로 새 문서를 완성한다**
   먼저 요청을 `hwpx.document_plan.v1` JSON으로 정규화한다. MCP 서버가 연결되어 있으면 `validate_document_plan` → `create_document_from_plan` → `inspect_document_authoring_quality` 순서로 간다. MCP가 없으면 `python-hwpx`의 `create_document_from_plan()`을 직접 사용한다. 예시는 [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)를 본다.

6. **문서 구조를 조사한다**
   텍스트 노드, 표 개수, 특정 OWPML 태그 분포를 확인할 때는 `ObjectFinder`를 사용한다. 예시는 [`examples/02_extract_and_inspect.py`](examples/02_extract_and_inspect.py)를 본다.

7. **플레이스홀더를 일괄 치환한다**
   표 셀까지 포함한 전역 치환이면 `python3 scripts/zip_replace_all.py input.hwpx output.hwpx --replace "{기관명}=OO구청" "{담당자}=홍길동"`을 사용한다. 치환 직후 네임스페이스 정리까지 하려면 `--auto-fix-ns`를 붙인다.

8. **ZIP-level 수정 후 네임스페이스만 다시 정리한다**
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

### 1-1) 선언형 document-plan 기반 새 문서 생성

사용자가 "회의록/운영계획서/가정통신문/보고서 초안을 HWPX로 만들어줘"처럼 새 문서 생성을 요청하면, 바로 저수준 XML을 만들지 말고 `hwpx.document_plan.v1`을 먼저 작성한다.

1. 제목, 메타데이터, heading, paragraph, bullets, table block으로 계획을 정규화한다.
2. MCP 서버가 있으면 `validate_document_plan(document_plan)`으로 비파괴 검증을 먼저 수행한다.
3. `ok=false`이면 `issues[].code`, `issues[].path`, `repairHints[]`를 읽고 plan을 수정한 뒤 `validate_document_plan`을 다시 실행한다. `can_create=false` 상태에서는 생성하지 않는다.
4. 검증이 통과하면 `create_document_from_plan(filename, document_plan)`으로 HWPX를 생성한다.
5. 반환된 `quality.validation.reopened`, `validate_package.ok`, `validate_document.ok`, `visual_review_required`를 확인한다.
6. MCP가 없으면 local Python에서 `create_document_from_plan()`과 `inspect_document_authoring_quality()`를 사용한다.

관련 예제:
- [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)
- [`examples/06_mcp_document_plan.md`](examples/06_mcp_document_plan.md)
- 검증: `python3 scripts/quickcheck.py --document-plan`

주의:
- v1은 headings, paragraphs, bullets, tables, page break 중심이다.
- 깨진 table은 `columns[].key`와 `rows[]`의 key를 먼저 맞춘다. 누락된 row key는 빈 셀로 생성되지만, 의도한 데이터라면 plan에서 보강한다.
- `unknown_style_token` 같은 style warning은 지원 token(`body`, `title`, `subtitle`, `heading`, `bullet`, `table_header`, `table_cell`)으로 바꾸거나 style을 생략한다.
- `validate_package.ok=false` 또는 `validate_document.ok=false`이면 `validation.*.issues[]`와 `recovery.repair_hints[]`를 확인하고 재저장/재생성한 뒤 다시 검사한다. 이 상태의 파일은 handoff하지 않는다.
- binary `.hwp`, 임의 OWPML 삽입, 복잡한 레이아웃 재현은 범위 밖이다.
- `visual_review_required=True`는 구조 검증은 통과했지만 렌더러/픽셀 검수는 하지 않았다는 뜻이다.

### 1-2) 운영 계획서 제출 후보 작성

사용자가 “운영 계획서”, “사업 운영 계획”, “학교 운영 계획”, “AI 중점학교 운영계획서”처럼 제출 가능한 계획서 작성을 요청하면 generic document-plan보다 운영 계획서 프로필을 우선한다.

1. 사용자 요청을 `hwpx.document_plan.v1`로 정규화한다.
2. 필수 구조를 포함한다: 신청 목적, 운영 계획, 추진 일정, 사업비/자원 사용 계획, 교육과정 또는 운영 체계, 기대 효과/성과 관리, 제출/확인 마감 문구.
3. 표는 최소 2개를 권장한다: `추진 일정`, `사업비 사용 계획`.
4. placeholder, `TODO`, `작성 필요`, `□□□□`, `○○` 같은 drafting marker를 남기지 않는다.
5. MCP가 있으면:
   - `validate_document_plan(document_plan)`
   - `analyze_document_plan(document_plan, quality_profile="operating_plan")`
   - `create_document_from_plan(filename, document_plan, quality_profile="operating_plan")`
   - `get_document_text(filename)` 및 `get_table_text(filename, table_index)`로 readback
6. MCP가 없으면:
   - `validate_document_plan(plan)`
   - `create_document_from_plan(plan)`
   - `inspect_document_authoring_quality(path, plan=plan, quality_profile="operating_plan")`
   - `inspect_operating_plan_quality(path, plan=plan)`
7. handoff 전 evidence를 확인한다:
   - `plan_validation.ok == true`
   - `quality.validation.reopened == true`
   - `quality.validation.validate_package.ok == true`
   - `quality.validation.validate_document.ok == true`
   - file-only `inspect_operating_plan_quality(path).report_version == "operating-plan-quality-v1"`
   - file-only `inspect_operating_plan_quality(path).status == "ready"`
   - `visual_review_required == true`이면 최종 제출 전 별도 시각 검토가 필요하다고 명시
8. `status="needs_revision"` 또는 `gaps[]`가 있으면 `repair_hints[]`를 반영해 plan을 보강하고 다시 검증한다.

예제:
- [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py)
- [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md)

검증:
- `python3 scripts/quickcheck.py --operating-plan`

### 1-3) P6 기준선 기반 양식 보존 form-fit

사용자가 승인된 AI 융합형 교육실 운영계획서 양식, P6 baseline, 또는 “기존 양식 그대로 채워줘”라고 요청하면 원본 양식을 직접 수정하지 않는다.

1. 기준선 JSON과 구조화된 content를 준비한다.
2. MCP 서버가 있으면 `analyze_template_formfit(source_filename, baseline, content, destination_filename)`을 먼저 호출한다.
3. `mutated=false`, `source.unchanged_after_analysis=true`, `unresolved_count=0`이 아니면 apply하지 않는다.
4. `apply_template_formfit(analysis=..., confirm=true)`를 호출한다.
5. handoff 전 evidence를 확인한다:
   - `handoff_status == "ready"`
   - `source.preserved == true`
   - `validation.validate_package.ok == true`
   - `validation.validate_document.ok == true`
   - `residual_markers.blocking == []`
   - file-only `inspect_operating_plan_quality(destination).status == "ready"` 또는 남은 gap이 제출 전 수동 보완 가능하다는 근거
6. `visual_review_required=true`이면 렌더링/열람/사람 검토를 최종 제출 전 별도 gate로 남긴다.

예제:
- [`examples/08_template_formfit.py`](examples/08_template_formfit.py)
- [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md)

검증:
- `python3 scripts/quickcheck.py --template-formfit`

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

- [`examples/06_create_from_document_plan.py`](examples/06_create_from_document_plan.py)
  `hwpx.document_plan.v1` JSON에서 검증 가능한 HWPX를 생성하는 예제.

- [`examples/07_create_operating_plan.py`](examples/07_create_operating_plan.py)
  운영 계획서 `document_plan`을 생성하고 `operating_plan` 품질 프로필까지 확인하는 예제.

- [`examples/07_mcp_operating_plan.md`](examples/07_mcp_operating_plan.md)
  MCP 서버에서 운영 계획서를 검증, 분석, 생성, 품질 확인하는 호출 흐름.

- [`examples/08_template_formfit.py`](examples/08_template_formfit.py)
  baseline 기반 양식 보존 생성 local 예제.

- [`examples/08_mcp_template_formfit.md`](examples/08_mcp_template_formfit.md)
  MCP 서버에서 `analyze_template_formfit` → `apply_template_formfit`로 원본을 보존하며 채우는 호출 흐름.

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

## 양식 + 아이디어 기반 고품질 생성 workflow

사용자가 양식 HWPX와 대략적인 아이디어만 주고 “완성도 있게 작성해줘”라고 요청하면, 목표 품질 샘플을 매번 요구하지 않는다. 우선 `hwpx-mcp-server`의 MCP 품질 파이프라인을 사용한다.

1. 양식 파일을 `form_filename`으로 지정하고 사용자 요청을 `idea_brief` 또는 구조화된 content spec으로 정리한다.
2. `analyze_quality_generation(form_filename, idea_brief, destination_filename)`을 먼저 호출한다. 이 단계는 원본 양식을 변경하지 않고, 내장 품질 프로필과 생성 계획을 반환한다.
3. 분석 결과가 적절하면 `apply_quality_generation(analysis=..., confirm=True)`를 호출한다.
4. 결과의 `validation`과 `quality.gaps`, `revision_history`를 확인한다. 품질이 부족하면 같은 파이프라인으로 보강된 브리프나 수정 계획을 적용해 다시 생성한다.
5. 이 workflow의 일반 입력은 **양식 + 아이디어**다. 좋은 품질 샘플은 캘리브레이션/평가용으로만 쓰며 매번 필요한 입력으로 취급하지 않는다.

예시 MCP 호출 개념:

```json
{
  "form_filename": "inputs/form-template.hwpx",
  "idea_brief": "초등학생 AI 기초 소양과 교원 AI 수업 설계 역량을 강화하는 2026년 AI 중점학교 운영계획서를 작성한다.",
  "destination_filename": "outputs/ai-school-plan.hwpx"
}
```
