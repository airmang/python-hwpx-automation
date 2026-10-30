# Known-leak policy owners: additive candidate

The core compatibility functions keep their existing names, defaults, outputs
and warning-free behavior during the current major. This candidate routes
application consumers through these canonical replacements:

| Responsibility | Automation entry point | Core primitive |
| --- | --- | --- |
| Attachment/table/figure reference policy | `office.compliance.inspect_reference_consistency(source)` | Generic paragraph source reader |
| Application document-plan inputs | `office.document_ops.paragraph_plan_to_paragraphs(plan)` | `hwpx.tools.doc_diff.paragraph_texts` and generic `doc_diff` |
| Markdown report heading promotion | `office.authoring.report_parser.detect_markdown_heading(text)` | `export_markdown(..., heading_detector=...)`, passed through ingest options |
| Evaluation-plan caption selection | `office.evalplan.strip_evalplan_table_captions(source, *, output_path=None)` | `hwpx.table_patch.strip_trailing_table_text(..., predicate=...)` |

Import these names under `hwpx_automation.`. The plan reader accepts a mapping
with `sections`; invalid top-level inputs raise `TypeError`. Existing block and
source precedence is preserved: generic `paragraphs` and `text` mappings win over
`sections`. The heading detector preserves the previous Markdown-specific
numbered-heading rules, independently of the broader pasted-report parser.
Non-HWPX ingest adapters ignore the Markdown options as before.

Caption selection retains the short ordinal-label rule. Editing eligibility is
proved by the neutral core API: only a plain text tail after the last direct
table and before the paragraph's actual line cache can be removed. Unknown
controls, foreign namespace lookalikes and non-whitespace run tails are retained.
Plain supported captions have byte-identical output and reports to the legacy
core helper. Unsafe legacy control-dropping cases are deliberately preserved,
not claimed as byte-identical cleanup. Output files are published atomically
only after predicate selection succeeds.

## Publication gate

This is an implementation candidate, **not a valid published-floor release**.
The currently published core does not provide all three additive seams. Keep the
PR draft and do not merge or publish automation until all of these are observed:

1. A published core contains `paragraph_texts`, `heading_detector` and
   `strip_trailing_table_text`.
2. The dependency minimum and identity/candidate-core CI pin name that actual
   publication. Do not guess a future version or bypass the missing APIs through
   core-private functions.
3. Both the source-main matrix and the published-floor suite, including isolated
   installed-wheel probes, pass against that dependency.

The existing release identity and historical contract receipts remain unchanged
in this draft. The current MCP tool contract remains unchanged. Core policy
compatibility definitions remain available; warnings and removal follow the
separately approved relative major-version schedule recorded in
`core-known-leak-moves.json`.

## Historical output capture

The full migration suite exposed a pre-existing core change: structural table
edits now synchronize the saved table height with the object-model row-height
delta (core #539). The previous automation owner and this candidate produce the
same four output byte sequences with that core. The old API/plan/report and byte
capture remains untouched in `tests/parity_fingerprints/evalplan.golden.json`;
`evalplan.post-height-sync.json` separately attributes only the changed byte
hashes and lengths. Other XML and ZIP-member payloads remain unchanged. This is
structural application-migration parity, not a rendered-layout approval. Existing
object semantics can clamp a saved table height to zero; visual verification of
those outputs remains unverified.
