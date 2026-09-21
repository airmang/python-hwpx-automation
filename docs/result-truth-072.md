# Feature 072 result and evidence semantics

The domain contracts remain separate. `AgentBatchResult.ok=false` means its
transaction did not publish and includes a typed `AgentError`; its `rolledBack`
and `verificationReport` give the measured state. `ok=true` confirms the
transaction and the named checks in that report, not a visual verdict.
`MutationReport` projects those measured checks; `realHancom=not_performed`
is not success. The core `PlanReport` keeps its own error vocabulary.

The agent CLI emits the domain error and uses its established exit categories.
The MCP adapter keeps known agent codes (`stale_revision`,
`identity_collision`, `idempotency_conflict`, etc.) in `errorCode`, retaining
allowlisted target, recoverability, retryability, and a bounded suggestion.
Unknown lowercase strings never become protocol error codes. Partial artifact
results must keep their artifact statuses; an absent check remains unverified.

Authoring quality reports `render_checked=true` when a generated PDF can be
opened with at least one page. `visual_complete` remains `unverified` because
that check alone cannot detect clipping, missing content, or overlap. An
image-only PDF satisfies the render check. `source_content_hash` names the
actual HWPX bytes used for validation and rendering. Replacement of a path
while the inspection runs invalidates the result.

Workflow `renderEvidence` is a separate `hwpx.evidence-lineage/v1` companion
to the unchanged, frozen `RenderReceiptV2`. It binds the input HWPX hash to
the exact PDF and page PNG hashes and is `rendered_unreviewed`. A finding link
uses zero-based visual-QA `page_index` and emits the one-based render page
number. Bounding boxes are normalized to [0,1] with a top-left origin.
Missing targets stay `unmapped`; ambiguous ones stay `ambiguous`. A named
observer and content-addressed review evidence are both required to claim a
real Hancom review. The companion rejects a receipt for different source
bytes or a missing page. Render-only workflow status is
`real_hancom_rendered_review_unverified`.
