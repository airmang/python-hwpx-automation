# Document diff, mail-merge, and redline ownership migration

Generic HWPX document operations and application workflow/runtime now have
separate owners without changing the installed tool surface.

## Callable owners

| Responsibility | Owner |
|---|---|
| paragraph/document diff and reference consistency | `python-hwpx` core |
| comparison-table document-plan composition | `hwpx_mcp_server.office.document_ops` |
| placeholder discovery and generic merge with injected sanitizer | `python-hwpx` core |
| canonical-PII-bound mail-merge workflow | `hwpx_mcp_server.office.document_ops` |
| tracked-change structure/linkage contract | `python-hwpx` core |
| Hancom-bound redline verification/orchestration | `hwpx_mcp_server.office.document_ops` |

MCP production handlers use the canonical application owner. The public tool
surface remains exactly `119 default / 127 advanced / 28 skill-required` at
contract hash `429cb6706323e762`.

## Guidance for new work

- Use `doc_diff` for read-only comparison and
  `create_comparison_table_document` only when a generated comparison HWPX is
  explicitly requested.
- Use `mail_merge` through MCP so the canonical compliance sanitizer and fit
  policy are injected. Do not build a new application workflow on the frozen
  core 4.x default-policy wrapper.
- Use `add_tracked_edit` for redline authoring. Interpret `marksLinked`,
  `displayEnabled`, `opensClean`, `render_checked`, and `visual_ok` exactly as
  described in `workflows-redline.md`.
- If a Hancom oracle is unavailable, report visual state as unverified; a
  structural pass is not a visual pass.
- Add reusable document/package/OXML diff, placeholder replacement, or
  tracked-change structure primitives to core. Add comparison presentation,
  privacy policy, bulk orchestration, and Hancom verification to MCP.

## Python 4.x compatibility

Existing imports remain operational:

- `hwpx.tools.doc_diff.build_comparison_table_plan`;
- `hwpx.tools.mail_merge.mail_merge`;
- `hwpx.tools.redline.verify_redline`.

They are compatibility surfaces, not independent feature owners. Correctness
or security fixes originate in the canonical owner or generic core seam, gain
an executable parity regression, and may then be mirrored when required.

No compatibility import is removed by this migration. S-106 may observe public
consumption and prepare migration guidance, but removal requires the separately
approved S-107 core-major gate.
