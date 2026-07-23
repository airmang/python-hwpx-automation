# Agent runtime ownership migration

S-097 changes implementation ownership without changing a public wire or CLI
contract.

## Current owner and compatibility

- Canonical application owner:
  `hwpx_mcp_server.office.agent`
- Frozen core 4.x compatibility import:
  `hwpx.agent`
- Frozen core 4.x console entry point:
  `hwpx = "hwpx.agent.cli:main"`

Existing Python and CLI users do not need an immediate change. The core copy
remains operational throughout 4.x with the exact schema, result, error,
blueprint, replay, and CLI behavior. Core does not import or depend on MCP.

MCP production tools now execute the canonical MCP owner. Tool names, order,
input/output schemas, classifications, counts, and contract hash remain exactly
`119/127/28 @ 429cb6706323e762`.

## Guidance for new integrations

- Use existing MCP agent-document and mixed-form tools for application and
  model-facing workflows.
- Use `python-hwpx` document/OXML/mutation/preservation APIs for reusable
  library work.
- Do not add new workflow features to `hwpx.agent`; feature development belongs
  in the MCP owner.
- Do not replace the `hwpx` command with an MCP console alias during 4.x. S-097
  deliberately preserves the existing console entry point.

## 4.x fix policy

Security or correctness fixes originate in the MCP owner, add an executable
parity regression, and may then be mirrored into the core compatibility copy
with an explicit receipt. Feature work, schema expansion, and independent
behavior changes in the core copy are forbidden.

## Removal gate

No import or CLI is removed by S-097. Removing `hwpx.agent` or the `hwpx` agent
CLI requires a separately approved core-major Stage after:

1. another public-consumption census;
2. a published deprecation window and migration guide;
3. parity and rollback evidence;
4. explicit owner approval for the core major.

Until that gate is complete, absence of third-party code-search results is not
treated as permission to break the 4.x surface.
