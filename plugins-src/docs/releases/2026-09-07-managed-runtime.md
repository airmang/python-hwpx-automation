# Managed runtime release verification — 2026-09-07

Public train: python-hwpx 6.3.0, python-hwpx-automation 7.0.4, hwpx-mcp-server compatibility 7.0.4, hwpx-plugin 2.1.0. Contract `8c278ebd5becba08` is unchanged.

- [Automation release](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.0.4): canonical and compatibility wheels/sdists observed on PyPI; [release workflow](https://github.com/airmang/python-hwpx-automation/actions/runs/34121476463) succeeded.
- [Plugin release](https://github.com/airmang/hwpx-plugins/releases/tag/v2.1.0): public marketplace installed by Codex 0.144.4. A fresh ephemeral app-server session, with no model turn, called `mcp_server_health` and `describe_capabilities` through the installed plugin.
- Native Codex observed core6.3.0 / automation7.0.4 / plugin2.1.0 and 128 default tools. Managed runtime installed and running versions matched; `restartRequired=false`, `lastError=null`.
- A second fresh runtime launched from the installed Codex configuration observed 136 advanced tools, matching versions and contract, zero MCP protocol parsing errors, workspace denial checks, and document reopen/open-safety checks. Module origins were checked against installed wheels.
- [Automation source CI](https://github.com/airmang/python-hwpx-automation/actions/runs/34120622749) passed Python3.10–3.14, type/architecture/conformance/fuzz gates and Windows/macOS clean package checks. [Plugin CI](https://github.com/airmang/hwpx-plugins/actions/runs/34121885554) passed 191 tests, generated bundles, editable protocol and clean wheel smoke. The clean compatibility matrix also passed public legacy5.1.1/core4.2.0 upgrade and full rollback.

The release tags and PyPI artifacts retain `release-approved` as the publication-time snapshot. Only this follow-up source commit promotes `currentPublic` to the observed full train; immutable artifacts are not rewritten.

A successful installation is not a multi-day update observation or a real Hancom rendering verdict. Receiving a future upstream release without a plugin change and observations over three releases remain longitudinal follow-ups. No real Hancom render pass is claimed here.
