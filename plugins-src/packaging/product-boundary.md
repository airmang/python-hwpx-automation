# hwpx-skill product boundary

`hwpx-skill` is the judgment and routing layer. It tells an agent which
capability to use, in what order, and with which evidence; it does not become a
second Python document library or MCP server.

## Skill owns

- task classification and workflow selection;
- genre/profile choice and bounded variation guidance;
- model-facing examples, evidence rules, and retry guidance;
- multi-host packaging and exact version/contract pins.

Document/package/XML implementation belongs to `python-hwpx`. Workflow,
profile, policy, workspace, and renderer binding belongs to
`hwpx-mcp-server`.

Generated plugin bundles may contain the approved support scripts and examples
already required by the hosts. A new Python file outside `examples/`, or a new
runtime script not in the approved support-script set, fails
`scripts/check_product_boundary.py` until the responsibility decision is
reviewed. This prevents application logic from drifting into the prompt layer.
