# Government Report Visual Review Checklist

Use this checklist after `examples/09_visual_review_loop.md` has produced
per-file visual-review evidence. The 09 loop remains the single-file evidence
contract; this checklist only names government-report layout facts to observe
when the opened document can be inspected in Hancom Office HWP or another real
HWPX viewer.

## Acceptance Rule

Do not mark a government-report document as submission-ready from structural
checks alone. The final visual claim requires:

- `current.status == "observed_pass"`
- `current.screenshot_path` points to an existing screenshot from the opened
  document
- no recovery, conversion, password, repair, or error dialog appeared while
  opening the file
- `summary.ready_for_submission_claim == true`

If Hancom, ComputerUse, or screenshot capture is unavailable, record `blocked`.
If a document opens but any layout item below is uncertain or visibly wrong,
record `needs_review`. Do not downgrade `blocked` or `needs_review` to
`observed_pass` without a new opened-document observation.

## Open And Dialog Checks

- The document opens with `open -a "Hancom Office HWP" <file>`.
- No recovery dialog appears.
- No conversion dialog appears.
- No package-repair, broken-file, password, or unsupported-object error appears.
- The reviewer closes the document without saving changes.

## Layout Checks

- Title and subtitle are both visible and do not overlap.
- Header, footer, page number, and page margin are not clipped.
- Tables fit inside the page width; no right edge or last column is cut off.
- Table captions and unit labels remain near the table they describe.
- Computed values are rendered as visible text, including percentages and KRW
  Hangul amounts when present.
- Government-style bullets render as intended: `□`, `○`, `-`, `※`, and `*`.
- Image captions remain near their images.
- Page breaks do not split a heading from its first body paragraph in an
  obviously broken way.
- No unresolved placeholders, drafting markers, or broken field text are
  visible.

## Evidence Fields

Each evidence JSON should include:

- target file path and checksum
- viewer detection result or viewer command
- Axis A structural acceptance result
- Axis B visual status: `observed_pass`, `needs_review`, or `blocked`
- screenshot path for `observed_pass`
- explicit layout risks for `needs_review` or `blocked`
- reviewer note naming any recovery dialog, visible defect, or observation
  blocker

## Relationship To The 09 Loop

`examples/09_visual_review_loop.md` defines how one HWPX file becomes
visual-review evidence. Scaled government-report review should reuse that v1
evidence schema and add only orchestration:

- use `scripts/detect_hwpx_viewer.py` to choose Hancom, LibreOffice, Quick Look,
  or blocked
- use `scripts/visual_review_batch.py` to create per-file 09-compatible
  evidence and a batch summary
- use this checklist to decide whether a government-report visual observation is
  `observed_pass`, `needs_review`, or `blocked`
