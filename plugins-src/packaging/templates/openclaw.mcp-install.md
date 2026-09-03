# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Unpublished candidate wiring

The source checkout carries the exact `6.3.0 / 7.0.3 / 2.1.0` public pins
below for pre-release verification. They are not the current public marketplace
release.

```json
{
  "hwpx": {
    "command": "uvx",
    "args": ["--with", "python-hwpx[preview]>=6.3.0,<7", "--from", "python-hwpx-automation[mcp,oracle]>=7.0.3,<8", "hwpx-automation-mcp"],
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

`uvx`는 처음 해석한 버전 조합을 캐시하고 스스로 갱신하지 않습니다. 같은 메이저 안의 최신으로 옮기려면 `uvx --refresh --with "python-hwpx[preview]>=6.3.0,<7" --from "python-hwpx-automation[mcp,oracle]>=7.0.3,<8" hwpx-automation-mcp --help`를 한 번 실행합니다. 자동 갱신은 번들 런처 `scripts/hwpx-automation-mcp`(Claude Code·Codex 번들) 경로만 제공합니다.

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
