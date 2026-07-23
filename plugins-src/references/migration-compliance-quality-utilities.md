# Compliance, quality, and utilities ownership migration

Four policy-bearing runtimes now have one MCP application owner while the
released Python 4.x imports and page-guard CLI remain operational.

## Canonical owners

| Frozen Python 4.x compatibility import | Canonical MCP owner |
|---|---|
| `hwpx.tools.official_lint` | `hwpx_mcp_server.office.compliance.official_lint` |
| `hwpx.tools.pii` | `hwpx_mcp_server.office.compliance.pii` |
| `hwpx.tools.page_guard` | `hwpx_mcp_server.office.quality.page_guard` |
| `hwpx.tools.table_compute` | `hwpx_mcp_server.office.utilities.table_compute` |

MCP handlers, form-fill, and MCP-owned authoring code execute the canonical
modules. The public tool surface remains exactly
`119 default / 127 advanced / 28 skill-required` at contract hash
`429cb6706323e762`.

`HwpxDocument`, `HwpxPackage`, OPC/OXML traversal, mutation, serialization,
preservation, and other format primitives remain reusable `python-hwpx`
responsibilities. Policy decisions, compliance interpretation, PII defaults,
quality thresholds, and general table-computation reports belong to MCP.

## PII policy injection

MCP form-fill and mail-merge entry points explicitly inject
`hwpx_mcp_server.office.compliance.DEFAULT_POLICY`. New application workflows
must also inject the canonical MCP policy instead of relying on a default
owned by a frozen core compatibility copy.

The default behavior remains privacy-safe: recognized machine PII is masked
unless an existing public surface explicitly authorizes raw output. Do not
add an implicit raw-PII path while routing a workflow.

## Python 4.x compatibility policy

The four `hwpx.tools` modules, their public names and signatures, report
versions, deterministic behavior, and
`hwpx-page-guard = "hwpx.tools.page_guard:main"` remain frozen through the
4.x line. Core must not import or depend on MCP or this skill.

Security or correctness fixes originate in the MCP owner, gain an executable
cross-owner parity regression, and may then be mirrored into the core copy
with an explicit receipt. Feature work, schema expansion, policy changes, or
independent behavior changes in the core copy are forbidden.

## Later migration routing

- S-101 and later dependency-trim work must consume the canonical MCP
  compliance/quality/utilities packages and keep the public-core allowlist
  narrow.
- S-105 policy/workflow migrations must explicitly inject canonical MCP policy
  objects at any retained core primitive seam.
- S-106 may observe public consumption and prepare deprecation evidence, but
  it does not authorize removal.
- S-107 may remove a frozen core import or CLI only as a separately approved
  core-major change after the observation and deprecation gates pass.

Until those gates complete, both layers intentionally ship: MCP is the
application owner and Python 4.x is the compatibility owner.
