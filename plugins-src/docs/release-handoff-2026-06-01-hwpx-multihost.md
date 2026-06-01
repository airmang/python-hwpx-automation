# HWPX Multi-Host Packaging Release Handoff - 2026-06-01

## Bundles

- Claude Code: `plugins/claude/hwpx-plugin` (+ repo-root `.claude-plugin/marketplace.json`)
- Codex: `plugins/codex/hwpx-plugin`
- OpenClaw: `plugins/openclaw/hwpx-plugin`
- Hermes Agent: `plugins/hermes/hwpx`

Source of truth: repo-root `SKILL.md`, `references/`, `examples/`, `scripts/`.
Build: `scripts/build_hwpx_plugins.py`. Config: `packaging/hosts.json` + `packaging/templates/`.

## Verification

- `python3 scripts/build_hwpx_plugins.py` && `git diff --exit-code -- plugins .claude-plugin`
- `python3 scripts/validate_hwpx_plugin.py`
- MCP tool discovery smoke for `validate_document_plan`, `create_document_from_plan`, `inspect_operating_plan_quality`
- `uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review`

## Residual notes

- End-to-end install in Claude Code / OpenClaw / Hermes is not exercised here; confirm in each host after install.
- `visual_review_required=true` remains a final submission gate.
- The `hwpx-mcp-server==2.2.6` pin is owned by feature work (Sub-project B).
- GitHub repo renamed to `airmang/hwpx-plugins`; local directory name is unchanged.
