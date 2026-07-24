# Evaluation-plan runtime ownership migration

The released evaluation-plan workflow now has one canonical MCP application
owner without changing the Python 4.x compatibility surface, MCP ToolSpec, or
the J1–J6 judgment workflow.

## Current owner and compatibility

- Canonical application owner:
  `hwpx_mcp_server.office.evalplan`
- Frozen core 4.x compatibility import:
  `hwpx.evalplan_fill`
- Sibling application policy:
  `hwpx_mcp_server.office.form_fill`
- Reusable core primitives:
  `hwpx.body_patch`, `hwpx.patch`, and `hwpx.table_patch`

The MCP owner contains the review-Markdown parser, evaluation-plan content
models, target skeleton and structural plan, §1–§11 content fill, detailed §7
rubric handling, and deterministic clean-phase cleanup. MCP production
consumers do not import the frozen core copy.

Existing Python users do not need an immediate change. The core 4.x module
remains operational with its ordered exports, signatures, dataclasses,
structural/all/clean behavior, result and refusal shape, byte preservation, and
core-only installation. Core does not import or depend on MCP or this skill.

The public tool surface remains exactly
`119 default / 127 advanced / 28 skill-required` at contract hash
`429cb6706323e762`.

## Guidance for new work

- Use `apply_evalplan_fill(..., phase="clean")` for the MCP application
  workflow.
- Keep J1–J6 judgment in
  [`workflows-evalplan.md`](workflows-evalplan.md). This migration does not
  change those six decisions or their order.
- Add evaluation-plan parsing, workflow, cleanup, or policy features only to
  `hwpx_mcp_server.office.evalplan`.
- Add reusable content-independent HWPX byte, table, paragraph, body, package,
  preservation, or open-safety primitives to `python-hwpx`.
- Do not add new feature behavior to the frozen `hwpx.evalplan_fill` copy.

Private owner-reviewed 2·3학년 content and renders remain git-external.
Checked-in tests and bundles use synthetic, non-PII fixtures only.

## 4.x fix policy

Security or correctness fixes originate in the MCP owner and gain an
executable cross-owner parity regression. A fix may then be mirrored into the
core 4.x compatibility copy only with an explicit mirror receipt proving the
same public behavior. Feature work, schema expansion, and independent behavior
changes in the core copy are forbidden.

## Removal gate

No core import is removed by this migration. Physical removal remains zero.
S-106 may observe public consumption and prepare deprecation evidence, but it
does not authorize removal. Removing `hwpx.evalplan_fill` requires a separately
approved S-107 core-major Stage after:

1. a fresh public-consumption census;
2. a published deprecation window and migration guide;
3. parity, external-scenario, clean-wheel, protocol, and rollback evidence;
4. explicit owner approval for the core major.

Until those gates complete, MCP is the application owner and Python 4.x is the
compatibility owner.
