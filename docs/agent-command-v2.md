# 문서 에이전트 명령 v2 (hwpx-automation 8.0)

`apply_document_commands`·`get_document_node`·`query_document_nodes`·블루프린트 도구가 쓰는 꼴이다.
v1(7.x)과 달라진 점만 적는다. 계약 차이는 `docs/tool-contract-delta-8.0.0.json`에 있다.

## 한 줄 요약

글은 런의 차례가 아니라 **문단의 글자 범위**로 다룬다. 표·그림·도형·각주·미주는 **글자 자리**에 놓는다.
글자 자리는 `paragraph.text`로 센다(탭·줄바꿈은 1, 컨트롤·개체는 0).

## 새 꼴

| 하는 일 | v2 꼴 |
|---|---|
| 글 넣기 | `{"op": "add", "kind": "text", "parent": <문단>, "position": {"mode": "offset", "offset": 3}, "properties": {"text": "가나", "bold": true}}` |
| 글 범위 고치기 | `{"op": "set", "path": "<문단>/text[3:5]", "properties": {"text": "다라"}}`(모양 6가지도 받음) |
| 글 범위 지우기 | `{"op": "remove", "path": "<문단>/text[3:5]"}` |
| 글 옮기기·복사 | `{"op": "move" \| "copy", "path": "<문단>/text[3:5]", "parent": <다른 문단>, "position": {"mode": "offset", "offset": 0}}` |
| 개체·각주를 자리에 | `"position": {"mode": "offset", "offset": n}` 또는 같은 문단 개체의 `before`·`after` |
| 각주 더하기 | `{"op": "add", "kind": "footnote", "parent": <문단>, "position": ..., "properties": {"text": "..."}}` |

- 결과의 `place`: `{"paragraph": <문단 경로>, "offset": n, "length": m}`. 글 범위·런·개체·각주에 실린다.
- `get_document_node`는 `<문단>/text[s:e]`도 읽는다(`text`·`start`·`end`·`runs`). 런·개체 노드의 `summary`에는 `place`가 있다.
- 블록 자리(문단·행)는 v1과 같다: `append`·`prepend`·`index`·`before`·`after`.
- 명령에 `schemaVersion`(v1·v2)을 줄 수 있다. 주지 않으면 일괄의 판을 따른다.

## v1 꼴이 받는 대접

| v1 꼴 | v2 |
|---|---|
| 런 `add`·`remove`·`copy` | `contract_changed` — `kind "text"`로 |
| 문단 안 개체·글·각주의 `"mode": "index"` | `contract_changed` — `offset`으로 |
| 문단 안 `before`·`after`가 런 경로 | `contract_changed` — 런의 `place.offset`으로 |
| v1 명령에 v2 꼴(`text`, `offset`, `text[..]`)을 섞음 | `contract_changed` — `schemaVersion` v2로 |
| 문단 안 `append`·`prepend`(v1 명령) | 옛 자리(같은 종류의 뒤·앞)와 새 자리(글 끝·맨 앞)가 같으면 받는다. 다르면 `contract_changed`, `suggestion`에 옛 자리의 offset |
| 런 `set`, 문단·표·칸·행·누름틀·메모 명령 | 그대로 받는다 |

`contract_changed`는 `recoverability: "needs-review"`이고 `suggestion`에 새 꼴 한 줄이 있다.

## 블루프린트 v2

- 덤프는 `hwpx.agent-blueprint/v2`만 쓴다. 개체·각주는 `properties.offset`, 누름틀은 `properties.start`·`end`에 둔다. `references`는 비어 있다.
- v1 블루프린트는 받는다. v1 규칙(해시, catalog v1)으로 검증한 뒤 v2로 읽어 올린다.
  - 개체는 hostRun 끝에 둔다.
  - 누름틀은 hostRun 끝부터 endRun 끝까지 감싼다.
  - 결과 `verificationReport.upgradedFrom`에 `hwpx.agent-blueprint/v1`이 실린다.
- 런이 다른 문단을 가리키는 v1 블루프린트는 `unsupported_content`로 거부한다. 8.0으로 다시 덤프하라는 안내가 붙는다.
