# Typed blueprint dump/replay — 문서 블록 이식

## 언제 이 경로를 쓰나

지원되는 HWPX 문서 전체 또는 결재·양식 블록을 versioned typed semantic blueprint로 덤프하고,
스타일·글자속성·번호매기기·그림·참조·ID 충돌이 있는 다른 HWPX에 원자적으로 이식할 때 쓴다.
이 경로는 raw XML 복사, 세션형 편집기, watch, OfficeCLI adapter가 아니다.

양식 채움, 시험지 조판, 메일머지, PII, 공문 lint처럼 더 풍부한 도메인 검증이 있는 작업은 기존
전문 workflow를 유지한다. blueprint replay가 전문 workflow의 증거를 대신하지 않는다.

## 1. source와 target 경로 확정

1. `get_document_node(filename, path="/", depth=2)`로 source의 `revision`과 bounded 구조를 읽는다.
2. `query_document_nodes`로 후보를 좁히고 유일한 canonical path를 고른다. 여러 후보 중 첫 항목을
   임의 선택하지 않고, `volatilePath`는 다른 revision에서 재사용하지 않는다.
3. target도 별도로 읽어 `targetParent`, 삽입 위치, `expectedRevision`을 확정한다.

## 2. deterministic dump

교차 문서 이식은 기본 `portable`, 동일 source fingerprint에 종속된 exact replay만 `source-bound`다.
덤프 도구는 `dump_document_blueprint`, 재생 도구는 `replay_document_blueprint`다.

```text
dump_document_blueprint(
  filename=<source.hwpx>,
  path=<source canonical path>,
  mode="portable",
  expected_revision=<source revision>,
  output=<block.hwpxbp>,
  require_replayable=true,
  include_manifest=true
)
```

반드시 다음을 확인한다.

- 동일 source bytes/path/mode/catalog의 bundle bytes와 `blueprintHash`가 반복 실행에서 동일하다.
- `unsupported == []`이고 manifest의 `fidelity.replayable == true`다.
- node, style/character, numbering, resource, reference 수가 예상 범위다.
- resource는 content-addressed allow-list 이미지뿐이며 외부 fetch가 없다.

inspection-only dump는 `require_replayable=false`로 만들 수 있지만 replay 입력으로 사용하지 않는다.

## 3. typed inspect/edit/repack

CLI의 안전 경로는 다음뿐이다.

```bash
hwpx dump --inspect block.hwpxbp > inspected.json
hwpx dump --repack block.hwpxbp --manifest edited-blueprint.json --output edited.hwpxbp
```

편집 가능한 것은 versioned typed manifest JSON뿐이다. ZIP을 직접 풀어 XML, namespace, package part,
asset path, native object를 넣지 않는다. repack은 원본 bundle을 먼저 완전 검증하고, canonical hash를
다시 계산하며, 검증된 content-addressed asset만 보존한다. raw XML 공개나 fallback은 없다.

문서에서 바로 bundle bytes를 stdout으로 넘겨야 할 때는 `hwpx dump ... --output -`를 쓸 수 있다.
replay request는 `hwpx replay -`로 stdin JSON을 받거나 파일로 전달한다.

## 4. atomic replay envelope

```json
{
  "schemaVersion": "hwpx.agent-blueprint-replay/v1",
  "bundle": {
    "filename": "block.hwpxbp",
    "blueprintHash": "sha256:<64 hex>"
  },
  "target": {
    "input": "target.hwpx",
    "output": "result.hwpx",
    "overwrite": false
  },
  "targetParent": "/section[1]",
  "position": {"mode": "append"},
  "mode": "portable",
  "mappingPolicy": {"strict": true},
  "expectedRevision": "sha256:<target revision>",
  "idempotencyKey": "new-key-for-this-attempt",
  "dryRun": true,
  "quality": "transparent",
  "verificationRequirements": [
    "package",
    "reopen",
    "openSafety",
    "semanticDiff",
    "bytePreservation"
  ]
}
```

`replay_document_blueprint(request=...)` 또는 `hwpx replay request.json`을 사용한다. 서버는 bundle과
전체 graph/catalog/hash를 target 접근 전에 검증하고, dependency mapping을 모두 preflight한 뒤 하나의
working document에서 구성한다. SavePipeline은 정확히 한 번 호출되고, 요청 output은 마지막 atomic
commit 전까지 바뀌지 않는다.

## 5. dry-run과 commit

1. 먼저 `dryRun=true`로 node map, dependency maps, semantic diff, fidelity를 검토한다.
2. strict mode에서는 `degraded` 또는 `unsupported` 하나라도 있으면 중단한다.
3. commit은 `dryRun=false`와 새 idempotency key로 실행한다.
4. 네트워크/호스트 재시도처럼 **동일 요청의 재전송에만** 같은 key를 쓴다. 내용을 바꾼 요청에 같은
   key를 쓰면 `idempotency_conflict`가 정상이다.

성공 영수증에서 다음을 모두 확인한다.

- `ok == true`, `rolledBack == false`;
- source-bound는 필요한 dependency가 모두 `exact`, portable은 허용된 `exact|mapped`만 존재;
- blueprint logical ID마다 target canonical path가 있고 dangling reference가 없음;
- `semanticDiff.ok`, `bytePreservation.ok`;
- package validation/reopen/reference/resource integrity와 `openSafety.ok`;
- `verificationReport.savePipeline.ok`와 선언한 domain 검증.

실패는 `rolledBack == true`여야 하며 기존 output sentinel/파일이 그대로여야 한다. `stale_revision`,
`identity_collision`, missing dependency, hash/catalog mismatch를 성공으로 우회하지 않는다.

## 6. 실제 한컴 검증

실제 한컴 검증이 요구되면 replay의 구조·openSafety 영수증만으로 완료하지 않는다.

1. `render_health`가 ready인지 확인한다.
2. 정확히 replay output hash를 `render_submit`한다.
3. `render_status`에서 Hancom build, input/output hash, PDF, 전체 페이지 PNG 수와 full-page 완료를 확인한다.
4. bundle/replay 영수증과 real-Hancom 영수증의 output hash가 같아야 한다.

oracle unavailable, page mismatch, damage warning, 일부 페이지만 확인한 상태는 `unverified`다. 로컬 preview나
LibreOffice 결과를 real-Hancom evidence로 승격하지 않는다.

## 7. 범위와 보안 경계

- `.hwpxbp` 허용 엔트리는 `blueprint.json`과 content-addressed image asset뿐이다.
- absolute/parent path, symlink, nested archive, executable, unknown entry, hash/MIME mismatch, 압축 폭탄은
  target 접근 전에 거부한다.
- schema/help/ToolSpec/skill/demo에 raw XML, namespace, package path, private coordinate, opaque native object를
  넣지 않는다.
- MCP는 stateless facade 두 개뿐이다. resident session, open/save/close lifecycle, watch, OfficeCLI adapter는
  이 workflow 범위 밖이다.
