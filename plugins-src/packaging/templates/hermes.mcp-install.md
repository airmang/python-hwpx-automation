# HWPX skill + MCP server for Hermes Agent

This directory is a publishable Hermes skill (`SKILL.md` plus `scripts/` and `references/`).
Hermes loads MCP servers from `config.yaml`, not from the skill, so register the HWPX MCP
server there.

## Publish the skill

```bash
hermes skills publish plugins/hermes/hwpx --to github --repo airmang/hwpx-plugins
```

## Register the MCP server in `config.yaml`

```yaml
mcp_servers:
  hwpx-mcp-server:
    command: uvx
    args: ["--refresh-package", "hwpx-mcp-server", "--refresh-package", "python-hwpx", "--from", "hwpx-mcp-server==2.23.0", "hwpx-mcp-server"]
    env:
      HWPX_MCP_ADVANCED: "0"
      HWPX_MCP_AUTOBACKUP: "1"
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

## Private practice campaign (opt-in)

The Leap B campaign runner additionally requires `HWPX_CORPUS_SOURCE`,
`HWPX_PRACTICE_ROOT`, and `HWPX_SKILL_ROOT` in the private MCP host environment.
Inject their local values through the host configuration or secret store; never put
them in tool arguments, prompts, receipts, or published plugin files. The source root
must stay read-only and separate from the mutable practice root. This configuration
enables local execution only; it does not authorize publication, adoption, merge, or release.
