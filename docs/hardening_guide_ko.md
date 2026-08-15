# python-hwpx-automation 하드닝 가이드

> 릴리스 상태: `released` (2026-08-02) — 공개 트레인 `python-hwpx 5.5.0 → python-hwpx-automation 6.5.1 → hwpx-plugin 1.5.0` 기준 문서입니다.

> 아래 5.0/6.0/1.0 좌표는 `released` 공개 트레인입니다(2026-07-28):
> core 5.0.1 / `python-hwpx-automation` 6.0.4 / plugin 1.0.0. 직전 공개
> 트레인은 core 4.2.0 / `hwpx-mcp-server` 5.1.0 / plugin 0.8.0, 계약 해시
> `429cb6706323e762`였습니다.

## 공개 계약과 프로필

- 도구 등록, 입력·출력 스키마, health/capability 표면과 생성 문서는 하나의
  `ToolSpec` 레지스트리에서 만들어집니다. `python-hwpx-automation` 6.0.4는
  기본 119개, 고급 모드 포함 127개 도구와 28개 skill-required 도구를 유지하며
  계약 해시는 `0ce938371f0b55a6`입니다. 최소 좌표는 core `5.0.0`,
  automation `6.0.0`, skill `1.0.0`입니다.
- 4.0.0의 `f46ec677231b3a20`, 4.1.0의 `c127914cc3f4480e`, 4.2.1의 `fff2c9093ca4677b`,
  4.3.0의 `f82caecbcfc742e9`, 4.4.x의 `c89cbc5f98eb5367`는 역사적 계약입니다. 최소
  버전 좌표도 canonical payload에 포함되므로 도구 이름·순서·스키마가 같더라도 다른
  릴리스 해시와 섞어 쓰면 안 됩니다. `mcp_server_health`가 좌표나 해시 skew를
  보고하면 쓰기를 진행하지 마세요.
- 스키마는 JSON Schema 2020-12 기준이며 `$defs`, `$ref`, `anyOf`를 사용할 수
  있습니다. 실제 호스트에 노출되는 계약은 `docs/tool-contract.generated.json`과
  `docs/tool-contract.md`에서 확인합니다.
- 기본 프로필을 운영 표면으로 사용하세요. package inspection과 저수준 검증
  도구가 꼭 필요한 경우에만 `HWPX_AUTOMATION_ADVANCED=1`을 설정하고 호스트를 다시
  시작합니다. 기존 `HWPX_MCP_ADVANCED=1`도 6.x fallback으로 지원합니다.
- `plan_edit` → `preview_edit` → `apply_edit`와 `analyze_quality_generation` /
  `apply_quality_generation`는 5.0.0 major 경계에서 **제거**되었습니다(별칭·유령
  래퍼 없음). 신규 자동화는 `apply_document_commands`, 문서 생성은
  `create_document_from_plan`(+ `inspect_document_quality`)을 사용합니다. 존재하지
  않는 `HWPX_MCP_HARDENING`, `search`, `get_context` 도구에 의존하면 안 됩니다.

## 작업공간·네트워크 경계

- `HWPX_AUTOMATION_WORKSPACE_ROOTS`에는 허용할 절대 디렉터리를 JSON 배열로
  지정합니다. 기존 `HWPX_MCP_WORKSPACE_ROOTS`는 6.x fallback입니다.
  상대경로는 첫 root를 기준으로 해석되고, 절대경로는 나열된 root 중 하나에 속해야
  합니다. traversal, workspace 밖 경로, symlink escape는 정형 MCP 오류로
  거부됩니다.
- 변수를 생략하면 서버 프로세스의 시작 cwd 하나만 workspace로 사용합니다. 호스트가
  cwd를 명확히 보장하지 못한다면 환경 변수를 명시하세요. filesystem root(`/`) 자체는
  허용할 수 없습니다.
- macOS와 `renameat2`를 제공하는 Linux의 canonical mixed-form 및 byte-preserving
  form 게시 경로는 root/parent descriptor와 대상 byte·identity·mode snapshot으로
  동시 parent/target 교체를 검사하고, 실패 시 소유한 후보만 제거·원복합니다.
- Windows와 원자 교환 primitive가 없는 기타 POSIX fallback은 후보의 실제 관측
  mode와 게시 전후 identity를 검사하고 정상 실패 시 소유 후보를 원복합니다. 다만
  handle-relative 원자 교환은 제공하지 않으므로 workspace를 신뢰된 로컬 디렉터리로
  두고 ACL 또는 호스트 sandbox로 같은 사용자 권한의 동시 reparse/rename을
  차단해야 합니다.
- URL 입력, HTTP document storage, 원격 render transport는 기본적으로 HTTPS와 공개
  주소만 허용합니다. DNS 결과 전체, redirect 대상, 실제 연결 피어를 각각 검사합니다.
  `HWPX_AUTOMATION_ALLOW_PRIVATE_NETWORK=1`은 신뢰된 사설/루프백 HTTPS
  서비스가 반드시 필요한 경우에만 사용하며 링크로컬·metadata·예약 주소는
  계속 차단됩니다. 기존 `HWPX_MCP_ALLOW_PRIVATE_NETWORK`는 6.x fallback입니다.

## 저장·검증 경계

- 일반 문서 저장은 capability handshake와 `SavePipeline`을 사용합니다. `quality`를
  받는 도구는 transparent 또는 strict 정책에 따른 `visualComplete` 결과를
  반환합니다.
- `byte_preserving_patch`, `apply_table_ops`, `apply_body_ops`,
  `apply_evalplan_fill`은 untouched package byte를 지키기 위한 명시적 carveout입니다.
  guarded publication, open-safety, byte/member diff와 공통 verification receipt를
  사용하며 전체 `visualComplete` 렌더를 주장하지 않습니다.
- `apply_document_commands`의 다중 story 트랜잭션은 본문, 표 셀, 기존 구역의
  단순 `BOTH` 머리글을 같은 revision과 직렬화에 묶습니다. rich/control 머리글은
  평탄화하지 않고 fail-closed로 거부하며, 실패 시 부분 출력이 없어야 합니다.
- canonical mixed-form 분석과 dry-run은 출력 상위 디렉터리를 만들지 않습니다. 적용과
  검증은 source/output revision, inode, mode 및 정확한 publication token을 다시
  확인하며 외부가 바꾼 파일은 같은 바이트여도 원복하거나 덮어쓰지 않습니다.
- 기존 파일을 바꾸는 form/byte-preserving 트랜잭션은 첫 게시 전에 같은 workspace에
  예측 불가능한 이름의 exact recovery sidecar를 예약합니다. 최종 identity 검증까지
  성공한 경우에만 guarded cleanup하며, 실패·외부 경합 시에는 외부 파일을 건드리지
  않고 원본 바이트 복구본을 남깁니다. 운영자는 실패 조사와 복구가 끝난 뒤에만 해당
  `.recovery` 파일을 정리해야 합니다.
- capability skew는 기본적으로 쓰기를 fail-closed로 막습니다. 진단 목적의
  `HWPX_AUTOMATION_REQUIRE_CAPABILITY=0`은 계약 불일치를 이해한 운영자만
  제한적으로 사용해야 합니다. 기존 `HWPX_MCP_REQUIRE_CAPABILITY`은 6.x
  fallback입니다.

## 오류와 운영 점검

- 실패 응답은 `hwpx.mcp-error/v1`의 `code`, `category`, `retryable`, `suggestion`을
  사용하며 원래 인자나 로컬 절대경로를 노출하지 않습니다.
- 시작 후 `mcp_server_health`에서 `capability.ok`, `toolSurface`와 계약 해시를
  확인하고, `describe_capabilities`로 현재 프로필의 작업군과 진입점을 확인합니다.
- 릴리스 검증은 `.venv/bin/pytest -q`, `.venv/bin/ruff check src tests`,
  `.venv/bin/python scripts/render_tool_contract.py --check --skip-skill`,
  `.venv/bin/python scripts/render_contract_delta.py --check`,
  `.venv/bin/python scripts/check_public_hygiene.py`,
  `.venv/bin/python scripts/run_conformance.py run --tier structural
  --check tests/conformance/golden/structural.json`를 모두 통과해야 합니다. 공개 합성
  코퍼스의 생성기는 `python scripts/conformance_corpus_build.py`이며 출력은
  `scripts/conformance/corpus`입니다.


> 릴리스 상태 참고: 현재 공개 트레인은 python-hwpx 6.1.0 · python-hwpx-automation 7.0.1 · hwpx-plugin 2.0.0입니다 (python-hwpx 6.1.0 released 2026-08-15, core-only 트레인).
