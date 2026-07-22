# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Pinned public release

Add an MCP server entry that runs the exact released packages with `uvx`:

```json
{
  "hwpx-mcp-server": {
    "command": "uvx",
    "args": ["--refresh-package", "hwpx-mcp-server", "--refresh-package", "python-hwpx", "--with", "python-hwpx[visual,preview]==4.2.0", "--from", "hwpx-mcp-server==5.1.0", "hwpx-mcp-server"],
    "env": {
      "HWPX_MCP_ADVANCED": "0",
      "HWPX_MCP_AUTOBACKUP": "1",
      "HWPX_SKILL_VERSION": "0.8.0",
      "HWPX_MCP_WORKSPACE_ROOTS": "[\"/absolute/path/to/workspace\"]"
    }
  }
}
```

These coordinates describe the public S-080 release stack.

## Local development checkout

If you have local `hwpx-mcp-server` and `python-hwpx` checkouts, point the command at the
bundled launcher and let it resolve them, or set the repo env vars:

```bash
export HWPX_MCP_SERVER_REPO=/absolute/path/to/hwpx-mcp-server
export PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx
```

The skill itself loads from `./skills` as declared in `openclaw.plugin.json`.
Use more than one absolute entry in `HWPX_MCP_WORKSPACE_ROOTS` only when the
agent must work across explicitly authorized directories.
