# Form-fill runtime ownership migration

The application-level form-fill runtime now has one canonical MCP owner without
changing the public Python, MCP ToolSpec, or document-output contracts.

## Current owner and compatibility

- Canonical application owner:
  `hwpx_mcp_server.office.form_fill`
- Frozen core 4.x compatibility imports:
  `hwpx.fill_residue`, `hwpx.form_fill`, `hwpx.form_fit`,
  `hwpx.formfill_quality`, `hwpx.guidance_scan`, and
  `hwpx.template_formfit`
- Reusable core primitives remain in `hwpx.document`, `hwpx.table_patch`,
  OWPML namespace/validation helpers, and byte-preserving mutation/reporting
  APIs.

Existing Python users do not need an immediate change. The 13-file core copy
remains operational throughout 4.x with its public imports, signatures,
dataclasses, report fields, refusal behavior, preservation, and optional
render-oracle behavior. Core does not import or depend on MCP.

MCP production handlers now execute the canonical MCP owner. Tool names, order,
input/output schemas, classifications, counts, and contract hash remain exactly
`119/127/28 @ 429cb6706323e762`.

## Guidance for new integrations

- Keep using the canonical MCP form workflow:
  `analyze_form_fill` → `apply_form_fill` → `verify_form_fill`.
- Use the existing MCP scoring, residue, guidance, template compatibility,
  mail-merge fit, seal, and geometry tools for application-facing work.
- Use `python-hwpx` document/table/text/field mutation and byte-preserving
  package APIs for reusable library work.
- Add new matching, fit-policy, guidance, residue, form-quality, and workflow
  behavior only to `hwpx_mcp_server.office.form_fill`.
- Do not add feature work to the frozen core form-fill modules.

The template-formfit functions remain deprecated compatibility surfaces. Their
presence does not change the preferred canonical mixed-form workflow documented
in [`workflows-forms.md`](workflows-forms.md).

## 4.x fix policy

Security or correctness fixes originate in the MCP owner, add an executable
parity regression, and may then be mirrored into the core compatibility copy
with an explicit receipt. Feature work, schema expansion, and independent
behavior changes in the core copy are forbidden.

The remaining serial migration routes are:

- visual and oracle policy move in the visual-runtime migration;
- mail-merge application policy moves in the mail-merge migration.

Evaluation-plan parsing and cleanup have moved to the canonical MCP owner; see
[`migration-evalplan-runtime.md`](migration-evalplan-runtime.md). Later
migrations may consume the canonical form-fill owner. They must not restore
production imports from the frozen core family.

## Removal gate

No core import is removed by this migration. Physical removal remains zero.
Removing any frozen form-fill surface requires the separately approved
observation and core-major sequence after:

1. another public-consumption census;
2. a published deprecation window and migration guide;
3. parity, wild-form, clean-wheel, protocol, and rollback evidence;
4. explicit owner approval for the core major.

Until that gate is complete, the canonical MCP owner and the core 4.x
compatibility copy are intentionally both shipped.
