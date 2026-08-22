# Skill-First Workflows on the Automation MCP Adapter

> 릴리스 상태: `released` (2026-08-02) — 공개 트레인 `python-hwpx 5.5.0 → python-hwpx-automation 6.5.1 → hwpx-plugin 1.5.0` 기준 문서입니다.

This guide describes the released 6.0 automation train's optional FastMCP
adapter (`released`, 2026-07-28: core 5.0.1 / automation 6.0.4 / plugin
1.0.0). The Python automation layer is the product surface and `python-hwpx`
remains the upstream engine layer; `hwpx-mcp-server` continues as the 6.x
compatibility distribution and console.

Scope for this pass:

- do not add new public MCP tools by default
- keep document/package semantics in Python code, not in markdown
- use skills as thin orchestration over the current tool inventory

Existing compatibility/deprecated callers remain supported during the public
observation window. The exhaustive retained-tool table, canonical replacements,
and rollback procedure are in
[`compatibility-observation.md`](compatibility-observation.md).

## Current Tool Coverage

`HWPX_AUTOMATION_ADVANCED=1` is required for package inspection and low-level
validation (`HWPX_MCP_ADVANCED=1` remains a 6.x fallback). The canonical
heterogeneous edit entry point, `apply_document_commands`, is available in the
default profile.

| Workflow need | Existing MCP tools | Notes |
|---|---|---|
| Read package parts | `package_parts` | Advanced mode only. |
| Extract XML/text | `package_get_xml`, `package_get_text`, `get_document_text`, `get_paragraph_text`, `get_paragraphs_text`, `hwpx_extract_json`, `hwpx_to_markdown`, `hwpx_to_html` | Use package-level extraction when exact part shape matters. |
| Validate structure | `validate_structure`, `lint_text_conventions` | `lint_text_conventions` is optional style/text policy linting. |
| Apply heterogeneous edits | `apply_document_commands` | One atomic set/add/remove/move/copy command batch with dry-run, revision, and idempotency guards. |
| Mixed-form fill | `analyze_form_fill` → `apply_form_fill` → `verify_form_fill` | Canonical atomic route across native fields, labeled cells, canonical paths, and body anchors; narrow replacement/cell tools are compatibility paths. |
| Save/copy flows | `copy_document` plus the normal mutating tools | Mutating tools persist immediately through the shared atomic save path. Reviewable handoff는 copied working file을 기준으로 잡는다. |

Important boundary:

- There is no active public `fill_template` tool on the FastMCP surface.
- There is no active public `save` / `save_as` tool on the FastMCP surface.
- Cautious workflows should edit a copied working file, then promote that file externally after review.

## Workflow 1: Reference-Preserving Edit

Use when an existing HWPX document must be edited with minimal layout drift and clear review checkpoints.

Suggested order:

1. `copy_document` to create a working copy.
2. Read the baseline with `get_document_outline`, `get_paragraphs_text`, `get_table_text`, or `hwpx_extract_json`.
3. In advanced mode, inspect likely-sensitive parts with `package_parts`, `package_get_xml`, `package_get_text`, `object_find_by_tag`, and `object_find_by_attr`.
4. Run `validate_structure` before editing if the source package is suspicious or externally produced.
5. Make bounded edits with the smallest tool that fits the task:
   - `search_and_replace` or `batch_replace` for anchored text updates
   - `format_text` for run-level styling
   - `set_table_cell_text` for fixed table locations
   - `insert_paragraph`, `add_paragraph`, `add_heading`, `add_memo` only when structure really must change
6. Re-read the touched areas and rerun `validate_structure`.
7. For a heterogeneous change set, run `apply_document_commands` with `dry_run=true`, review the receipt, then apply the same bounded commands with the captured revision and an idempotency key.

Layout drift controls:

- Prefer replacements over structural insert/delete operations.
- Touch the smallest paragraph/table range possible.
- Inspect package parts when the source relies on fixed section XML, memo anchors, or table-heavy layouts.
- Use `copy_document` first because edits persist immediately.

Limitations:

- `apply_document_commands` is limited to its typed set/add/remove/move/copy command union; use a domain-specific tool when its evidence or semantics are required.
- There is no public structure-diff or layout-drift report tool on the active surface.
- Package inspection is diagnostic; interpretation still belongs to the workflow layer.

## Workflow 2: Government or Public-Form Filling

Use when an existing form mixes native fields, labeled table cells, canonical document paths, and body-text anchors that must commit as one verified transaction.

Suggested order:

1. Keep the approved source immutable and choose a distinct output path.
2. Read visible structure with `list_form_fields`, `get_document_outline`, `get_paragraphs_text`, and `get_table_map`.
3. Build one strict `hwpx.mixed-form-plan/v1` covering the required `nativeField`, `labelCell`, `canonicalPath`, and `bodyAnchor` operations.
4. Call `analyze_form_fill(plan=...)` without modifying the document; review the compiled plan, locator evidence, revisions, and any ambiguity.
5. Apply the reviewed compiled plan with `apply_form_fill(plan=compiledPlan)`. The output is committed once or rolled back as a whole.
6. Call `verify_form_fill(plan=compiledPlan, expected_output_revision=...)` and retain the unified open-safety, byte-preservation, reopen, privacy, and optional render receipt.
7. Use `apply_evalplan_fill` for the preserved evaluation-plan workflow and `compose_exam` for exam composition; do not fold either into the generic mixed-form route.
8. Use `fill_form_field`, `batch_replace`, or `set_table_cell_text` only for retained single-target compatibility work where the canonical mixed transaction is unnecessary.

Layout drift controls:

- Prefer existing fields and anchors over inserting new paragraphs.
- Keep table geometry unchanged unless the form explicitly allows it.
- Treat ambiguous or multi-match locators as blocked until the plan is narrowed.
- Require a successful unified verification receipt before handoff.

Limitations:

- Repeated labels can still require human disambiguation during analysis.
- The canonical transaction does not replace the dedicated evaluation-plan or exam workflows.
- Complex approval seals or unsupported drawing-object mutations still require their dedicated tools or manual review.

## Workflow 3: Template-Based Document Generation

Use when document generation starts from a reusable template, or when a new document must be assembled from current core mutators.

Suggested order:

1. If a template file exists, start with `copy_document`.
2. Replace placeholders with `batch_replace` or `search_and_replace`.
3. Update fixed tables with `set_table_cell_text`, `merge_table_cells`, `split_table_cell`, or `format_table`.
4. Add controlled freeform content with `add_heading`, `add_paragraph`, `insert_paragraph`, and `add_table`.
5. Use `create_custom_style` only when a real reusable style is needed across multiple inserts.
6. Run `validate_structure` if advanced mode is available.

Fallback when no template exists:

1. `create_document`
2. `add_heading`
3. `add_paragraph` / `insert_paragraph`
4. `add_table`
5. `format_text` / `format_table`

Limitations:

- There is no single public `fill_template` shortcut on the active surface.
- Large-scale document assembly still requires explicit orchestration in the client or skill.

## Workflow 4: Cautious Edit-Review-Save

Use when edits should remain reviewable and low risk even though the current MCP surface persists mutations immediately.

Suggested order:

1. `copy_document` to create a disposable working draft.
2. Capture the baseline with `get_document_text`, `get_document_outline`, or advanced package reads.
3. Use `apply_document_commands(..., dry_run=true)` when you want an explicit review/verification receipt for a heterogeneous command batch.
4. Perform only bounded mutating operations on the working draft.
5. Re-read the touched areas and rerun `validate_structure`.
6. Keep or rename the reviewed copy outside the MCP workflow once approved.

Why this is the safe path:

- Mutations already go through the safer atomic save path, but they still update the target file immediately.
- There is no separate public `save` / `save_as` handoff step on the current FastMCP surface.
- Copy-first is therefore the practical review boundary on the current surface.

## Example Skill Folders

- `examples/skills/reference-preserving-edit/SKILL.md`
- `examples/skills/form-fill/SKILL.md`
- `examples/skills/template-generation/SKILL.md`

These examples stay intentionally thin:

- they describe when to use the workflow
- they name the existing MCP tools in order
- they document layout-drift precautions
- they do not duplicate Python business logic from the server or from `python-hwpx`

## Prompt/Resource Layer Status

No new prompt or resource layer was added in this pass.

Reason:

- the active product surface is the FastMCP tool inventory in `src/hwpx_automation/server.py`
- legacy prompt/resource code exists elsewhere in the repo, but enabling or expanding it here would broaden scope without proving a product need

If future workflow prompting becomes important, keep the contract narrow and register it against the active FastMCP surface instead of reviving legacy behavior by default.


> 릴리스 상태 참고: 현재 공개 트레인은 python-hwpx 6.3.0 · python-hwpx-automation 7.0.3 · hwpx-plugin 2.0.2입니다 (2026-08-22 왕복 충실도 트레인) (python-hwpx 6.2.1 released 2026-08-19, Windows 편집기 표면 core-only 트레인 — v6.2.0은 보존된 실패 태그).
