# HWPX Plugin Deployment Skew Note

## Symptom

A host session can show an old MCP surface, for example about 37 tools, while
the current server checkout exposes the full surface. Current expected counts
are reported by `mcp_server_health().toolSurface`.

## Likely Causes

- The plugin-local `.hwpx-mcp-server-venv` was created with an older
  `hwpx-mcp-server` pin and reused.
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

If skew is reported, remove the plugin, remove the stale plugin-local venv if
present, reinstall the plugin, and start a fresh host session.
