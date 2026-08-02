# HWPX skill + MCP server for Hermes Agent

This directory is a publishable Hermes skill (`SKILL.md` plus `scripts/` and `references/`).
Hermes loads MCP servers from `config.yaml`, not from the skill, so register the HWPX MCP
server there.

## Candidate publishing command (do not run before release approval)

The `1.6.0 / 6.6.1 / 5.6.0` coordinates below are an unpublished candidate.
The current public stack remains `0.8.0 / 5.1.0 / 4.2.0`.

```bash
hermes skills publish plugins/hermes/hwpx --to github --repo airmang/hwpx-plugins
```

## Register the MCP server in `config.yaml`

```yaml
mcp_servers:
  hwpx:
    command: uvx
    args: ["--refresh-package", "python-hwpx-automation", "--refresh-package", "python-hwpx", "--with", "python-hwpx[preview]==5.6.0", "--from", "python-hwpx-automation[mcp,oracle]==6.6.1", "hwpx-automation-mcp"]
    env:
      HWPX_AUTOMATION_ADVANCED: "0"
      HWPX_AUTOMATION_AUTOBACKUP: "1"
      HWPX_SKILL_VERSION: "1.0.0"
      HWPX_AUTOMATION_WORKSPACE_ROOTS: '["/absolute/path/to/workspace"]'
```

## Local development checkout

```yaml
mcp_servers:
  hwpx:
    command: /absolute/path/to/hwpx-plugins/packaging/templates/hwpx-automation-mcp
    env:
      HWPX_AUTOMATION_REPO: /absolute/path/to/python-hwpx-automation
      PYTHON_HWPX_REPO: /absolute/path/to/python-hwpx
```

The launcher uses editable checkouts only when both repository paths are
explicitly configured. This prevents candidate checks from silently selecting
an unrelated sibling checkout. `HWPX_MCP_SERVER_REPO` remains a 6.x
compatibility alias. New configurations use the host-local key `hwpx`; an
existing `hwpx-mcp-server` key remains valid through 6.x but is not the FastMCP
protocol identity.
List additional absolute roots in `HWPX_AUTOMATION_WORKSPACE_ROOTS` only when they are
intentionally authorized.
