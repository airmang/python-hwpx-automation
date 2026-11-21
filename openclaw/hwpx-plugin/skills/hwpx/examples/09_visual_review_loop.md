# Visual Review Loop

Use this workflow when `inspect_operating_plan_quality(path).visual_review_required == true` or when template form-fit returns `visual_review_required=true`.

File-only checks can prove that the package opens, XML validates, required content exists, and operating-plan quality gates pass. They cannot prove rendered page breaks, table fit, typography, or approved-form layout parity. Before claiming a document is submission-ready, create visual-review evidence with `scripts/visual_review.py` and require `current.status == "observed_pass"` with `current.screenshot_path` present.

## CI Or Viewer-Missing Fallback

When CI, a headless container, or the current environment cannot open HWPX in a real viewer, record a blocked evidence file instead of claiming final visual approval:

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_fallback.json --viewer none --status blocked --notes "No HWPX viewer is available in this environment." --layout-risk "Rendered page breaks and table fit require opened-document review."
```

This fallback is valid handoff evidence, but it is not a final submission-ready visual claim.

## Local ComputerUse Or Human Viewer Pass

1. Launch the generated `.hwpx` in a real HWPX viewer such as Hancom Office, a supported web viewer, or another environment that can render the document.
2. Use ComputerUse or a human reviewer to inspect the opened document. ComputerUse is recorded as the review method, not as the viewer mode.
3. Check page breaks, table overflow, clipped text, missing placeholders, unresolved drafting markers, header/footer behavior, and whether approved-form spacing still fits.
4. Capture a screenshot of the opened document or the relevant reviewed page.
5. Record an observed pass:

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_pass.json --viewer auto --method computer-use --status observed_pass --screenshot examples/out/09_visual_review_page1.png --notes "Opened in local HWPX viewer. Tables fit, page breaks are acceptable, and no clipped placeholders were visible."
```

Only `observed_pass` with `--screenshot` evidence permits a final submission-ready visual claim. `--observation` is useful supporting detail, but observation text alone is not sufficient.

## Regeneration Iteration

If visual review finds a layout problem, mark it as `needs_review` and keep the layout risk explicit:

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan.hwpx --evidence examples/out/09_visual_review_needs_review.json --viewer auto --method computer-use --status needs_review --screenshot examples/out/09_visual_review_overflow.png --notes "Budget table overflows on page 3 after opening the document." --layout-risk "Table fit must be reduced before submission."
```

If you review the same target file again without regenerating it, reuse the same evidence path. The script will move the previous `current` block into `iterations[]` only when the evidence file already belongs to the same target checksum.

If you regenerate the HWPX, the output file has a different path or checksum. Write a new evidence file and use `--regenerated-from` to link to the previous evidence path. This preserves traceability, but it does not merge the previous JSON into `iterations[]`.

```bash
python3 scripts/visual_review.py examples/out/07_operating_plan_regenerated.hwpx --evidence examples/out/09_visual_review_pass_after_regen.json --viewer auto --method computer-use --status observed_pass --screenshot examples/out/09_visual_review_regenerated_page3.png --notes "Regenerated from the overflow evidence. Budget table now fits on page 3." --regenerated-from examples/out/09_visual_review_needs_review.json
```

## Required Handoff Fields

The visual-review evidence must include:

- `schemaVersion`
- `target.path`
- `target.sha256`
- `target.size_bytes`
- `quality.visual_review_required`
- `current.status`
- `current.timestamp`
- `current.tool_path`
- `current.screenshot_path` for `observed_pass`, or `current.fallback_reason` for viewer-unavailable/disabled/failure fallback evidence
- `iterations`
- `summary.ready_for_submission_claim`

Allowed `current.status` values are `observed_pass`, `needs_review`, and `blocked`.
