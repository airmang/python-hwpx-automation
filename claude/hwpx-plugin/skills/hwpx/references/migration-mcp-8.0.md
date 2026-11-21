# 8.0 문서 에이전트 명령 마이그레이션 가이드

`python-hwpx-automation` 8.0에서 `apply_document_commands`의 명령이 `hwpx.agent-command/v2`로,
블루프린트가 `hwpx.agent-blueprint/v2`로 올랐다. 서버 쪽 정본은 automation 저장소의
`docs/agent-command-v2.md`와 `docs/tool-contract-delta-8.0.0.json`이다.

## 무엇이 바뀌었나

글을 다루는 단위가 "런(글자 모양이 같은 조각)의 차례"에서 **문단 글의 글자 자리**로 바뀌었다.
글자 자리는 `paragraph.text`로 센다(탭·줄바꿈은 1, 컨트롤·개체는 0).

| 하는 일 | 7.x(v1) | 8.0(v2) |
|---|---|---|
| 문단 중간에 글 넣기 | 런 add + `index` | `{"op":"add","kind":"text","parent":<문단>,"position":{"mode":"offset","offset":3},"properties":{"text":"…"}}` |
| 글 일부 지우기 | 런 remove | `{"op":"remove","path":"<문단>/text[3:5]"}` |
| 글 일부 옮기기·복사 | 런 copy | `{"op":"move"|"copy","path":"<문단>/text[3:5]","parent":<문단>,"position":{"mode":"offset","offset":0}}` |
| 표·그림·도형·각주 자리 | 같은 종류 형제 사이 `index`/`before`/`after` | `{"mode":"offset","offset":n}`, 또는 같은 문단 개체의 `before`/`after` |
| 각주·미주 | set·remove·copy | set·add·remove·move·copy |

결과의 `place`(`paragraph`·`offset`·`length`)가 바뀐 노드가 문단 글의 어디에 있는지 알려 준다.
`get_document_node`의 런·개체 노드 `summary.place`로 자리를 읽는다.

## 안내 오류 `contract_changed`

뜻이 바뀐 옛 꼴은 조용히 다르게 처리하지 않고 `contract_changed`로 거부한다.
`suggestion`에 새 꼴이 실려 있으므로 그대로 고쳐 다시 보낸다.

- 런 add·remove·copy
- 문단 안 개체·글의 `"mode": "index"`
- `before`/`after`가 런 경로를 가리킴
- v1 명령에 v2 꼴이 섞임
- v1 명령의 문단 안 `append`/`prepend` 가운데 옛 자리와 새 자리가 다른 것

문단·표·칸·행·누름틀·메모 명령과 런 `set`은 그대로 된다.

## 블루프린트

덤프는 v2만 쓴다. v1 블루프린트(`.hwpxbp`)는 그대로 재생된다. 서버가 읽어 v2로 올리고
`verificationReport.upgradedFrom`에 적는다.
