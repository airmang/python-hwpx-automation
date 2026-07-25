# 시험지 조판 워크플로 (출제 md → 학교 양식 재조판, 문항 keep-together)

따로 출제·정리된 시험 문제(Markdown)를 **학교 시험지 양식 `.hwpx`** 에 그 양식의 기존
스타일로 다시 조판한다. 출제(내용 생성)는 **상류 단계**이고 이 워크플로는 **재조판(조판)**
만 한다. 핵심 보장: **한 문항이 단/쪽 경계에서 잘리지 않는다(keep-together)**, 관리박스·
머리글/꼬리글·결재란은 **무손실 보존**, 그림/표/수식은 **텍스트 placeholder로 남겨** 사람이
나중에 삽입한다.

> **요구 도구**: 이 번들은
> `compose_exam` / `verify_question_splits`를 사용한다. `mcp_server_health()`의
> `toolSurface`에 이름이 없거나 계약 해시가 다르면 설치 조합이 맞지 않는 것이므로 이
> 워크플로를 시도하지 말고 core/MCP/plugin 버전과 활성 profile을 먼저 교정한다.

## runtime 소유권과 호환 정책

- 시험지 parser/IR/profile/measurement/composition의 **정본은
  `hwpx-mcp-server`의 `hwpx_mcp_server.office.exam`** 이다. 실제
  `compose_exam`·`verify_question_splits` 호출은 이 정본으로만 라우팅된다.
- `python-hwpx 4.x`의 `hwpx.exam`은 기존 직접 사용자를 위한 **동결된 operational
  compatibility copy**다. 새 기능은 MCP 정본에만 추가한다.
- core 4.x copy 수정은 보안·정확성 문제에만 허용하며, MCP 정본과 동일한 패리티
  테스트와 변경 receipt를 함께 남겨야 한다. 일반 개선이나 리팩터링을 양쪽에
  독립적으로 적용하지 않는다.
- core copy는 python-hwpx 5.0에서 제거됐다. 조판 정본은 MCP
  `office.exam`이며, 직접 import 사용자는
  [`migration-core-5.0.md`](migration-core-5.0.md)의 대체표를 따른다.

## 입력 계약

| 입력 | 형태 | 처리 |
|---|---|---|
| 컨테이너 | 학교 양식 `.hwpx` (관리박스·페이지셋업·머리글/꼬리글·결재란이 이미 채워짐) | 본문영역만 조판, 나머지는 그대로 보존 |
| 본문 | 출제 Markdown (반구조; 아래 컨벤션) | Exam IR로 정규화 후 양식 본문에 INSERT |
| 비텍스트 | `[그림N]` · `[표N]` · `[식N]` 텍스트 마커 | 발문 안에 그대로 둠 — **사람이 그림 삽입** |

## 출제 md 컨벤션 (조판기가 파싱하는 형식)

```
# 2026학년도 2학년 정보 중간고사        ← (선택) 첫 H1 제목, 첫 문항 앞
## 1. (2점)                            ← 단독 문항: "## <번호>. [(<배점>점)]"
다음 중 가장 작은 단위는?               ← 발문
[그림1]                                ← placeholder는 발문 안에 그대로 (인라인)
① 비트                                 ← 답항: ①②③④⑤ 리터럴 마커
② 바이트
## 3∼4. 세트                           ← 세트문제 헤더: "## <a>[∼~]<b>. 세트"
다음 코드를 보고 물음에 답하시오. …      ← 공통지문
### 3. (3점)                           ← 세트 멤버: "### <번호>. [(<배점>점)]"
…
```

- 배점 `(N점)` 은 생략 가능. 번호·`①~⑤` 는 **리터럴 텍스트**(자동 번호 아님) — 양식의 실제
  시험지와 동일하게 그대로 찍힌다.
- 파서는 **fail-loud** 다: 문항 헤더 앞의 본문, 활성 문항 없는 답항 줄 등은 조용히 넘어가지
  않고 오류로 보고한다(조용히 틀린 조판 금지).

## 조판 루프

1. **조판**: `compose_exam(form_filename, output, exam_md=..., verify=true)`
   (또는 큰 본문은 `exam_md_filename=경로`). `exam_md` 와 `exam_md_filename` 은 **정확히 하나**.
   - `verify=true`(기본): 한컴 렌더로 문항-split/overflow/placeholder를 측정한다.
   - `verify=false`: 렌더 없이 조판만(빠름, `renderChecked=false`).
   - `role_style_names`(선택): 역할→양식 스타일 **이름** 매핑 override (예
     `{"number":"문항번호","choice1":"답지1행"}`). 기본은 양식 표준 스타일
     (바탕글·문항자동번호넣기·1~5행답항·(보기)박스안내용)을 쓰니 대개 생략한다.
     `max_rounds`(기본 2): split 수렴 재렌더 횟수.
   - 응답: `{ok, outputPath, renderChecked, splits, overflow, placeholdersOk, rounds,
     needsReview, notes, openSafety}`.
2. **정직 판정**: 응답을 **그대로** 읽는다. `renderChecked=false` 면 검증 안 된 것이고,
   `splits` 가 숫자면 그 수만큼 문항이 단/쪽 경계에 걸친 것이다.
3. **시각 확인(이 양식류 필수)**: 학교 원안지 양식은 한컴이 본문을 **벡터 커브로 export**
   하는 경우가 많아 텍스트 추출 게이트가 문항을 못 읽는다 → 응답이 `splits=null` +
   `needsReview=true` 로 온다(이건 **0 splits가 아니라 "텍스트로는 검증 불가"** 라는 정직한
   신호다). 이때는 `render_preview(outputPath)` 로 렌더 이미지를 만들어 **사람/이미지로
   문항 잘림·관리박스/꼬리글 보존·placeholder 유지를 눈으로 확인**한다. **`needsReview=true`
   를 통과(verified)라고 주장하지 않는다.**
4. **독립 재검**(선택): `verify_question_splits(filename, valid_question_numbers=[...], marker_regex=...)`
   — `filename` 은 조판 **출력 파일**(1단계 `output` / 응답 `outputPath`). `valid_question_numbers`
   에 조판한 문항 번호를 주면 그 번호로 스코핑해 양식 chrome(예: "2026." 연도)이 가짜 문항을
   열지 않는다. `marker_regex`(선택)는 문항 번호를 인식하는 정규식 override(기본은 줄 첫머리
   `"N."` 패턴; `group(1)` 이 문항 번호). 같은 정직 규칙: 오라클 없음→`renderChecked=false`,
   커브-export→`splits=null`+`needsReview`.
5. **수렴**(필요 시): `splits` 가 양수면 조판기가 라운드마다 해당 문항 머리에 break를 넣어
   재렌더한다(`max_rounds`). 그래도 안 되면 `set_paragraph_format(..., page_break_before=true)`
   로 그 문항을 다음 쪽으로 직접 민다.

## keep-together 메커니즘

조판기는 각 문항의 마지막 문단을 제외한 모든 문단에 `keepWithNext` 를 단다(공짜 단 응집).
한컴은 keepWithNext/keepLines를 **단(column) 응집에는** 존중하지만 **쪽 경계는 미존중** 하므로,
오라클 측정에서 남은 straddle은 `columnBreak`/`pageBreak` 삽입으로 결정론적으로 해소한다
(오라클 부재 시 columnBreak 기본). 수동 개입이 필요하면 `set_paragraph_format` 의
`keep_with_next` / `keep_lines` / `page_break_before` 를 쓴다.

## 안전 수칙

- **원본 양식 보존**: 조판은 항상 원본과 **다른 `output`** 에만 쓴다.
- **openSafety**: 응답 `openSafety.ok == true` 를 확인한다. false면 handoff하지 않는다.
- **그림은 placeholder로**: `[그림N]` 등은 텍스트로 남는다. 자동 이미지 배치는 v1 비목표 —
  최종본에 그림이 필요하면 사람이 한컴에서 삽입한다.
- **정직 보고**: 커브-export 양식에서 텍스트 게이트가 unverified면, "조판은 됐고 시각
  증거로 확인했다"까지만 주장한다. 텍스트 split=0 을 사칭하지 않는다.

데모(프롬프트→조판→시각 증거)는 `demo/exam-typesetting/` 참조.
