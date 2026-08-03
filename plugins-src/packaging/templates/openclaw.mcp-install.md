# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Unpublished candidate wiring

The source checkout carries the exact `6.0.0 / 7.0.0 / 2.0.0` candidate pins
below for pre-release verification. They are not the current public marketplace
release.

```json
{
  "hwpx": {
    "command": "uvx",
    "args": ["--refresh-package", "python-hwpx-automation", "--refresh-package", "python-hwpx", "--with", "python-hwpx[preview]==6.0.0", "--from", "python-hwpx-automation[mcp,oracle]==7.0.0", "hwpx-automation-mcp"],
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
