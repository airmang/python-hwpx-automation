# HWPX Plugin Release Handoff - 2026-05-30

Stage: hwpx display S-004 / server S-045

## Bundle

- Plugin path: `plugins/hwpx-plugin`
- Skill path: `plugins/hwpx-plugin/skills/hwpx`
- MCP config: `plugins/hwpx-plugin/.mcp.json`
- MCP launcher: `plugins/hwpx-plugin/scripts/hwpx-mcp-server`

## Verification

- `python3 scripts/sync_hwpx_plugin.py`
- `python3 scripts/validate_hwpx_plugin.py`
- `python3 -O scripts/validate_hwpx_plugin.py`
- MCP tool discovery smoke for `validate_document_plan`, `create_document_from_plan`, and `inspect_operating_plan_quality`
- `uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review`

## Residual Notes

- `visual_review_required=true` remains a final submission gate.
- Local development expects sibling checkouts or `HWPX_MCP_SERVER_REPO` and `PYTHON_HWPX_REPO`.
- Start a new Codex thread after installing or reinstalling the plugin so new skills and MCP tools load.
