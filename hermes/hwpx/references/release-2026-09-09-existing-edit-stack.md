# Existing-edit stack release verification — 2026-09-09

Public train: python-hwpx 6.4.0, python-hwpx-automation 7.1.0, hwpx-mcp-server compatibility 7.1.0, hwpx-plugin 2.2.0. Contract `ba0211fc854a0a97` (floor-only change from `8c278ebd5becba08`; 128 default / 136 advanced / 29 skill-required tools unchanged).

- [Core release](https://github.com/airmang/python-hwpx/releases/tag/v6.4.0): wheel and sdist observed on PyPI; the release workflow verified PyPI and GitHub hashes.
- [Automation release](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.1.0): canonical and compatibility wheels/sdists observed on PyPI; the release-approved plugin handoff receipt is attached.
- [Plugin release](https://github.com/airmang/hwpx-plugins/releases/tag/v2.2.0): public marketplace installed by Codex 0.153.4 (`codex plugin marketplace add airmang/hwpx-plugins`, `codex plugin add hwpx-plugin@hwpx` → 2.2.0). A fresh ephemeral app-server session, with no model turn, called `mcp_server_health` and `describe_capabilities` through the installed plugin.
- Native Codex observed core 6.4.0 / automation 7.1.0 / plugin 2.2.0 and 128 default tools bound to contract `ba0211fc854a0a97` with no binding mismatches. The bundled launcher built a new managed generation `gen-6.4.0-7.1.0` next to the previous `gen-6.3.0-7.0.4`; installed and running versions matched, `restartRequired=false`, `lastError=null`.
- Plugin source CI (PR #31) passed the plugin-contract E2E built from the core and automation release commits; 191 tests, four regenerated host bundles and shipped-code validation passed locally.

The release tag and marketplace entry retain `release-approved` as the publication-time snapshot. Only this follow-up source commit promotes `currentPublic` to the observed full train; the tag is immutable.

A successful installation is not a multi-day update observation or a real Hancom rendering verdict; the advanced 136-tool runtime was not re-observed for this train. Receiving a future upstream release without a plugin change and observations over three releases remain longitudinal follow-ups.
