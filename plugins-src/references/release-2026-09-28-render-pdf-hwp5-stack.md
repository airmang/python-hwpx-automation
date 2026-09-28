# Public stack release observation — 2026-09-28 KST

Public train: `python-hwpx 6.6.0` → `python-hwpx-automation 7.3.1` (+ `hwpx-mcp-server 7.3.1` compatibility) → `hwpx-plugin 2.4.0`. Contract `5e5c23651f92785a` (unchanged from 2.3.0): 128 default, 136 advanced, 29 skill-required tools.

- [Core release](https://github.com/airmang/python-hwpx/releases/tag/v6.6.0): wheel and sdist observed on PyPI; their SHA-256 values match the GitHub Release assets.
- [Automation release](https://github.com/airmang/python-hwpx-automation/releases/tag/v7.3.1): canonical and compatibility wheels/sdists observed on PyPI and GitHub with matching hashes. The `release-approved` plugin handoff receipt is attached. `v7.3.0` is a preserved failed tag; nothing was published from it.
- [Plugin release](https://github.com/airmang/hwpx-plugins/releases/tag/v2.4.0): the GitHub marketplace entry on main names 2.4.0. A fresh isolated Codex home installed `hwpx-plugin@hwpx` 2.4.0 directly from the public marketplace.
- The installed plugin's MCP configuration, run with an isolated home and cache, built runtime generation `gen-6.6.0-7.3.1` from public PyPI. The server reported 128 tools at contract `5e5c23651f92785a`, `python-hwpx 6.6.0`, automation 7.3.1, and skill bundle 2.4.0; a document creation call succeeded.
- Plugin PR CI reran the contract test using the exact core and automation release commits. Local acceptance covered 204 plugin tests, four host bundles, the launcher protocol E2E, and the clean wheel install smoke.

The release tag and installed marketplace snapshot retain `release-approved` as the publication-time record. The follow-up source commit promotes `currentPublic` only after the complete installation was observed.

Automation 7.3.1 writes builder metadata to the document properties instead of visible body paragraphs; put a visible title in the body as a block. Two historical cell-fill page-flow cases still show text occlusion. Saving or rendering a file is not proof of visual correctness or submission readiness. The advanced 136-tool profile was checked by contract CI but was not separately exercised in this public installation.
