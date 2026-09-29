# python-hwpx-automation 파이썬 API (웹판)

`from hwpx_automation import api`로 쓰는 공개 facade 가운데 이 스킬이 검증한 부분이다.
깊은 모듈(`hwpx_automation.office.*`, `hwpx_ops`, MCP 서버)은 쓰지 않는다.
여기 없는 이름은 추측해서 부르지 않는다.

## 문서 계획 v1

| 함수 | 하는 일 |
|---|---|
| `api.validate_document_plan(plan)` | 계획을 검사한다. `ok`, `errors`, `warnings`, `issues`를 가진 보고서를 돌려준다. 각 issue는 `code`, `path`, `message`, `severity`, `suggestion`을 가진다. |
| `api.create_document_from_plan(plan)` | 계획으로 새 `HwpxDocument`를 만든다. 계획이 잘못되면 `ValueError`. 저장은 돌려받은 문서의 `save_to_path(경로)`로 한다. |

계획은 JSON 객체다.

| 키 | 필수 | 설명 |
|---|---|---|
| `schemaVersion` | 예 | `"hwpx.document_plan.v1"` (`schema`가 아니다) |
| `title` | 권장 | 문서 제목 |
| `subtitle` | 아니오 | 부제 |
| `metadata` | 아니오 | `organization`(기관), `author`(작성자), `date`(작성일), `document_type`(문서 유형)만 쓴다. 다른 키는 경고 없이 무시된다. 넣으면 제목 아래에 "문서 정보" 표가 생긴다 |
| `blocks` | 예 | 본문 블록 목록 (1개 이상) |

블록 종류(`type`):

| type | 필드 |
|---|---|
| `heading` | `text`, `level`(1부터) |
| `paragraph` | `text` |
| `bullets` | `items`(문자열 목록) |
| `table` | `columns`: `[{"key", "label", "widthWeight"}]`, `rows`: 열 `key`를 키로 하는 객체 목록, `caption`(선택), `unit`(선택, 예: "단위: 천원") |
| `page_break` | 없음 |
| `memo` | `text`(메모가 달린 **새 문단**으로 들어간다 — 같은 문장을 `paragraph`로 또 넣지 않는다), `memo`(메모 내용) |

- 글꼴·크기·여백은 기본 업무 문서 스타일로 정해진다. 이 웹판은 계획의 서식 필드를 검증하지 않았으므로
  넣지 않는다. 서식을 바꿔야 하면 문서를 만든 뒤 core API(`doc.page.set_margins` 등,
  [core/llms.txt](core/llms.txt))로 고친다.
- 검증 실패 시 `issues`의 `suggestion`을 따라 계획을 고쳐 다시 검증한다.

## 이 웹판에서 검증하지 않은 경로

아래 facade는 패키지에 들어 있지만 웹 샌드박스에서 검증하지 않았다. 요청이 오면 쓰지 말고,
"웹판에서는 아직 지원하지 않는다"고 알린다. 사용자가 Claude·Codex 데스크톱 플러그인을 쓸 수 있으면
그쪽을 안내한다.

- 복잡한 양식 채움: `api.analyze_form_fill`, `api.apply_form_fill`
- 시험지 합성: `api.compose_exam`, `api.parse_exam_markdown`
- 평가계획 채움: `api.parse_evalplan_review`, `api.fill_evalplan`, `api.finalize_evalplan`
- 장르 문서(공문 기안문·결재란·정부 보고서 양식), 한컴 렌더 검증, 미리보기 이미지
