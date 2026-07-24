# Compatibility observation: current routes and rollback

Use this guide when an existing automation calls a compatibility/deprecated MCP
tool, imports an application runtime directly from `python-hwpx`, or invokes a
legacy core CLI.

The observation window is 2026-07-24 through 2026-10-31 (Asia/Seoul), at least
90 days. The opening census authorizes **no removals**. Every observed surface
is `extend`: keep it working, guide new work to the canonical route, and collect
real usage before any next-major proposal.

Public feedback:

- [`python-hwpx` import/CLI/schema observation](https://github.com/airmang/python-hwpx/issues/68)
- [MCP compatibility/deprecation ToolSpec observation](https://github.com/airmang/hwpx-mcp-server/issues/88)
- [four-host skill guidance observation](https://github.com/airmang/hwpx-plugins/issues/15)

## MCP tool routing

The installed contract stays exactly **119 default / 127 advanced / 28
skill-required** at hash `429cb6706323e762`.

| Existing tool | Status | Route for new work | Observation decision |
|---|---|---|---|
| `apply_edits` | compatibility | `apply_document_commands` | extend |
| `apply_evalplan_fill` | compatibility, dedicated workflow | keep for evaluation plans; generic forms use analyze/apply/verify | extend |
| `create_comparison_table_document` | compatibility | `create_document_from_plan` | extend |
| `create_government_report_document` | compatibility | `create_document_from_plan` | extend |
| `create_proposal_document` | compatibility | `create_document_from_plan` | extend |
| `fill_by_path` | compatibility | `analyze_form_fill` → `apply_form_fill` → `verify_form_fill` | extend |
| `analyze_template_formfit` | deprecated | `analyze_form_fill` | extend |
| `apply_template_formfit` | deprecated | `apply_form_fill` + `verify_form_fill` | extend |
| `fill_form_field` | deprecated | canonical mixed-form trio | extend |

Deprecated means “do not choose for new work”; it does not mean the tool is
absent. Do not invent a removal date or tell a user to downgrade.

## Core 4.x routing

Direct core application-runtime callers keep working in 4.x. New multi-step
agent work should route through the MCP and this skill; reusable HWPX
structure/OXML/mutation primitives remain valid core APIs.

| 4.x family | Canonical application owner | Observation decision |
|---|---|---|
| agent runtime | MCP `office.agent` | extend |
| authoring runtime | MCP `office.authoring` | extend |
| compliance/quality/utilities | MCP `office.compliance` / `office.quality` / `office.utilities` | extend |
| form fill | MCP `office.form_fill` | extend |
| evaluation plan | MCP `office.evalplan` + J1~J6 skill workflow | extend |
| exam | MCP `office.exam` + exam skill workflow | extend |
| visual application runtime | MCP `office.rendering` | extend |
| comparison/mail-merge/redline wrappers | MCP `office.document_ops` | extend |

The `hwpx`, `hwpx-analyze-template`, and `hwpx-page-guard` commands also remain
available in 4.x. Published schema/report version strings keep their required
fields; additive Optional fields are allowed, but breaking shapes require a new
schema version and separate major approval.

For document creation, prefer
`validate_document_plan` → `create_document_from_plan`. Use `hwpx.builder`
directly only for an existing local integration or when the MCP is unavailable
and the task genuinely needs the lower-level core object model.

## Safe migration loop

1. Keep the current request, output, and error envelope as a fixture.
2. Confirm `mcp_server_health()` and the contract hash.
3. Dry-run the canonical route when supported and inspect semantic diff,
   rollback, open-safety, and domain receipts.
4. Run the existing and canonical routes side-by-side in a clean installation.
5. Switch only the intended caller after semantic parity passes.
6. If the client or workflow regresses, restore that caller to the retained
   compatibility route. No package downgrade is required.

Tool-name truncation, GUI workspace roots, schema presentation, and host-specific
discovery are client integration signals, not proof that a public surface is
unused. Record the host and visible schema with feedback.

## Removal gate

The observation end date does not remove anything. After 2026-10-31, a closing
census must decide keep/remove/extend for every tool, import family, CLI,
schema/report, and documented workflow. A removal then needs a separately
approved next-major plan, explicit migration table, clean installed-protocol
parity, rollback evidence, and regenerated four-host guidance.
