# Authoring runtime ownership migration

The authoring runtime now has one canonical application owner without changing
the public Python, CLI, MCP tool, or document-output contracts.

## Current owner and compatibility

- Canonical application owner:
  `hwpx_mcp_server.office.authoring`
- Frozen core 4.x compatibility imports:
  `hwpx` authoring exports, `hwpx.authoring`, `hwpx.builder`,
  `hwpx.design`, `hwpx.presets`, `hwpx.tools.advanced_generator`,
  `hwpx.tools.style_profile`, and `hwpx.tools.template_analyzer`
- Frozen core 4.x console entry point:
  `hwpx-analyze-template = "hwpx.tools.template_analyzer:main"`

Existing Python and CLI users do not need an immediate change. The 16-file core
copy remains operational throughout 4.x with its public signatures, schemas,
normalization, validation, errors, builder lowering, profile registry, output
payloads, save/reopen behavior, and `openSafety` behavior. Core does not import
or depend on MCP.

MCP production handlers now execute the canonical MCP owner. Tool names, order,
input/output schemas, classifications, counts, and contract hash remain exactly
`119/127/28 @ 429cb6706323e762`.

## Guidance for new integrations

- Use existing MCP authoring, generation, layout/style, quality/render, and
  specialized tools for application- and model-facing authoring workflows.
- Use `python-hwpx` document/OXML/mutation/preservation APIs for reusable
  library work.
- Add new zero-base authoring, genre-specific authoring, and authoring workflow
  features only to `hwpx_mcp_server.office.authoring`.
- Do not add new workflow features to the frozen core authoring modules.
- Existing independent consumers of `hwpx.builder` and
  `hwpx.tools.template_analyzer` remain supported by the 4.x compatibility
  copy.

## 4.x fix policy

Security or correctness fixes originate in the MCP owner, add an executable
parity regression, and may then be mirrored into the core compatibility copy
with an explicit receipt. Feature work, schema expansion, and independent
behavior changes in the core copy are forbidden.

The compliance/quality migration is now complete for MCP production routing:
official lint and page guard are owned by
`hwpx_mcp_server.office.compliance`/`office.quality`, while the corresponding
core imports remain frozen 4.x compatibility. See
`references/migration-compliance-quality-utilities.md`.

The core authoring copy may continue to use its remaining temporal
dependencies until their separately approved migrations:

- `hwpx.visual` — visual runtime migration;
- `hwpx.tools.mail_merge` — mail-merge migration.

## Removal gate

No import or CLI is removed by this migration. Removing any frozen authoring
surface requires a separately approved core-major Stage after:

1. another public-consumption census;
2. a published deprecation window and migration guide;
3. parity, clean-wheel, and rollback evidence;
4. explicit owner approval for the core major.

Until that gate is complete, the canonical MCP owner and the core compatibility
copy are intentionally both shipped.
