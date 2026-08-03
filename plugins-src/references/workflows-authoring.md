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

6.2.1부터 수식을 **생성**할 수 있다. 실한컴이 만드는 수식 형상 그대로
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

## 차트 삽입 (`add_chart`) — 데이터 → 네이티브 차트

6.3.0부터 차트를 **생성**할 수 있다. 데이터 시리즈가 ECMA-376 chartML로
컴파일되어 실한컴이 네이티브로 그리고 차트 편집기로 편집 가능하다(OLE
폴백·사전렌더 이미지 없음 — 실측 계약).

**판단 규칙**
1. 유형은 렌더 검증된 MVP 3종만: `bar`(비교) · `line`(추이) · `pie`(구성비,
   시리즈 1개만). 밖을 요구받으면 `CHART_UNSUPPORTED`로 거부된다 — 가까운
   지원 유형으로 재제안하거나 한계를 정직 보고한다.
2. `series`의 각 `values` 길이는 `categories` 길이와 일치해야 한다. 표 데이터를
   차트로 옮길 때는 표를 먼저 읽고(예: `get_tables`) 시리즈로 변환한다.
3. 배치 주소는 셋 중 하나만: 생략(문서 끝, float) · `paragraph_index` ·
   `tableIndex`+`row`+`col`(표 셀). 본문 흐름에 넣으려면 `treat_as_char`.
4. 시각 확인이 필요하면 렌더 검증 경로(oracle 가능 시)로 최종 확인한다 —
   차트는 텍스트 추출에 나타나지 않는다.

## 데모

`demo/M3-authoring/` — 공문·보고서·가정통신문 3종을 이 표면으로 생성해 실제 한컴 opens-clean 확인(증거 PNG + verdict).

## 운영계획서 zero-base 저작 (장르-충실 백지 합성)

운영계획 브리프를 받으면 **장르 문법은 조회하고, 변주는 스킬이 판단**한다
— 엔진에 장르 하드코딩이 없으므로 판단을 코드에 기대지 말 것.

1. **장르 문법 조회**: `get_genre_grammar("operating_plan")` — 타이포
   역할(HY헤드라인M 헤더·휴먼명조 본문, portable 대체는 함초롬 계열)과
   구조 문법을 얻는다.
2. **변주 슬롯 결정**(문서마다 스킬이 판단): 번호 체계(Ⅰ… vs 1.…)·섹션칩
   렌더(`box`=accent 칩 vs `inline`)·accent 색·등장 블록(조직도/비교표/
   현황표/FAQ 중 브리프가 요구하는 것만).
   - **inline 칩이면 `number`를 비워** heading 자동번호에 맡긴다(번호
     중복 렌더 방지).
3. **plan 조립**: `compose_section_chip`의 block을 그대로 끼우고, 표는
   columns 객체+rows 매핑으로. 타이틀 밴드·칩은 `showHeader:false`가
   이미 담겨 온다. `validate_document_plan` → 오류는 repairHints로 수리.
4. **생성**: `create_document_from_plan(..., style_preset="genre:operating_plan")`
   — 장르 타이포가 뱅크에서 적용된다.
5. **box 칩 accent**: 생성 후 각 칩 표에
   `format_table(fill_color=<accent>, row=0, col=0)`.
6. **조직도**: `add_boxed_org_chart(filename, hierarchy, accent_color=…)`
   — 노드는 `{"label", "sublabel"?, "children"?}`; 깊이 4·박스 40 초과는
   typed 거부되니 큰 조직은 분할을 브리프와 상의.
7. **검수**: `render_preview` self-check로 칩·커넥터·표를 눈으로 확인.
   기계 통과를 "제출 가능"으로 번역하지 말고 오너 검수로 넘긴다.


## 기안문 서식 저작 (별지 제1·2호서식)

`compose_official_draft`(일반기안문)·`compose_simple_draft`(간이기안문)가
「행정업무의 운영 및 혁신에 관한 규정 시행규칙」의 **공개 서식 구조**를 범용
document-plan 블록으로 낮춘다. 파일은 쓰지 않으므로
`validate_document_plan` → `create_document_from_plan` 순으로 이어 붙인다.

### 두뇌(스킬)가 판정할 것

- **수신 형태**: 내부결재(`내부결재`) / 기관장+보조기관(`○○장관(○○과장)`) /
  합의제기관 / 민원인(우편번호·주소 포함) / 다수(`수신자 참조` + 결문 수신자란).
- **내부결재 여부**: `internal_only=true`이면 **발신명의를 넣지 않는다**.
- **결재자 목록**: 실제로 서명하거나 `전결`/`대결`을 표시하는 사람만 넣는다 —
  규칙 제7조제4항이 그 외 사람의 서명란 생성을 금지한다. 칸 수는 목록 길이다.
- **전결·대결**: 해당 권자의 `mark`에 `전결`/`대결`과 `date`를 넣는다(기관장란이
  아니라 **그 권자의 서명란**에 표시한다).
- **공개구분**: 부분공개·비공개는 괄호에 정보공개법 제9조제1항 호 번호를 적는다.

### 규정에서 오는 불변식(도구가 강제)

1. 결재란 칸 수 = 결재자 수(제7조제4항).
2. 결문 라벨 대부분은 **인쇄하지 않는다** — 행정기관명·발신명·기안자/검토자/
   결재권자·직위(직급) 서명·주소·홈페이지·전자우편·공개 구분(별지 제1호서식
   비고). 반대로 `시행`·`접수`·`우`·`협조자`·`전화번호`·`팩스번호`는 표시한다.
3. 선택 항목에 **체크박스 개체를 쓰지 않는다** — 별표 4 제10호가 `[  ]`+√
   텍스트를 규정한다(`※ [ ]에는 해당되는 곳에 √표를 합니다.`).

### 정직 경계

- 본문 글꼴·글자 크기, 행 높이·열 폭 mm는 **법령이 정하지 않는다**. 프리셋
  기본값을 쓰되 "규정이 정한 값"이라고 말하지 않는다.
- 문서 제목 줄(예: "일반기안문")은 서식에 없다 — plan `title`을 비운다.
- 현재 document_plan의 문단 `align`은 산출물에 반영되지 않는다(알려진 결함).
  가운데 정렬이 필요한 기관명·발신명의는 생성 후 `set_paragraph_format`으로
  따로 맞춘다.
