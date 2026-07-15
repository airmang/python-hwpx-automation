# ComputerUse Visual Review At Scale

This workflow extends `examples/09_visual_review_loop.md`; it does not replace
the 09 single-file evidence contract. Per-file evidence still uses
`scripts/visual_review.py` and schema `hwpx.visual-review.v1`. The batch runner
only adds viewer detection, repeated execution, and an aggregate report.

## Detect The Viewer

```bash
python3 scripts/detect_hwpx_viewer.py --pretty
```

Detection order is:

1. Hancom Office HWP
2. LibreOffice
3. Quick Look
4. blocked

CI can force the blocked shape:

```bash
HWPX_VIEWER_FORCE=blocked python3 scripts/detect_hwpx_viewer.py --pretty
```

## Batch Preflight

Run a batch preflight before opened-document observation:

```bash
python3 scripts/visual_review_batch.py \
  --inputs "${PYTHON_HWPX_ROOT}/tests/fixtures/hwpxlib_corpus/*.hwpx" \
  --evidence-dir examples/out/11_corpus_batch
```

When a viewer is available but no opened-document observation has been made,
the batch status is `needs_review`. When no viewer is available, or when CI
forces blocked, the status is `blocked`. Neither status is submission-ready.

## ComputerUse Observation

For each target selected for visual review:

1. Open the file:

   ```bash
   open -a "Hancom Office HWP" <file>
   ```

2. Observe the opened document with ComputerUse or a human reviewer.
3. Check Axis A: no recovery, conversion, password, repair, or error dialog.
4. Check Axis B: page layout, clipping, table fit, bullets, captions, and
   generated content placement.
5. Capture a screenshot of the opened document.
6. Close the document without saving.
7. Record per-file evidence using the 09 loop:

   ```bash
   python3 scripts/visual_review.py <file> \
     --evidence examples/out/11_hancom_evidence/<name>.json \
     --viewer "command:open -a 'Hancom Office HWP'" \
     --method computer-use \
     --status observed_pass \
     --screenshot examples/out/11_hancom_screenshots/<name>.png \
     --observation "No recovery or conversion dialog appeared." \
     --observation "Tables and captions were visible without clipping."
   ```

If the opened document cannot be observed or screenshot capture fails, record
`blocked` with an explicit layout risk. If a defect is visible, record
`needs_review`.

## Government Report Checklist

Use `references/government-report-visual-review.md` for government-report
documents. That checklist names the government-specific layout facts such as
title/subtitle overlap, table width, caption/unit proximity, and rendering of
`□`, `○`, `-`, `※`, and `*` bullets.

## Local 2026-06-03 Run Notes

The local environment detected Hancom Office HWP at
`/Applications/Hancom Office HWP.app`, and `open -a "Hancom Office HWP"` started
the app. The first attempt could not capture the display, so the evidence was
truthfully recorded as blocked:

```text
examples/out/11_hancom_blocked_evidence/visual_review_batch_report.json
```

After the user re-requested the check from the local Mac session, screenshot
capture succeeded. The retry evidence was written to:

```text
examples/out/11_hancom_observed_evidence_retry/
examples/out/11_hancom_screenshots_retry/
```

The representative set was:

- `reader_writer__HeaderFooter.hwpx`
- `reader_writer__SimpleTable.hwpx`
- `reader_writer__SimplePicture.hwpx`
- `reader_writer__SimpleEquation.hwpx`
- `error__20250808__2015년_12월_재난안전종합상황_분석_및_전망.hwpx`
- `error__20250523__프로젝트 계획서.hwpx`
- `examples/out/10_builder_vertical_slice.hwpx`
- `examples/out/10_government_report.hwpx`

The retry recorded four simple one-page corpus samples as `observed_pass`:

- `reader_writer__HeaderFooter.hwpx`
- `reader_writer__SimpleTable.hwpx`
- `reader_writer__SimplePicture.hwpx`
- `reader_writer__SimpleEquation.hwpx`

The retry recorded four multi-page or partially visible samples as
`needs_review`, with screenshots attached and explicit layout risks:

- `error__20250808__2015년_12월_재난안전종합상황_분석_및_전망.hwpx`: only page 1 of 75 was captured
- `error__20250523__프로젝트 계획서.hwpx`: only page 1 of 2 was captured
- `examples/out/10_builder_vertical_slice.hwpx`: page 2 was not captured
- `examples/out/10_government_report.hwpx`: table begins near the bottom of the captured viewport
