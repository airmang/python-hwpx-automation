# 한컴 없는 스크롤 통독 프리뷰 — workflows-preview

> 수식 MathML 렌더에는 core의 `preview` extra가 필요하다 (`python-hwpx[preview]`).

## 렌더 소유권과 호환성

- 실제 한컴 discovery·실행·worker·페이지 QA의 정본은
  `hwpx_mcp_server.office.rendering`이다. `python-hwpx`에는
  report/protocol/mask·detector/diff 같은 renderer-neutral 계약만 정본으로
  남는다.
- `python-hwpx` 4.x의 `hwpx.visual.oracle`·`hancom_worker`·fixture/page-QA
  export는 기존 소비자를 위한 호환 표면이다. 새 기능과 MCP 실행 경로는 그
  호환 복사본을 직접 호출하지 않는다.
- 이 소유권 이동은 도구 이름·입력·출력·분류를 바꾸지 않는다.
  `render_preview`의 텍스트 근사 경로와 아래 실제 한컴 렌더 라우팅도 그대로다.
- 오라클이 없거나 시간 예산이 끝나면 결과는 `renderChecked=false` /
  `unverified`다. 이를 성공한 실제 렌더로 표현하지 않는다.
- 4.x 호환 표면의 물리적 제거는 python-hwpx 5.0에서 완료됐다.

**언제:** 저작·편집을 마친 뒤 **한컴을 열지 않고** 문서를 처음부터 끝까지 스크롤로 통독 검수할 때.
특히 수식(`<hp:equation>`)이 포함된 문서에서는 프리뷰가 수식을 빈칸으로 떨구지 않고 실제로
조판해 보여줘야 검수가 의미 있다. 페이지 수가 많은 문서에서 진행 위치(현재 페이지)를 확인하고
싶을 때도 쓴다. (`viewer`는 `render_preview`의 추가 옵션.)

**도구:** `render_preview(filename, viewer=true, screenshot="off")`. `viewer`는 래스터화와
독립이므로, 페이지 PNG가 필요 없는 가벼운 텍스트 통독 경로에서는 `screenshot="off"`로 무거운
headless 캡처를 끈다. `mode="pages"`(기본, 페이지별 박스 + 인디케이터 추적) 또는 `"long"`
(연속 한 페이지).

**`structuredContent.viewer` 필드:**
- `viewerPath` — 워크스페이스 안에 쓰인 `viewer.html`의 상대 경로. HTML 크기와 무관하게 항상
  디스크에 쓰인다.
- `html` — 인라인 HTML 본문. `byteSize`가 cap(`max_viewer_bytes`, 기본 2MB)을 넘으면 빠지고
  `htmlOmitted: "exceeds_max_viewer_bytes"`만 남는다 — 이때도 `viewerPath`의 파일은 온전하니
  그걸 연다.
- `pageCount`, `warnings` — 근사 페이지네이션과 프리뷰 경고.
- `fidelityTier` — 예: `"text-approx-pagination; equations=mathml"`. **에이전트는 이 값을
  사용자에게 있는 그대로 보고한다** — "픽셀 정확"이나 "한컴과 동일"로 번역하지 않는다. 텍스트
  레이아웃·페이지네이션은 항상 근사이고, 한컴 렌더만이 truth다(헌법 IV).
- `equationLibrary` — `"latex2mathml"`(설치됨) 또는 `"absent"`.
- `equationRendering` — `{mathml, latexFallback, scriptFallback}` 개수. 문서 내 각 수식이
  어느 단계에서 멈췄는지의 정직한 집계.

**수식 fail-closed 3단계(빈칸 금지, 헌법 VI):**
1. **mathml** — EqEdit→LaTeX→MathML 전부 성공, 브라우저 네이티브 `<math>` 렌더. 최고 충실도.
2. **latex-fallback** — LaTeX 변환은 성공했으나 MathML로 못 감(라이브러리 `python-hwpx[preview]`
   미설치 또는 MathML 변환 자체 실패). LaTeX 원문이 코드블록으로 보인다 — 라이브러리 부재가
   사유면 `pip install python-hwpx[preview]` 설치를 안내한다.
3. **script-fallback** — LaTeX 변환조차 실패. 원본 `<hp:script>`(EqEdit 소스)를 코드블록으로
   그대로 노출 — 설치로 해결되지 않으니, 수식 원문을 한컴에서 직접 확인하라고 안내한다.

fallback이 보이면 `equationRendering`에서 어느 단계 카운트가 올랐는지 확인해 위 안내를 하되,
**빈 문단이 아니라 항상 무언가 보이는** fail-closed 설계이므로 "수식이 사라졌다"고 오해하지 않는다.

## 루프

1. 저작/편집 완료 후 `render_preview(filename, viewer=true, screenshot="off")` 실행.
2. `structuredContent.viewer.fidelityTier`와 `equationRendering`을 확인하고, 그대로(정직하게)
   사용자에게 보고한다.
3. **환경별 전달:**
   - **Claude Code**: `viewerPath`가 가리키는 파일을 읽어 Artifact로 발행 — 사용자가 브라우저에서
     스크롤 통독한다.
   - **Codex/기타 로컬 환경**: `open <viewerPath>`(macOS) 또는 대응 명령으로 로컬에서 연다.
     Artifact 발행 경로가 없다.
4. 뷰어 상단 배지("텍스트 근사 프리뷰 · 페이지네이션은 한컴과 다를 수 있음 · 수식 MathML 렌더")가
   항상 표시된다 — 그대로 사용자에게 전달해도 된다.
5. **제출 전 최종 검수**처럼 픽셀 단위 truth가 필요하면 이 뷰어로 대체하지 말고
   [`workflows-real-hancom-render.md`](workflows-real-hancom-render.md)(`render_health` →
   `render_submit` → `render_status`) 경로로 실제 한컴 렌더를 받는다.

## 정직 라벨

- 뷰어는 **텍스트 근사 프리뷰**다. 페이지 경계·줄바꿈·비함초롬 폰트 픽셀은 한컴과 다를 수 있다
  (헌법 IX) — 조판 엔진 재구현이 아니다.
- **수식만 렌더 검증**됐다(P0에서 한컴 대조로 구조 일치 확인,
  `specs/012-document-preview-viewer/evidence/p2v-receipt.md`). 나머지 레이아웃(페이지 수 등)은
  근사이지 truth가 아니다.
- 도형/그림/OLE은 실제 렌더가 아니라 `⟦그림 N⟧`·`⟦도형⟧` 자리표시 마커로 노출된다(표는 이미
  렌더됨) — 빈칸이 아니라 "여기 무언가 있다"는 정직한 신호.
- `viewer=true`는 `render_preview`의 애디티브 옵션이다 — 기본 호출(`viewer` 생략)의 출력 스키마는
  그대로다.
