# python-hwpx-automation product boundary

`python-hwpx-automation` is the application layer above `python-hwpx`. It turns
generic HWPX capabilities into office workflows without becoming the package or
OXML owner. The base distribution is a Python automation product; FastMCP is an
optional adapter installed with `[mcp]`.

## Automation owns

- workflow, genre, profile, and office-policy services;
- typed application plans and deterministic orchestration;
- the canonical semantic agent runtime under `office.agent`;
- PII and compliance decisions;
- Hancom discovery and render-backend binding;
- workspace authorization and model-facing error contracts.

Application services live under `hwpx_automation.office`. Handlers should
translate tool requests into these services rather than adding more business
logic to the core library.

## Dependency direction

Automation may import `hwpx`. It must not create or vendor a `hwpx` package and
must not import implementation from `hwpx-skill`. The core library must never
import automation. The automation service packages and static ToolSpec data
must import without the optional `mcp` distribution; only the adapter/runtime
binding may import FastMCP.

The installed identity manifest is `hwpx_automation/identity.json`. It is the
machine-readable authority for canonical, compatibility, and host-local
identifiers.

Some frozen wire and receipt identifiers still contain `mcp`:
`hwpx.mcp-error/v1`, `versions.mcp`, `minMcpVersion`, `MIN_MCP_VERSION`,
architecture receipt IDs under `hwpx-mcp.*`, and the historical
`mcpRuntimeMembers` parity field. They are classified
`compatibility-preserved` through 6.x and remain byte-exact for existing
consumers; none assigns product ownership to MCP. Canonical capability names
are `versions.automation`, `minAutomationVersion`, and
`MIN_AUTOMATION_VERSION`. Internal owner-ledger keys use `automationRuntime`.

The prefix transition applies only to variables that carried the former MCP
product identity: `HWPX_AUTOMATION_*` is canonical and `HWPX_MCP_*` is its
bounded fallback. Product-neutral integration/capability variables retain their
existing names. The identity manifest enumerates every live `HWPX_RENDER_*`,
`HWPX_WORKFLOW_ENCRYPTION_KEY`, `HWPX_ORACLE_*`, `HWPX_SKILL_VERSION`, and
`HWPX_PLUGIN_ROOT` spelling as `integration-preserved` or
`capability-preserved`; they are not additional rename aliases.

The installed module-boundary manifest is
`hwpx_automation/public-modules.json`. For the 6.0 candidate it freezes all 177
shipped Python modules: 172 base-public modules that must import transitively
with the MCP SDK blocked, plus five explicitly classified MCP adapter/composer
modules. CI verifies the counts, sorted-list digests, source/wheel inventory,
and every base import. Adding, removing, or reclassifying a module therefore
requires an intentional manifest update instead of silently widening the
optional dependency boundary.

Linux keeps the full Python 3.10/3.11/3.12 suite. A separate bounded native
macOS/Windows job uses Python 3.10 to build and install clean core and canonical
`[oracle]` wheels, imports representative automation/render/form-fill modules,
and exercises structural-only oracle degradation plus the MCP-without-`[mcp]`
failure. It never launches a GUI application. The release workflow repeats the
same clean-wheel smoke on the minimum supported Python before publication.

`office/rendering.py` is the canonical Hancom binding. Existing direct
`resolve_oracle` imports in `handlers/layout_style.py` and
`handlers/specialized.py` are frozen compatibility debt; new direct discovery
sites fail the product-boundary check.

Moving released core workflows here is a compatibility project, not a copy
project. Each move needs one owner, a primitive seam, a 4.x migration path, and
an explicit later removal gate.

`hwpx_automation.office.agent` is the canonical owner of the released semantic
agent runtime. Automation production modules must not import the frozen core
`hwpx.agent` compatibility copy. The canonical runtime may use only the
approved public core seams for documents, OXML, mutation reports, quality,
table targeting, and package open-safety validation.

### Existing edit continuity

The agent owner has 21 modules, including two internal policy owners:
`_batch_publication` binds input revisions and output identities to the existing
workspace CAS writer; `_text_scope` checks a text-only command's permitted change
against the actual candidate. Guarded ZIP/XML parsing is imported from
`hwpx.opc.security`; serialization and format mutation remain core-owned. The
complete shipped-module ledger contains 180 base modules and 5 MCP adapter
modules. No new public MCP tool or parameter is introduced.

Quality-only `SavePipeline` injection still runs once; application publishers
carry `GuardedSavePipeline.publication` so the existing mixed-form owner retains
its publication and failure-preimage receipts. Scope preservation is reported
only for supported text-only paragraph/run/cell batches. Other command families
retain their current behavior and report a declared command log, without claiming
that log independently proves non-target preservation.
