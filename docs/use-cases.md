# 🔧 python-hwpx-automation — 이런 것도 가능합니다

> Python 자동화와 선택 MCP 어댑터로 여는 한글(HWPX) 문서 워크플로
>
> 릴리스 상태: `released` (2026-08-03) — 현재 공개 트레인은
> `python-hwpx 5.6.0 → python-hwpx-automation 6.6.4 → hwpx-plugin 1.6.0`입니다.

---

## python-hwpx-automation이란?

`python-hwpx-automation`은 `python-hwpx` 위에서 한글 문서(`.hwpx`)를
읽고, 쓰고, 편집하는 고수준 Python 자동화 제품입니다. AI 어시스턴트 연결은
기본 제품과 분리된 선택 MCP 어댑터입니다.

기존에는 한글 파일을 열어서 일일이 수작업으로 처리해야 했던 일을, 이제 자연어 요청으로 자동화할 수 있습니다.

이 문서는 공개 릴리스 `python-hwpx-automation 6.7.1` 기준입니다. 공개
트레인은 `python-hwpx 5.7.0 → python-hwpx-automation 6.7.1 →
hwpx-plugin 1.7.0`, 계약 해시는 `98510af22d13899c`입니다.

6.7.1 릴리스의 기본 모드 128개(고급 모드 포함 총 136개)의 도구로 문서 생성,
선언형 document-plan 생성, 선언적 편집 계획 실행(`run_edit_plan` —
다단 편집을 all-or-nothing 원자 실행), 누름틀 필드 저작(`add_form_field`),
네이티브 수식 저작(`add_equation`, LaTeX→EqEdit), 네이티브 차트 생성
(`add_chart`, 데이터→chartML, 막대·꺾은선·원), 운영 계획서 품질 프로필,
검색, 치환, 표 편집, 서식 적용(표 테두리 선 종류·색·굵기와 셀 음영을
`format_table`로), HWPX repair/recover까지 처리할 수 있습니다.

document-plan, form-fill, visual-review handoff 워크플로의 문서화·테스트
기준 upstream 버전 바닥은 `python-hwpx >= 5.7.0`입니다. 설치 계약은 기본
128개/고급 136개/스킬 필수 28개이며, automation 바닥은 `6.5.0`, skill
바닥은 `1.6.0`입니다.
호환·deprecated 도구는
2026-10-31까지 모두 유지하며, 신규 호출의 canonical 경로와 rollback은
[compatibility observation](compatibility-observation.md)을 따릅니다.

선언형 document-plan 생성은 `validate_document_plan`으로 먼저 검증합니다.
`ok=false`이면 `issues[].path`와 `repairHints[]`를 따라 JSON plan을 고친 뒤
다시 검증하고, `can_create=false` 상태에서는 파일 생성을 진행하지 않습니다.
생성 전에는 `analyze_document_plan(..., quality_profile="operating_plan")`으로
파일을 쓰지 않고 품질 preview를 확인할 수 있습니다. 생성 후에는
`inspect_document_authoring_quality`의 package/schema issue와
`quality.profiles.operating_plan.gaps[]`, `repair_hints[]`를 확인합니다.

승인된 HWPX 양식을 보존해야 할 때는 `analyze_form_fill(plan=...)` →
`apply_form_fill(plan=...)` → `verify_form_fill(plan=...)`의 canonical mixed-form
흐름을 사용합니다. 분석 단계는 원본을 변경하지 않으며, 적용 단계는 원본과 다른
destination에 한 번만 commit합니다. unified receipt의 rollback/idempotency,
byte-preservation, reopen, privacy, openSafety와 요구된 실제 렌더 증거를 handoff에서
확인합니다. template-formfit 쌍은 기존 자동화를 위한 호환 경로입니다.

본문·표 셀·기존 구역의 단순 `BOTH` 머리글을 함께 바꿀 때는 한 번의
`apply_document_commands` 호출에 각 canonical path command를 순서대로 넣습니다.
서버는 하나의 revision과 직렬화에 묶어 적용하며, 어느 command든 실패하면 부분
출력을 남기지 않습니다. rich/control 머리글은 구조 손실을 피하기 위해 fail-closed로
거부합니다.

한컴에서 열리지 않거나 ZIP 오류가 의심되는 HWPX는 원본을 덮어쓰지 않고
`repair_hwpx`로 새 복구 복사본을 만듭니다. central directory 손상처럼 일반
ZIP open이 실패하면 `recover=true`를 사용하고, `crcOk`,
`validatePackage.ok`, `reordered`, `recovered`를 증거로 확인합니다.

---

## 활용 사례 쇼케이스

### 📋 사례 1: 긴 문서를 자동으로 요약하기

**상황**: 105개 문단에 17개 표가 담긴 학교 운영계획서. 전체를 읽기엔 시간이 부족하고, 핵심만 빠르게 파악하고 싶다.

**AI에게 이렇게 요청하세요**:
> "이 운영계획서에서 핵심 내용만 뽑아서 요약 문서를 새로 만들어줘."

**결과**: AI가 원본 구조를 분석하고, 주요 섹션 핵심을 추출해 제목·본문·요약 표가 포함된 요약 문서를 자동 생성합니다.

**활용 분야**:
- 학교 운영계획, 사업보고서 등 장문 문서의 경영진/관리자용 요약본 작성
- 학부모 배포용 축약 안내문 자동 생성
- 회의 전 빠른 문서 브리핑 자료 준비

---

### 🔄 사례 2: 인사이동·조직개편 일괄 반영

**상황**: 새 학기 조직 개편으로 "교육정보부장"이 "디지털혁신부장"으로, "정보교사"가 "에듀테크교사"로 변경되었다. 수십 페이지에 흩어진 직위명을 하나씩 바꾸는 것은 고된 작업.

**AI에게 이렇게 요청하세요**:
> "이 문서에서 교육정보부장→디지털혁신부장, 정보교사→에듀테크교사, 실무사→행정지원관으로 전부 바꿔줘."

**결과**: 19건의 직위명이 한 번의 요청으로 일괄 변경되고, 잔존 여부까지 자동 검증합니다.

**활용 분야**:
- 매년 반복되는 조직도·직위 변경 반영
- 법령 용어 변경에 따른 공문서 일괄 수정
- 학교명·기관명 변경 시 관련 문서 전체 업데이트

---

### 🔁 사례 3: 치환 후 원본 복원 — 왕복 무결성 보장

**상황**: 문서를 영문 버전으로 변환했다가 다시 원래 한글로 되돌리고 싶다. 치환 과정에서 내용 손상이 우려된다.

**AI에게 이렇게 요청하세요**:
> "NEIS를 나이스시스템으로 바꿔줘. 그 다음에 다시 NEIS로 되돌려줘. 원래대로 돌아오는지 확인해봐."

**결과**: 4건 용어를 바꿨다가 되돌려도 오차 없이 복원되며, split-run 환경에서도 정확히 작동합니다.

**활용 분야**:
- 문서 번역 후 원본 복구가 필요한 경우
- 임시 용어 변경 후 원상복구
- 치환 작업 안전성 사전 검증

---

### 📊 사례 4: 문서 속 모든 표를 한눈에 — 데이터 마이닝

**상황**: 수십 페이지 문서에 표가 17개 있다. 표 위치와 데이터 성격을 빠르게 파악하고 싶다.

**AI에게 이렇게 요청하세요**:
> "이 문서에 있는 표를 전부 읽어서 어떤 내용인지 정리해줘."

**결과**: 17개 표를 전수 분석해 표 크기(행×열), 위치, 용도(제목용/데이터용) 카탈로그를 자동 생성합니다. 44행짜리 대형 표도 처리합니다.

**활용 분야**:
- 예산서·결산서 표 데이터 추출/분석
- 여러 문서에 흩어진 표 데이터 통합
- 문서 내 데이터 현황 사전 조사

---

### 📐 사례 5: 문서 구조를 자유자재로 재편

**상황**: 결론을 앞으로 옮기고, 불필요한 부록을 삭제하고, 맨 앞에 요약 문단을 추가하고 싶다.

**AI에게 이렇게 요청하세요**:
> "이 문서의 결론 부분을 본론 앞으로 옮기고, 부록은 삭제하고, 맨 앞에 요약 문단을 하나 넣어줘."

**결과**: 문단 삽입·삭제·이동을 조합해 문서 구조를 재구성합니다. 인덱스 계산도 자동 처리합니다.

**활용 분야**:
- 보고서 구조를 독자 맞춤형으로 재편 (경영진용 vs 실무자용)
- 제안서 섹션 순서 최적화
- 기존 문서를 재활용한 신규 문서 제작

---

### 📝 사례 6: 빈 문서에서 양식을 자동 생성

**상황**: 회의록, 업무일지, 점검표 같은 반복 양식 문서를 매번 처음부터 만들기 번거롭다.

**AI에게 이렇게 요청하세요**:
> "회의록 양식을 만들어줘. 기본정보 표, 안건 목록 표, 후속조치 표, 서명란까지 포함해서."

**결과**: 빈 HWPX에서 시작해 제목(3단계 헤딩), 4개 표(기본정보·안건·후속조치·서명란), 안내 문구를 포함한 양식을 자동 생성합니다.

**활용 분야**:
- 회의록, 업무일지, 출장보고서 등 정형 양식 자동 생성
- 부서별 양식 커스터마이징
- 신규 프로젝트 문서 템플릿 일괄 생성

---

### 🌐 사례 7: 한국어↔영어 용어 자유 전환

**상황**: 해외 교류/글로벌 보고를 위해 핵심 용어를 영문화하거나 역변환해야 한다.

**AI에게 이렇게 요청하세요**:
> "교육정보부는 Edu-IT Dept로, 홈페이지는 Website로 바꿔줘. 나중에 다시 한글로 되돌릴 수도 있어야 해."

**결과**: 한→영, 영→한 양방향 치환이 정확히 동작하며, 유니코드 혼합 환경에서도 손상 없이 복원됩니다.

**활용 분야**:
- 국제 교류 문서 핵심 용어 영문화
- 외국어 원문의 한글 용어 대체(현지화)
- 다국어 보고서 용어 일관성 유지

---

### 🧩 사례 8: 복잡한 표 — 셀 병합부터 서식까지 한번에

**상황**: 셀 병합과 서식이 포함된 복잡한 표를 빠르게 생성해야 한다.

**AI에게 이렇게 요청하세요**:
> "6행 5열 표를 만들고, 첫 번째 행은 제목으로 병합하고, 왼쪽 열은 카테고리별로 묶어줘. 헤더에 서식도 적용해줘."

**결과**: 표 생성 → 행/열/블록 병합 → 데이터 입력 → 헤더 서식 적용까지 전체 파이프라인을 한 흐름으로 처리합니다.

**활용 분야**:
- 성적표, 시간표, 예산 배분표 제작
- 비교 분석표 자동 생성
- 보고서용 서식 테이블 제작

---

### 🏋️ 사례 9: 대량 작업도 거뜬하게 — 50개 문단, 50건 치환

**상황**: 대량 문서 생성/치환을 빠르고 안전하게 수행해야 한다.

**AI에게 이렇게 요청하세요**:
> "50개 문단을 추가하고, 그 안에 있는 영문 키워드 4종류를 전부 한글로 바꿔줘. 빠진 거 없는지 확인도 해줘."

**결과**: 50개 문단 추가와 50건 치환을 누락 없이 처리하고, 치환 전후 카운트까지 자동 검증합니다.

**활용 분야**:
- 대량 공문서 생성(안내장, 통지서 등)
- 장문 문서의 용어 통일
- 반복 대량 데이터 문서 자동화

---

## 지원 도구 한눈에 보기

| 카테고리 | 도구 | 설명 |
|---|---|---|
| **문서** | 생성, 복사, 정보조회 | 새 문서 만들기, 복사, 통계 확인 |
| **읽기** | 전문, 문단, 범위, 구조 | 전체 텍스트부터 특정 문단까지 유연한 읽기 |
| **검색** | 텍스트 검색 | 키워드 위치·빈도 탐색 |
| **치환** | 단일 치환, 일괄 치환 | 하나씩 또는 여러 개 동시 변경 |
| **편집** | 문단 추가, 삽입, 삭제, 제목 | 원하는 위치에 내용 추가·제거·이동 |
| **표** | 생성, 읽기, 셀 수정, 병합, 서식, 라벨 기반 탐색/채우기 | 표 조작과 양식 자동화 전반 |
| **서식** | 텍스트 서식, 커스텀 스타일 | 굵기, 색상, 크기, 폰트 등 적용 |
| **복구** | repair/recover | 깨진 HWPX를 원본 보존 복사본으로 재패킹/복구 |
| **기타** | 페이지 나누기, 스타일 목록, 파일 탐색 | 문서 구성 보조 기능 |

---

## 이런 분들에게 추천합니다

- 📚 **학교·교육기관**: 운영계획, 안내문, 보고서 반복 작성
- 🏛️ **공공기관**: 공문서/보고서/편람 대량 관리
- 🏢 **기업**: 제안서, 회의록, 매뉴얼 중심 업무
- 🔧 **개발자**: 한글 문서 자동화 파이프라인 구축
- 🤖 **AI 활용자**: Claude, GPT 등과 협업 자동화

---

## 시작하기

```bash
# 설치
pip install "python-hwpx-automation[mcp]"

# 실행
hwpx-automation-mcp
```

업스트림 버전 참고:
- `Python >= 3.10`
- `python-hwpx >= 5.1.0`

6.x 호환 기간에는 기존 `hwpx-mcp-server` distribution과 console도
동작하지만, 새 설정과 문서는 canonical 이름을 사용합니다.

MCP 설정 예시:

```json
{
  "mcpServers": {
    "hwpx": {
      "command": "uvx",
      "args": [
        "--from",
        "python-hwpx-automation[mcp]==6.1.3",
        "hwpx-automation-mcp"
      ]
    }
  }
}
```

---

## 테스트 결과

실전 유즈케이스 9개 시나리오를 기준으로 검증했습니다.

- ✅ 문서 요약 자동 생성
- ✅ 인사이동 일괄 반영 (19건 치환, 잔존 0건)
- ✅ 왕복 치환 무결성 (한↔영 복원)
- ✅ 17개 표 전수 데이터 마이닝
- ✅ 문서 구조 재편 (삽입·삭제·이동)
- ✅ 회의록 템플릿 자동 생성 (4개 표 포함)
- ✅ 다국어 용어 양방향 전환
- ✅ 복잡한 표 파이프라인 (셀 병합 + 서식)
- ✅ 대량 작업 스트레스 테스트 (50문단, 50건 치환)

상세 검증 로그는 `tests/hwpx_mcp_report_updated.md`를 참고하세요.

---

## Skill-first workflow guide

For reference-preserving workflows on the current FastMCP surface, see:

- `docs/skill-first-workflows.md`
- `examples/skills/reference-preserving-edit/SKILL.md`
- `examples/skills/form-fill/SKILL.md`
- `examples/skills/template-generation/SKILL.md`

Current workflow boundary:

- No new public MCP tools are required for these flows.
- There is no active public `fill_template` tool on the FastMCP surface.
- There is no active public `save` / `save_as` tool on the FastMCP surface; mutating tools persist immediately, so use `copy_document` when you need a reviewable output path.
- Use `copy_document` first when you need a reviewable or low-risk edit path because mutating tools persist immediately.
- Use advanced mode for package inspection and validation steps: `package_parts`, `package_get_xml`, `package_get_text`, and `validate_structure`. Use `apply_document_commands` for new heterogeneous atomic edit flows; the `plan_edit`/`preview_edit`/`apply_edit` and `analyze_quality_generation`/`apply_quality_generation` transition stubs were removed at the 5.0.0 major boundary (use `create_document_from_plan` + `inspect_document_quality` for quality generation).

Layer ownership:

- `python-hwpx` stays the upstream engine for HWPX/package behavior.
- `python-hwpx-automation` owns the task API and exposes its optional MCP
  adapter through `src/hwpx_automation/server.py`.
- Skills and workflow examples orchestrate those tools; they do not replace core editing logic.

## Agent-first proposal document generation

The automation application generates proposal/planning documents through the
canonical document-plan path and exposes the same flow through its optional MCP
adapter. It inspects the result with `inspect_document_quality`.

Recommended flow:

1. Convert the user's natural-language request into a proposal-shaped `hwpx.document_plan.v1`.
2. Call `validate_document_plan`, then `analyze_document_plan` without writing a file.
3. Call `create_document_from_plan` to write and verify the HWPX.
4. Call `inspect_document_quality` to check validation, required sections, tables, asset weight, rubric scores, and the v2 `sample_match` proxy dimensions.
5. Revise the plan if average rubric score is below 4.0, `sample_match.pass` is false, or a required section is missing. `create_proposal_document` remains only as a compatibility facade.

This path intentionally benchmarks DOCX-style document principles without implementing a DOCX converter, GUI, model tuning, renderer, or pixel-diff gate. `visual_review_required=True` means rendered parity is not claimed.

### Visual review handoff evidence

For operating-plan and template-formfit handoff, file-only quality gates are not
enough for a submission-ready visual claim when `visual_review_required=True`.
Record `hwpx.visual-review.v1` evidence after opening or rendering the output.

Observed pass:

```bash
python3 ../hwpx-skill/scripts/visual_review.py work/output.hwpx --evidence work/output.visual-review.json --viewer auto --status observed_pass --screenshot work/output-page1.png --observation "Front matter, section headings, schedule table, and budget table are visible."
```

Viewer-missing blocked fallback:

```bash
python3 ../hwpx-skill/scripts/visual_review.py work/output.hwpx --evidence work/output.visual-review.json --viewer none --status blocked --notes "No HWPX viewer is available on this machine."
```

`observed_pass` with `--screenshot` evidence is the only status that permits a submission-ready visual claim.
`needs_review` and `blocked` preserve residual risk and should not be described
as final visual clearance.


> 릴리스 상태 참고: 현재 공개 트레인은 python-hwpx 6.1.0 · python-hwpx-automation 7.0.1 · hwpx-plugin 2.0.0입니다. automation 7.0.2 패치가 release-approved 상태이며 원격 진실 관찰 전까지 공개 좌표는 승격되지 않습니다.
