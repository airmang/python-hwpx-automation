# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Published package (recommended)

Add an MCP server entry that runs the pinned package with `uvx`:

```json
{
  "hwpx-mcp-server": {
    "command": "uvx",
    "args": ["--from", "hwpx-mcp-server==2.3.1", "hwpx-mcp-server"],
    "env": { "HWPX_MCP_ADVANCED": "0", "HWPX_MCP_AUTOBACKUP": "1" }
  }
}
```

## Local development checkout

If you have local `hwpx-mcp-server` and `python-hwpx` checkouts, point the command at the
bundled launcher and let it resolve them, or set the repo env vars:

```bash
export HWPX_MCP_SERVER_REPO=/absolute/path/to/hwpx-mcp-server
export PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx
```

The skill itself loads from `./skills` as declared in `openclaw.plugin.json`.
