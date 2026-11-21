# 7.0.0 / 8.0.0 / 8.0.0 공개 설치 관찰

2026-11-21 KST에 [`python-hwpx 7.0.0`](https://github.com/airmang/python-hwpx/releases/tag/v7.0.0), [`python-hwpx-automation 8.0.0`](https://github.com/airmang/python-hwpx-automation/releases/tag/v8.0.0), 호환 배포판 `hwpx-mcp-server 8.0.0`, [`hwpx-plugin 8.0.0`](https://github.com/airmang/hwpx-plugins/releases/tag/v8.0.0)의 공개 발행을 확인했다. 릴리스 태그는 `release-approved` 스냅샷을 보존하며, `released` 승격은 이 후속 커밋에만 기록한다. 시각은 UTC다.

## 발행

- **core** — `v7.0.0` 태그(main `2e451dea`)의 릴리스 워크플로가 성공했고, GitHub Release는 2026-11-20T17:31:47Z에 게시되었다. [PyPI](https://pypi.org/project/python-hwpx/7.0.0/) 파일의 SHA-256:
  - `python_hwpx-7.0.0-py3-none-any.whl` `9dcb2fe77298284fd6593e71a8092ee032d50801b31f9f30791ef0ceeefc968d`
  - `python_hwpx-7.0.0.tar.gz` `48a05bbefcdb6fff73b9650c1e835b0b7fe5417f17190129978b748c754f0eee`
- **automation** — `v8.0.0` 태그(`add7f69`)의 릴리스 워크플로가 성공했고, GitHub Release는 2026-11-21T00:17:31Z에 게시되었으며 플러그인 인계 영수증 `python-hwpx-automation-v8.0.0-plugin-handoff.json`이 붙어 있다. 정식·호환 배포판은 각각 [PyPI](https://pypi.org/project/python-hwpx-automation/8.0.0/)와 [PyPI](https://pypi.org/project/hwpx-mcp-server/8.0.0/)에서 확인했다. SHA-256:
  - `python_hwpx_automation-8.0.0-py3-none-any.whl` `216df98c6c1ad300f6813a04da241c32b9a1d3d5778cf9a2219b90c2ad767590`
  - `python_hwpx_automation-8.0.0.tar.gz` `69287874694067795420b7df61d64d1f670d40f324d600c6d7142d6fffa3f460`
  - `hwpx_mcp_server-8.0.0-py3-none-any.whl` `e874f212c6944c5fcac9f27469d895356b3e18bf1a93198325259da8f2824f6e`
  - `hwpx_mcp_server-8.0.0.tar.gz` `c300c238e159cd912ad57cfe870ef2abadb7dea5b32990e572edf50655f0b6f7`
- **plugin** — 이 저장소의 main `3285df0`에서 `plugins-dist` 워크플로가 번들을 `plugins-dist` 가지(커밋 `0307ea1`, 파일 661개, 커밋 하나)로 내보내고 `hwpx-plugin--v8.0.0` 태그를 달았다. 게시된 트리는 먼저 설치 시험을 거친 로컬 빌드와 바이트 단위로 같다. marketplace 저장소 [airmang/hwpx-plugins](https://github.com/airmang/hwpx-plugins) main(`87fcd8f`)은 이제 목록만 담으며, 두 호스트 항목 모두 이 저장소의 `plugins-dist` 가지를 가리키는 `git-subdir` 원천(`claude/hwpx-plugin`, `./codex/hwpx-plugin`)이다.

## 실제 marketplace 설치

macOS에서 격리한 설정 디렉터리로 공개 marketplace를 새로 추가해 설치했다.

- Claude Code 2.1.328: `claude plugin marketplace add airmang/hwpx-plugins` → `claude plugin install hwpx-plugin@hwpx`
- codex-cli 0.167.0: `codex plugin marketplace add airmang/hwpx-plugins` → `codex plugin add hwpx-plugin@hwpx`

두 호스트 모두 8.0.0을 설치했다. 각 설치본에서 띄운 MCP 서버는 `python-hwpx-automation 8.0.0`, `python-hwpx 7.0.0`, 스킬 번들 8.0.0, 도구 **128개**를 보고했다. Claude 설치본의 잠긴 런타임에서 읽은 도구 계약 해시는 **`c895883d5f4350ae`**다. 기존 2.4.0 설치본을 8.0.0으로 올리는 갱신도 두 호스트에서 관찰했다(`claude plugin marketplace update hwpx && claude plugin update hwpx-plugin@hwpx`, `codex plugin marketplace upgrade && codex plugin add hwpx-plugin@hwpx`).

이 저장소의 맨 위 설치 목록으로도 같은 번들이 설치된다. 같은 두 호스트(Claude Code 2.1.328, codex-cli 0.167.0)에서 격리한 설정으로 `airmang/python-hwpx-automation`을 marketplace로 추가해 `hwpx-plugin@hwpx` 8.0.0이 설치되는 것을 관찰했다.

## 관찰하지 않은 것

Windows 호스트, OpenClaw·Hermes 설치, 플러그인을 거친 한컴 렌더는 이번에 관찰하지 않았다. 저장·설치 성공만으로 시각 검토나 제출 적합성을 보증하지 않는다.
