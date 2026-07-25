# 낯선 HWPX 구조 탐색·원자 편집 — agent document interface

## 언제 이 경로를 쓰나

처음 보는 기존 HWPX에서 제목·문단·표·셀·누름틀·그림 같은 구조를 먼저 이해한 뒤, 서로 다른
종류의 변경, 기존 단순 머리글 story 편집, 블록 이동·복사를 **한 번에 전부 성공하거나 전부 취소**해야
할 때 쓴다.

다음은 기존 전문 경로가 우선이다.

- 평가계획: `apply_evalplan_fill`; 처음 보는 mixed 양식: `analyze_form_fill` →
  `apply_form_fill` → `verify_form_fill`
- 시험지, PII, 메일머지, 변경추적, 직인, 문서 생성, lint/repair: 각 전용 workflow/tool
- 이미 paragraph index나 anchor가 확정된 단건 편집: 가장 작은 전용 도구; 여러 canonical
  path 또는 본문·표 셀·기존 단순 머리글 story의 이종 편집: `apply_document_commands`

generic 명령은 raw XML, XPath, package part, 임의 속성을 받지 않는다. 전문 도구가 만드는 도메인
영수증을 generic 성공으로 대체하지 않는다.

## 세 도구

1. `get_document_node(filename, path="/", depth, child_limit, expected_revision)`
   - bounded semantic tree, canonical `path`, `stableId`, `stability`/`volatilePath`, 지원 속성·연산,
     `revision`, unsupported/truncated coverage를 반환한다.
2. `query_document_nodes(filename, selector, limit, node_depth, child_limit, expected_revision)`
   - 알려진 kind/속성, 정확 일치, `:contains()`, direct-child `>`만 허용한다.
3. `apply_document_commands(filename, output, commands, expected_revision, idempotency_key, dry_run,
   quality, verification_requirements, overwrite)`
   - `set`, `add`, `remove`, `move`, `copy`를 한 working document에 순서대로 적용하고 한 번 저장한다.

selector 예:

```text
paragraph[style="개요 1"]:contains("평가")
section > paragraph[type="normal"]
table[id="123"] > row > cell:contains("합계")
```

`limit`는 반드시 지정하고, query 결과가 여러 개인 상태에서 임의로 첫 항목을 고르지 않는다. 정확한
문맥을 더해 다시 query하거나 각 후보를 `get_document_node`로 읽어 **한 canonical path**를 확정한다.
`volatilePath=true`인 대상은 같은 revision에서만 쓰고, 문서가 바뀌면 다시 탐색한다.

### 기존 머리글 story의 command-only 경로

현재 공개 릴리스는 public view/query node catalog를 늘리지 않고, `set` command에서만 다음 두 경로를
인식한다.

```text
/section[1]/header[@page-type="BOTH"]
/section[2]/header[@id="1153630576"]
```

대상은 문서에 이미 존재하며 selector가 정확히 하나와 일치하는 단순 텍스트 머리글이어야 한다.
수정 가능한 속성은 `text` 하나다. 머리글 생성, footer, `add`/`remove`/`move`/`copy`, rich run,
쪽번호·필드·그림·기타 control이 있는 story는 generic 경로로 단순화하지 않고 fail-closed한다.
그런 작업은 `set_header_footer` 같은 전용 도구를 쓰거나 사람 검토로 넘긴다.

## 표준 루프

1. `mcp_server_health()`에서 tool surface와 capability가 정상인지 확인한다.
2. `get_document_node(..., path="/", depth=2)`로 구조와 `revision`을 얻는다.
3. `query_document_nodes(..., limit=<bounded>)`로 후보를 좁히고 canonical path를 확정한다.
4. 입력과 다른 `output`에 한 batch를 `dry_run=true`로 실행한다. dry-run 전용 idempotency key를 쓴다.
5. `semanticDiff`, 각 `commandResults`, `rolledBack`, `verificationReport`를 검토한다.
6. 동일 commands를 `dry_run=false`, 새 commit용 idempotency key, 같은 `expected_revision`으로 실행한다.
7. `ok == true`, `rolledBack == false`, 선언한 verification layer와
   `verificationReport.openSafety.ok == true`를 확인한다. 머리글 story가 있으면
   `verificationReport.storyPreservation.ok == true`, `storyCount`, `stories[].stableId`,
   `textMatched == true`까지 확인한다.

dry-run과 commit은 request hash가 다르므로 **같은 idempotency key를 재사용하지 않는다**. commit 재시도만
같은 key를 사용한다. `expected_revision` 불일치는 다시 읽고 외부 변경을 검토한 뒤 새 revision으로
재시도한다. 원본 직접 덮어쓰기는 피하고 `overwrite=false`를 기본으로 둔다.

## 원자 batch 예

```json
{
  "filename": "input.hwpx",
  "output": "output.hwpx",
  "commands": [
    {
      "commandId": "renameHeading",
      "op": "set",
      "path": "/section[1]/paragraph[id=\"101\"]",
      "properties": {"text": "수정된 평가 계획", "alignment": "CENTER"}
    },
    {
      "commandId": "copyBlock",
      "op": "copy",
      "path": "/section[1]/paragraph[id=\"102\"]",
      "parent": "/section[1]",
      "position": {"mode": "append"}
    },
    {
      "commandId": "fillCell",
      "op": "set",
      "path": "/section[1]/paragraph[id=\"103\"]/table[id=\"201\"]/row[1]/cell[2]",
      "properties": {"text": "서술형 평가"}
    },
    {
      "commandId": "renameExistingHeader",
      "op": "set",
      "path": "/section[1]/header[@page-type=\"BOTH\"]",
      "properties": {"text": "2026학년도 평가 운영 계획"}
    }
  ],
  "expected_revision": "sha256:<64 hex>",
  "idempotency_key": "commit-unique-key",
  "dry_run": false,
  "quality": "transparent",
  "verification_requirements": [
    "package", "reopen", "openSafety", "semanticDiff", "bytePreservation"
  ],
  "overwrite": false
}
```

앞 명령이 만든 노드는 뒤 명령에서 `$renameHeading.path` 또는 `$copyBlock.path`처럼 참조할 수 있다.
copy 결과의 `generatedIdentities`와 반환된 새 path를 사용하고 ID를 추측하지 않는다.

## 실패 처리

- `ambiguous_target`, `not_found`: 후보를 다시 읽고 고유 path를 확정한다.
- `stale_revision`, `volatile_target`: 현재 문서를 다시 view/query한다.
- `unknown_property`, `unsupported_operation`, `incompatible_parent`: 노드의
  `editableProperties`·`operations`와 shared catalog를 확인한다.
- `identity_collision`, `invariant_violation`, `unsupported_content`: generic 우회를 시도하지 말고
  전문 도구 또는 사람 검토로 넘긴다.
- 기존 머리글 경로의 `invalid_syntax`: 설치 core/MCP/skill 버전을 health에서 다시 확인한다.
  설치 조합이 계약과 맞는지 `mcp_server_health()`의 버전·계약 해시로 확인한다.
- `verification_failed`, `verificationReport.openSafety.ok != true`, `rolledBack == true`: 산출물을 제출하지 않는다.

로컬 `render_preview`는 근사 검수다. real-Hancom이 요구된 작업은 `render_health` → `render_submit` →
`render_status`의 일치하는 영수증 없이는 시각 완료로 주장하지 않는다.

## CLI 재현

MCP에서 확정한 batch는 공유 코어 계약의 JSON 파일로 보관할 수 있다. 독립 실행은 다음처럼 한다.

```bash
hwpx view input.hwpx --depth 2 --format json
hwpx query input.hwpx 'paragraph:contains("평가")' --limit 20 --format json
hwpx batch commands.json --format json
```

JSONL command-only 입력은 `hwpx batch - --jsonl-input --input input.hwpx --output output.hwpx`로 한 원자
batch가 된다. CLI 도움말과 MCP command schema는 같은 core catalog에서 생성된다.
