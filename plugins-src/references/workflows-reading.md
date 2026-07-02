# 런서식 충실 읽기(+각주/미주) — workflows-reading

**언제:** 문서를 **읽어서** 인라인 글자 서식(굵게·기울임·밑줄·취소선·색·크기·글꼴)과 **각주/미주 본문**까지 손실 없이 되살릴 때. 원문 인용·재작업·라운드트립 검증에서 서식/각주가 누락되면 안 될 때. (M6/S-060 — `hwpx-mcp-server>=2.11.0`.)

**핵심:** 이전엔 모든 읽기 표면이 각주 본문을 드롭했고 크기·글꼴은 노출되지 않았다. 이제:
- `hwpx_extract_json` 은 항상 `doc.notes[]` 를 방출 — 각주/미주의 `kind`·`instId`·`anchorParaIndex`·`bodyText`·`bodySpans`(본문 서식). PII 마스킹 기본 ON.
- `hwpx_extract_json(format_detail=True)` 런 상세에 **명명 필드** `bold`·`italic`·`underline`·`strikeout`·`color`·`fontSize`·`fontName`·`superscript`·`subscript`. (`strikeout` 은 실제 취소선일 때만 true — 상시-true 버그 수정됨.)
- `hwpx_to_markdown` 은 각주/미주 정의 부록(`[^fn1]: 본문`, `[^en1]: 본문`)을 본문 뒤에 덧붙인다.

## 루프

1. **구조 읽기:** `hwpx_extract_json(format_detail=True)` — 문단·표 + 런별 서식 + `notes[]`. 서식 스팬을 그대로 소비.
2. **가독 읽기:** `hwpx_to_markdown` — 본문 + 각주/미주 부록. 사람이 읽거나 재요약할 때.
3. **충실도 검증(선택, 라이브러리):** `hwpx.tools.read_fidelity.roundtrip_fidelity(path)` — 편집→저장→재열기 후 런서식·각주 보존율(구조적, 오라클 불요). 코퍼스 집계는 `corpus_fidelity`.

## 정직 라벨

- **구조적**(오라클 불요): charPr 해석 런-스팬 + 각주 본문의 before/after·source↔surface 대조로 입증. 코퍼스 4075런 라운드트립 1.0.
- **폰트명**은 문서 fontface 표를 통해 해석. 표에 없는 이름은 원 fontRef 기준으로 폴백될 수 있다.
- 각주 **인라인 앵커 마커**(본문 중간 `[^fn1]` 위치)는 후속 개선 대상 — 현재 마크다운은 말미 부록으로 보존.
