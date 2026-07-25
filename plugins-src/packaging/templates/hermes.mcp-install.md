# HWPX skill + MCP server for Hermes Agent

This directory is a publishable Hermes skill (`SKILL.md` plus `scripts/` and `references/`).
Hermes loads MCP servers from `config.yaml`, not from the skill, so register the HWPX MCP
server there.

## Publish the released skill

The `1.0.0 / 6.0.0 / 5.0.0` coordinates below are the public release stack.
The publish command and MCP entry retain those exact public-package pins.

```bash
hermes skills publish plugins/hermes/hwpx --to github --repo airmang/hwpx-plugins
```

## Register the MCP server in `config.yaml`

```yaml
mcp_servers:
  hwpx-mcp-server:
    command: uvx
    args: ["--refresh-package", "python-hwpx-automation", "--refresh-package", "python-hwpx", "--with", "python-hwpx[visual,preview]==5.0.0", "--from", "python-hwpx-automation[mcp]==6.0.0", "hwpx-mcp-server"]
    env:
      HWPX_MCP_ADVANCED: "0"
      HWPX_MCP_AUTOBACKUP: "1"
      HWPX_SKILL_VERSION: "0.7.0"
      HWPX_MCP_WORKSPACE_ROOTS: '["/absolute/path/to/workspace"]'
```

## Local development checkout

```yaml
mcp_servers:
  hwpx-mcp-server:
    command: /absolute/path/to/hwpx-plugins/packaging/templates/hwpx-mcp-server
    env:
      HWPX_MCP_SERVER_REPO: /absolute/path/to/hwpx-mcp-server
      PYTHON_HWPX_REPO: /absolute/path/to/python-hwpx
```

The launcher discovers sibling `hwpx-mcp-server` and `python-hwpx` checkouts automatically when
the env vars are unset and the repos sit under a common parent.
List additional absolute roots in `HWPX_MCP_WORKSPACE_ROOTS` only when they are
intentionally authorized.
