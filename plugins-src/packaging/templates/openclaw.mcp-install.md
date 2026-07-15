# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Published package (recommended)

Add an MCP server entry that runs the pinned package with `uvx`:

```json
{
  "hwpx-mcp-server": {
    "command": "uvx",
    "args": ["--refresh-package", "hwpx-mcp-server", "--refresh-package", "python-hwpx", "--with", "python-hwpx[visual]==2.29.2", "--from", "hwpx-mcp-server==2.23.1", "hwpx-mcp-server"],
    "env": {
      "HWPX_MCP_ADVANCED": "0",
      "HWPX_MCP_AUTOBACKUP": "1",
      "HWPX_SKILL_VERSION": "0.1.31",
      "HWPX_MCP_WORKSPACE_ROOTS": "[\"/absolute/path/to/workspace\"]"
    }
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
Use more than one absolute entry in `HWPX_MCP_WORKSPACE_ROOTS` only when the
agent must work across explicitly authorized directories.

## Private practice campaign (opt-in)

The Leap B campaign runner additionally requires `HWPX_CORPUS_SOURCE`,
`HWPX_PRACTICE_ROOT`, and `HWPX_SKILL_ROOT` in the private MCP host environment.
Inject their local values through the host configuration or secret store; never put
them in tool arguments, prompts, receipts, or published plugin files. The source root
must stay read-only and separate from the mutable practice root. This configuration
enables local execution only; it does not authorize publication, adoption, merge, or release.
