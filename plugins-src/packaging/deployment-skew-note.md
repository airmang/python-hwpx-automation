# HWPX Plugin Deployment Skew Note

## Symptom

A host session can show an old MCP surface, for example about 37 tools, while
the current server checkout exposes the full surface. Current expected counts
are reported by `mcp_server_health().toolSurface`.

## Likely Causes

- The host is still using a legacy `.hwpx-mcp-server-venv`, or a runtime whose
  package/Python fingerprint does not match the current bundle.
- The host loaded a cached plugin bundle before a marketplace/plugin reinstall.
- The host session was not restarted after installing the plugin, so newly
  generated skills and MCP tool schemas were not reloaded.
- The launcher did not expose the skill bundle version to the server, making
  skew invisible to the agent.

## Reproduction Check

In a fresh host session with the plugin installed, call:

```json
{"tool": "mcp_server_health", "arguments": {}}
```

Expected:

- `toolSurface.status == "ok"`
- `toolSurface.actualFastMcpToolCount >= toolSurface.expectedFastMcpToolCount`
- `toolSurface.missingKeyTools == []`
- `version`, `pythonHwpxVersion`, and `skillBundleVersion` are present

Current launchers store immutable, fingerprinted environments under
`.hwpx-mcp-runtime/envs/`; concurrent cold starts share an installation lock and
never replace a valid environment in place. If skew is reported, reinstall the
plugin and start a fresh host session. A legacy `.hwpx-mcp-server-venv` can be
archived after confirming that no older plugin installation uses it.
