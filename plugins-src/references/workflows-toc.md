# 네이티브 자동 차례·상호참조 — workflows-toc

**언제:** 다쪽 보고서/제안서에 **살아있는 목차**(한컴이 재계산하는 차례)나 "'추진 계획' 참조(N쪽)" 같은
**쪽 번호 상호참조**를 넣을 때. 고정 텍스트 목차는 문서를 편집해 페이지가 밀리는 순간 거짓이 된다 —
네이티브 필드는 한컴이 스스로 재번호한다. (`hwpx-mcp-server>=4.3.0` 계약; 기능은 네이티브 TOC 트랙에서 도입.)

**핵심 의미론 (실측):**
- `add_toc`가 삽입하는 차례는 `dirty=1` 네이티브 필드 — **한컴이 처음 여는 순간 항목·차례 스타일·쪽번호를
  통째로 재계산**한다(방출 시점 쪽번호는 추정치, 응답의 `cachedPagesAreEstimates`).
- **상호참조 캐시는 완전 자동** — 한컴이 열기/편집/저장 시 재계산. 추정치로 넣어도 자가 치유.
- 문서를 나중에 편집해 페이지가 밀리면? 라이브러리의 `mark_toc_dirty`(python-hwpx `hwpx.tools.toc_author`)로
  재계산을 다시 트리거(재-dirty)하면 다음 열기에 재번호.

**도구:**
- `add_toc(filename, level=2, leader=3, hyperlink=False)` — 개요(1~10) 스타일 제목들로 네이티브 차례 삽입.
  제목이 개요 스타일이어야 한다(`add_heading` 사용). **본문은 본문(스타일 1) 등 비수집 스타일로** —
  바탕글(스타일 0) 문단은 차례에 항목으로 끌려간다(실측).
- `add_cross_reference(filename, paragraph_index, target_heading_text, cached_page=1)` — 지정 문단 끝에
  특정 제목의 쪽 번호 상호참조 추가.
- `verify_toc(filename, refresh=False, verify_render=False)` — 캐시 쪽번호 검증.
  `verify_render=True` = 실제 한컴 렌더로 캐시 vs 실페이지 대조(`toc_correctness_ratio`).
  `refresh=True` = 검증 전 한컴을 열어 dirty 필드 재계산·저장(macOS GUI 오라클).
  오라클 없으면 **정직하게 `unverified`** — 단, 상호참조와 차례 캐시가 서로 모순이면 렌더 없이도
  `stale_detected_structurally`로 잡는다.

## 루프

1. **저작:** `add_heading`으로 개요 제목 구조를 만들고 본문을 채운 뒤 `add_toc` (+필요 시 `add_cross_reference`).
2. **검증(선택):** `verify_toc(verify_render=True)` — 한컴 렌더 대조. 데모 기준 ratio 1.0.
3. **편집 후 재번호:** 페이지가 밀리는 편집을 했다면 `mark_toc_dirty`(라이브러리) 후 저장 — 한컴이 다음 열기에 재계산.

## 정직 라벨

- 재계산은 **한컴이 여는 시점**에 일어난다(반자동) — 파일 캐시가 저절로 갱신되는 것이 아니다.
- 렌더 검증 없이 통과를 주장하지 않는다(`unverified` 명시). Mac에서 refresh와 render는 별도 세션
  (dirty-재생성 직후 같은 세션 PDF export는 이 한컴 빌드가 크래시 — 실측 우회).
- document_plan v2의 `{type:"toc"}`는 아직 **정적 텍스트 경로** — 네이티브는 `add_toc` 도구 경로.
  plan-v2 native 옵션은 follow-on.
