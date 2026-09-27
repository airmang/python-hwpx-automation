# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Unpublished candidate wiring

The source checkout carries the exact `6.5.0 / 7.2.0 / 2.3.0` candidate coordinates
below for pre-release verification. They are not the current public marketplace
release.

## Install the server once

```bash
uv tool install --with "python-hwpx[preview]>=6.5.0,<7" "python-hwpx-automation[mcp,oracle]>=7.2.0,<8"
uv tool dir --bin
```

`uv tool install`은 `uv tool dir` 아래에 고정 가상환경 하나를 만들고, 두 번째 명령이 출력하는
디렉터리에 `hwpx-automation-mcp` 실행 파일을 둡니다. 호스트가 그 디렉터리를 `PATH`에 두지 않으면
아래 `command`에 그 절대 경로를 적습니다.

Then register it:

```json
{
  "hwpx": {
    "command": "hwpx-automation-mcp",
    "env": {
      "HWPX_AUTOMATION_ADVANCED": "0",
      "HWPX_AUTOMATION_AUTOBACKUP": "1",
      "HWPX_SKILL_VERSION": "1.0.0",
      "HWPX_AUTOMATION_WORKSPACE_ROOTS": "[\"/absolute/path/to/workspace\"]"
    }
  }
}
```

The current public stack remains `python-hwpx 4.2.0` /
`hwpx-mcp-server 5.1.0` / `hwpx-plugin 0.8.0`.

## Update and clean up

같은 메이저 안의 최신으로 옮기려면 `uv tool upgrade python-hwpx-automation`을 실행합니다. 설치할 때
준 범위(`>=7.2.0,<8`, `>=6.5.0,<7`)를 그대로 지키며 같은 가상환경을 제자리에서 갱신하고, 다음 서버
시작부터 적용됩니다. 자동 갱신은 번들 런처 `scripts/hwpx-automation-mcp`(Claude Code·Codex 번들)
경로만 제공합니다.

예전 안내처럼 `command`가 `uvx`인 설정은 버전 조합이 바뀔 때마다 uv 캐시에 임시 가상환경을 새로
만들고 옛 환경을 지우지 않습니다. 위 설치 방식으로 바꾼 뒤, 2.0.2 이하 템플릿으로 만든 설정의
`args`에 `--refresh`로 시작하는 인자(매 기동마다 패키지를 다시 받음)가 남아 있지 않은지도
확인하세요. 남은 임시 환경은 이 서버를 쓰는 모든 호스트 세션을 닫은 뒤 `uv cache prune`으로
회수합니다. 실행 중인 `uvx`가 캐시 잠금을 잡고 있으면 정리가 진행되지 않습니다.

## Local development checkout

If you have local `python-hwpx-automation` (or its pre-rename
`hwpx-mcp-server`) and `python-hwpx` checkouts, point the command at the bundled
launcher and set both canonical repository environment variables:

```bash
export HWPX_AUTOMATION_REPO=/absolute/path/to/python-hwpx-automation
export PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx
```

Use `hwpx` as the new host-local config key and
`scripts/hwpx-automation-mcp` as the launcher path. An existing
`hwpx-mcp-server` key or `scripts/hwpx-mcp-server` path may remain unchanged
through 6.x; neither key is the FastMCP protocol identity.

`HWPX_MCP_SERVER_REPO` remains a 6.x compatibility alias.

The skill itself loads from `./skills` as declared in `openclaw.plugin.json`.
Use more than one absolute entry in `HWPX_AUTOMATION_WORKSPACE_ROOTS` only when the
agent must work across explicitly authorized directories.
