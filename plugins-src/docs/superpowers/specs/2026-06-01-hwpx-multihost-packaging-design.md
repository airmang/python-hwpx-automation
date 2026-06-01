# HWPX Multi-Host Packaging Design

**Date:** 2026-06-01
**Status:** Approved (design); implementation plan to follow
**Scope:** Sub-project A — package the existing HWPX skill so one canonical source ships to four agent hosts: Claude Code, Codex, OpenClaw, and Hermes Agent. Feature expansion ("real document work") is Sub-project B and is explicitly out of scope here.

---

## 1. Goal

Make the HWPX skill installable and correct on four independent agent hosts from a **single canonical source**, without relying on any host tolerating another host's metadata. Generated per-host bundles are committed to the repo and guarded against drift with sha256 checksums.

## 2. Background

The repo already ships a Codex-only plugin at `plugins/hwpx-plugin/`, produced by `scripts/sync_hwpx_plugin.py` (copies repo-root skill assets into the plugin) and checked by `scripts/validate_hwpx_plugin.py` (manifest + launcher + sync-drift validation). Naming conventions in place: plugin `hwpx-plugin`, skill namespace `hwpx`, MCP server id `hwpx-mcp-server`. The MCP launcher `scripts/hwpx-mcp-server` prefers local sibling checkouts (`../hwpx-mcp-server`, `../python-hwpx`) and falls back to `uvx --from hwpx-mcp-server==2.2.6`.

This design generalizes that single-host sync into a multi-host builder.

## 3. Host requirements (verified against official docs)

| Host | Manifest | Frontmatter | MCP wiring | Skill dir |
|------|----------|-------------|-----------|-----------|
| **Claude Code** | `.claude-plugin/plugin.json` (`name` required; optional `version`/`description`/`author`/`homepage`/`repository`/`license`/`keywords`/`displayName`). Distribution via `.claude-plugin/marketplace.json`. | `name` + `description` (+ optional `metadata`). **No `version`** at top level (non-standard for Claude skills; avoid warnings). | `.mcp.json` (or `mcpServers` in plugin.json), command path uses `${CLAUDE_PLUGIN_ROOT}`. | `skills/<name>/SKILL.md`, auto-discovered. |
| **Codex** | `.codex-plugin/plugin.json` (existing, includes `interface` block). | `name` + `description`. | `.mcp.json`, `"command": "./scripts/hwpx-mcp-server"`, `"cwd": "."` (existing, verified working). | `skills/`. |
| **OpenClaw** | `openclaw.plugin.json`: `id` (required), `configSchema` (required, `{"type":"object","additionalProperties":false}`), optional `name`/`description`/`version`, `skills: ["./skills"]`. | `name` + `description` (+ optional `user-invocable`, gating fields). | Not bundled in plugin manifest; declared in OpenClaw config. Provide config guidance. | `skills/<sub>/<name>/SKILL.md`. |
| **Hermes Agent** | None for a skill pack (skills are published, not manifested). | **Requires** `version`, `author`, `license`, and `metadata.hermes.tags`. | `config.yaml` `mcp_servers:` entry (config-driven, not bundled). Provide snippet. | Skill dir is `SKILL.md` + assets; Hermes places it under `skills/<category>/<name>/` at publish/install time. Our build emits the publishable skill dir (`plugins/hermes/hwpx/`) and `metadata.hermes.tags` carries the category. |

**Conflict points that force per-host artifacts:** frontmatter schema (Claude must omit `version`, Hermes must include it), MCP command-path form (`${CLAUDE_PLUGIN_ROOT}` vs relative `./`), and MCP delivery (bundled file vs external config). These are why approach B (per-host build) was chosen over a single shared directory.

## 4. Architecture

Canonical skill assets stay at the repo root and remain the single source of truth. A builder reads them and emits one bundle per host. Differences between hosts are expressed as **data** in a build config, not as forked copies maintained by hand.

```
hwpx-skill/
├── SKILL.md  references/  examples/  scripts/      # canonical source (unchanged)
├── packaging/
│   ├── hosts.json                                   # per-host: frontmatter, skill path, MCP strategy, manifest values
│   └── templates/                                   # manifest + config-snippet templates
│       ├── claude.plugin.json
│       ├── claude.marketplace.json
│       ├── codex.plugin.json
│       ├── openclaw.plugin.json
│       └── hermes.mcp-config.yaml
├── plugins/                                          # generated AND committed
│   ├── claude/hwpx-plugin/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── .claude-plugin/marketplace.json
│   │   ├── .mcp.json                                 # ${CLAUDE_PLUGIN_ROOT}/scripts/hwpx-mcp-server
│   │   ├── scripts/hwpx-mcp-server
│   │   ├── skills/hwpx/{SKILL.md, references/, examples/, scripts/}
│   │   └── plugin-sync.json
│   ├── codex/hwpx-plugin/                            # relocated from plugins/hwpx-plugin/
│   │   ├── .codex-plugin/plugin.json
│   │   ├── .mcp.json                                 # ./scripts/hwpx-mcp-server, cwd "."
│   │   ├── scripts/hwpx-mcp-server
│   │   ├── skills/hwpx/{...}
│   │   └── plugin-sync.json
│   ├── openclaw/hwpx-plugin/
│   │   ├── openclaw.plugin.json
│   │   ├── skills/hwpx/{...}
│   │   ├── INSTALL-mcp.md                            # OpenClaw MCP config guidance
│   │   └── plugin-sync.json
│   └── hermes/hwpx/
│       ├── SKILL.md                                  # Hermes frontmatter (version/author/license/metadata.hermes)
│       ├── scripts/  references/
│       ├── INSTALL-mcp.md                            # config.yaml mcp_servers snippet + `hermes skills publish` steps
│       └── plugin-sync.json
└── scripts/
    ├── build_hwpx_plugins.py                         # generalizes sync_hwpx_plugin.py
    └── validate_hwpx_plugin.py                       # validates all four targets + drift
```

> `plugins/hwpx-plugin/` (current Codex bundle) is **relocated** to `plugins/codex/hwpx-plugin/`. References in docs and the validator are updated accordingly.

## 5. Components

### 5.1 Canonical source
Unchanged: repo-root `SKILL.md` (frontmatter `name` + `description` + canonical body), `references/api.md`, `examples/*`, `scripts/*` skill scripts. The builder treats the body below the frontmatter as host-agnostic; only frontmatter is rewritten per host.

### 5.2 `packaging/hosts.json`
Declares, per host: the target output directory, the skill sub-path (`skills/hwpx` vs `skills/<category>/hwpx`), the frontmatter fields to emit, the manifest template + substitution values, and the MCP strategy (`bundled` with a path form, or `config-doc`). New hosts are added here.

### 5.3 Shared MCP launcher
`scripts/hwpx-mcp-server` is reused, with one required fix: its repo-root resolution currently assumes the bundle sits at `plugins/hwpx-plugin/` (`$PLUGIN_DIR/../..` == repo root). Relocating bundles to `plugins/<host>/hwpx-plugin/` adds one directory level and breaks local sibling-checkout resolution (it would fall through to the `uvx` fallback). The launcher must resolve the stack root robustly — walk upward to a marker, or honor `HWPX_MCP_SERVER_REPO`/`PYTHON_HWPX_REPO` env overrides first — rather than rely on a fixed relative depth. Claude and Codex bundles include a copy; OpenClaw and Hermes point their external MCP config at the launcher path. Launcher fallback behavior (local sibling repos → `uvx` pinned fallback) is otherwise unchanged. The `2.2.6` pin tracks the current `hwpx-mcp-server` version and is updated only when Sub-project B bumps it.

### 5.4 `build_hwpx_plugins.py`
For each host in `hosts.json`:
1. Split canonical `SKILL.md` into frontmatter + body.
2. Emit `SKILL.md` at the host skill path with host frontmatter + canonical body.
3. Copy shared assets (`references/`, `examples/`, skill `scripts/`) into the host skill dir.
4. Render the manifest template with substitution values; write it at the host's manifest path.
5. Write MCP wiring: `.mcp.json` (bundled hosts) or `INSTALL-mcp.md` (config-doc hosts), and copy the launcher where bundled.
6. Record the **source sha256** of every generated file into that host's `plugin-sync.json`.

Fails loudly if any canonical source is missing or any template leaves an unsubstituted placeholder.

### 5.5 `validate_hwpx_plugin.py`
Single gate. For each host target:
- Manifest exists, required fields present, no placeholder leakage.
- Skill dir and all assets exist; launcher executable where bundled.
- sha256 drift clean (source changed without rebuild → fail; bundle edited directly → fail).
- Host-specific asserts: Claude (`name`, marketplace entry, `${CLAUDE_PLUGIN_ROOT}` in `.mcp.json`, no top-level `version` in skill frontmatter), Codex (`name`, relative launcher), OpenClaw (`id` + `configSchema` + `skills:["./skills"]`), Hermes (frontmatter `version` + `author` + `license` + `metadata.hermes.tags`).

## 6. Data flow

```
canonical SKILL.md + assets
        │  build_hwpx_plugins.py (reads packaging/hosts.json)
        ▼
 per-host bundles (committed)  ──►  validate_hwpx_plugin.py (drift + schema gate)
        │
        ├─ Claude:  marketplace add → /plugin install
        ├─ Codex:   existing install flow
        ├─ OpenClaw: openclaw.plugin.json + MCP config
        └─ Hermes:  hermes skills publish + config.yaml mcp_servers
```

## 7. Error handling

- **Builder:** missing canonical source → abort with the path; unsubstituted template placeholder → abort.
- **Validator:** drift, missing files, placeholder leakage, missing required manifest/frontmatter fields, non-executable launcher → fail with the specific target and reason.
- **Launcher (runtime, unchanged):** no `uv`/`uvx` and no local checkout → exit 127 with guidance.

## 8. Verification strategy

This environment has no Claude Code / OpenClaw / Hermes runtime, so end-to-end install-in-host cannot be executed here. Verification is therefore:
1. `python3 scripts/build_hwpx_plugins.py` then `python3 scripts/validate_hwpx_plugin.py` → all four targets green.
2. MCP discovery smoke (existing pattern): launch `scripts/hwpx-mcp-server`, `initialize` + `tools/list`, assert core tools (`validate_document_plan`, `create_document_from_plan`, `inspect_operating_plan_quality`). Host-agnostic because the launcher is shared.
3. `quickcheck.py` skill workflows (`--document-plan --operating-plan --template-formfit --visual-review`).
4. Real per-host load is handed off via each bundle's install docs; the user confirms in the actual agent.

## 9. Distribution

- **Claude:** `.claude-plugin/marketplace.json` so users `claude plugin marketplace add <repo>` then `claude plugin install hwpx-plugin@<marketplace>`. In-place `@skills-dir` loading also works for local dev.
- **Codex:** existing local-marketplace install flow (unchanged).
- **OpenClaw:** `openclaw.plugin.json` + ClawHub publish note; MCP via OpenClaw config per `INSTALL-mcp.md`.
- **Hermes:** `hermes skills publish plugins/hermes/hwpx --to github --repo <owner/repo>` + `config.yaml` `mcp_servers:` snippet per `INSTALL-mcp.md`.

## 10. Decisions locked

- Architecture: **B** (canonical source + per-host builder).
- Generated bundles are **committed** (drift-guarded by sha256), extending the existing `plugin-sync.json` pattern.
- Codex bundle is **relocated** to `plugins/codex/hwpx-plugin/`.
- Manifest author email stays **`kokyuhyun@hotmail.com`** (current value; not changed to the active account email).
- Hosts: Claude Code, Codex, OpenClaw, Hermes.

## 11. Out of scope (Sub-project B)

Real document features and completeness (e.g., images/charts, advanced tables/cell-merge, styles/page setup, PDF export, mail-merge/batch generation). Tracked separately after A ships. The `hwpx-mcp-server==2.2.6` pin and skill body content are touched only by B.

## 12. Risks

- **Host runtime tolerance unverifiable here:** mitigated by emitting per-host-correct artifacts (no cross-tolerance assumption) + install-doc handoff.
- **Committed-bundle duplication:** ~4× the skill assets in git; accepted per the committed-bundle decision and guarded by drift checks.
- **OpenClaw MCP delivery underdocumented:** plugin manifest does not bundle MCP; we ship config guidance rather than a bundled server, and validate only what the manifest owns.
- **Launcher version pin** can go stale relative to a published `hwpx-mcp-server`; ownership of the bump sits with Sub-project B.
