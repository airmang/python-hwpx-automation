# 런서식 충실 읽기(+각주/미주) — workflows-reading

**언제:** 문서를 **읽어서** 인라인 글자 서식(굵게·기울임·밑줄·취소선·색·크기·글꼴)과 **각주/미주 본문**까지 손실 없이 되살릴 때. 원문 인용·재작업·라운드트립 검증에서 서식/각주가 누락되면 안 될 때. (`hwpx-mcp-server>=4.2.1` 계약; 기능은 M6/S-060에서 도입.)

**핵심:** 이전엔 모든 읽기 표면이 각주 본문을 드롭했고 크기·글꼴은 노출되지 않았다. 이제:
- `hwpx_extract_json` 은 항상 `doc.notes[]` 를 방출 — 각주/미주의 `kind`·`instId`·`anchorParaIndex`·`bodyText`·`bodySpans`(본문 서식). PII 마스킹 기본 ON.
- `hwpx_extract_json(format_detail=True)` 런 상세에 **명명 필드** `bold`·`italic`·`underline`·`strikeout`·`color`·`fontSize`·`fontName`·`superscript`·`subscript`. (`strikeout` 은 실제 취소선일 때만 true — 상시-true 버그 수정됨.)
- `hwpx_to_markdown` 은 각주/미주 정의 부록(`[^fn1]: 본문`, `[^en1]: 본문`)을 본문 뒤에 덧붙인다.
- `document_to_markdown(filename)` 은 로컬 파일 ingest 경로다. HWPX는 `python-hwpx` 엔진으로 처리하고,
  `[ingest]` extra가 설치된 경우 PDF/DOCX/XLSX/HTML/TXT 등은 optional MarkItDown adapter로 처리한다.
- `document_extract_json(filename)` 은 같은 ingest 결과를 Markdown + `sections`/`tables`/`metadata`로 반환한다.

## 루프

1. **구조 읽기:** `hwpx_extract_json(format_detail=True)` — 문단·표 + 런별 서식 + `notes[]`. 서식 스팬을 그대로 소비.
2. **가독 읽기:** `hwpx_to_markdown` — 본문 + 각주/미주 부록. 사람이 읽거나 재요약할 때.
3. **로컬 파일 ingest:** 사용자가 파일 경로만 줬거나 비-HWPX 원본을 읽어야 하면
   `document_to_markdown(filename)`을 먼저 호출한다. 응답의 `meta.engine`,
   `meta.source_format`, `warnings`, `attempts[]`를 보고 어떤 converter가 처리했는지 확인한다.
4. **충실도 검증(선택, 라이브러리):** `hwpx.tools.read_fidelity.roundtrip_fidelity(path)` — 편집→저장→재열기 후 런서식·각주 보존율(구조적, 오라클 불요). 코퍼스 집계는 `corpus_fidelity`.

## 정직 라벨

- **구조적**(오라클 불요): charPr 해석 런-스팬 + 각주 본문의 before/after·source↔surface 대조로 입증. 코퍼스 4075런 라운드트립 1.0.
- **폰트명**은 문서 fontface 표를 통해 해석. 표에 없는 이름은 원 fontRef 기준으로 폴백될 수 있다.
- 각주 **인라인 앵커 마커**(본문 중간 `[^fn1]` 위치)는 후속 개선 대상 — 현재 마크다운은 말미 부록으로 보존.
- MarkItDown adapter 결과는 **구조 읽기용 Markdown**이다. PDF/DOCX/XLSX의 페이지 배치,
  표 폭, 글꼴, 줄바꿈 같은 레이아웃 충실도는 주장하지 않는다.
- 비-HWPX ingest에서 `error == "MissingMarkItDownDependency"`이면 서버가 `[ingest]` extra 없이
  설치된 것이다. HWPX 읽기는 계속 가능하지만, 일반 문서 ingest는 설치를 보강해야 한다.
