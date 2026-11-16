# Public stack release observation — 2026-09-22 KST

Public train: `python-hwpx 6.5.0` → `python-hwpx-automation 7.2.0` (+ `hwpx-mcp-server 7.2.0` compatibility) → `hwpx-plugin 2.3.0`. Contract `5e5c23651f92785a`: 128 default, 136 advanced, 29 skill-required tools.

- [Core release](https://github.com/airmang/python-hwpx/releases/tag/v6.5.0): wheel and sdist observed on PyPI; their SHA-256 values match the GitHub Release assets. A clean public install created, saved, and reopened a HWPX package.
- [Automation release](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.2.0): canonical and compatibility wheels/sdists observed on PyPI and GitHub with matching hashes. The `release-approved` plugin handoff receipt is attached.
- [Plugin release](https://github.com/airmang/hwpx-plugins/releases/tag/v2.3.0): the GitHub marketplace entry on main names 2.3.0. A fresh isolated Codex home installed `hwpx-plugin@hwpx` 2.3.0 directly from the public marketplace.
- The installed plugin's MCP configuration started public wheels `python-hwpx 6.5.0` and `python-hwpx-automation 7.2.0` from site-packages. An actual protocol session listed 128 default tools at contract `5e5c23651f92785a`, exercised document creation/editing and a workflow, and reported no protocol errors. Workspace escape cases were denied; PII masking held. Render service was not configured, and the server reported that state honestly.
- Plugin PR CI reran the contract test using the exact core and automation release commits. Local acceptance covered 191 plugin tests and four host bundles.

The release tag and installed marketplace snapshot retain `release-approved` as the publication-time record. The follow-up source commit promotes `currentPublic` only after the complete installation was observed.

Two historical cell-fill page-flow cases still show text occlusion. Saving or rendering a file is not proof of visual correctness or submission readiness. The advanced 136-tool profile was checked by contract CI but was not separately exercised in this public installation.
