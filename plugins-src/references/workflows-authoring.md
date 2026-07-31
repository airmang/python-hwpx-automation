# 문서 작성 (공문·보고서·가정통신문) — workflows-authoring

**언제:** "공문/보고서/가정통신문 만들어줘" 같은 자유 요청에서 **성격에 맞는 완성 HWPX**를 제로베이스로 생성할 때. (양식 채움은 workflows-forms, 시험지 재조판은 workflows-exam.)

**핵심 도구:** `create_document_from_plan(filename, document_plan, verify_render=False)`.

`document_plan.metadata.document_type` 가 **공문 / 보고서 / 가정통신문** 이면 실제 한컴-harvest 프로파일(opens-clean)로 생성됩니다. 그 외 유형은 제로베이스 빌더로 떨어집니다.

## 작성 루프

1. **유형 판단(에이전트):** 공문 / 보고서 / 가정통신문 중 하나 → `metadata.document_type`.
2. **내용 구성:** `blocks[]` = `{type: heading, level: 1~3, text}` · `{type: paragraph, text}` · `{type: bullets, items}` · `{type: table, columns, rows}`. 공문·보고서의 하위 위계는 **항목기호 1.→가.→1)→가)** 를 본문 텍스트로 쓴다(Word식 다단 heading 아님 — 한국 공문 정통 방식).
3. **공문이면 두문/결문을 반드시 채운다:**
   - 두문: `blocks` 첫머리에 `{type: paragraph, text: "수신  <수신자>"}` (필요시 "(경유)").
   - 본문 마지막: `…  끝.` (붙임이 있으면 붙임 뒤).
   - 결문: `document_plan.gyeolmun = {issuer: "○○기관장", productionNumber: "처리과-번호", enforcementDate: "YYYY. M. D.", disclosure: "공개|부분공개|비공개"}`.
4. **생성:** `create_document_from_plan("out.hwpx", plan)`. 출력은 **HWPX 전용**(ODT 기안문·docx·pdf 미지원 → 거부).
5. **응답 `quality` 확인:**
   - `gongmun_structure.structure_pass` — 공문 작성규정 **구조 hard-gate**(수신·발신명의·시행·공개구분·끝.). `false`면 빠진 요소를 보강해 재생성.
   - `korean_proofing_status` — 기본 `"unverified"`(무료·오프라인 한국어 검사기 없음). 직접 교정했으면 `metadata.korean_proofing = "llm_proofed"` → `"llm_proofed_not_oracle_verified"`. **맞춤법 '통과'를 가장하지 말 것.**
   - `render_checked` / `visual_complete` — `verify_render=True` + Mac 한컴 가용 시 실제 렌더 영수증. 아니면 `"unverified"`.

## 안전 수칙 (정직 보고)

- 공문은 `structure_pass=true` 를 **확인**하고 넘긴다.
- 맞춤법·각주·시각완성은 자동 검증되지 않으면 **`unverified` 라벨 그대로** 보고한다(거짓 통과 금지).
- **각주(footnote)** 는 현재 한컴 렌더 미지원 → 사용하지 않거나 unverified로 표기.

## 수식 삽입 (`add_equation`) — 네이티브 `<hp:equation>` 저작

6.2.0부터 수식을 **생성**할 수 있다. 실한컴이 만드는 수식 형상 그대로
방출되므로 한컴이 네이티브로 조판·재편집하고, 기존 리더(EqEdit→LaTeX→MathML
프리뷰)가 특수분기 없이 되읽는다.

**판단 규칙**
1. 입력은 `latex`(권장) 또는 `script`(EqEdit 원문) **하나만**. LaTeX는
   렌더 검증된 토큰셋만 변환되며, 밖이면 `EQUATION_LATEX_UNSUPPORTED`로
   거부된다 — **무음 근사 없음**. 거부되면 지원 표기로 바꿔 쓰거나(예:
   `\limsup`→`\lim` 계열 재표현, `\begin{Bmatrix}`→`pmatrix`/`bmatrix`),
   불가능하면 사용자에게 해당 수식만 한계로 정직 보고한다.
2. 응답의 `readerLatex`가 원 LaTeX와 의미 동치인지 눈으로 확인한다 — 이것이
   자기 왕복 증거다. 시각 확인이 필요하면 `render_preview(viewer=true)`가
   수식을 MathML로 실렌더한다.
3. 배치 주소는 셋 중 하나만: 생략(문서 끝 새 문단) · `paragraph_index` ·
   `tableIndex`+`row`+`col`(표 셀). 수학 시험지 등 양식 배치에 셀 주소를 쓴다.
4. 수식은 인라인 개체라 줄높이를 바꾼다 — 저작 후 렌더 검증 경로(oracle
   가능 시)로 최종 확인한다.

## 데모

`demo/M3-authoring/` — 공문·보고서·가정통신문 3종을 이 표면으로 생성해 실제 한컴 opens-clean 확인(증거 PNG + verdict).
