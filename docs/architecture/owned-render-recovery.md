# Owned render recovery

The Mac GUI adapter belongs to `office.rendering`, alongside the Windows COM
session. It reuses MacHancomOracle and SerializedHancomWorker; the queue protocol
and public MCP tool contract do not change.

Local worker receipts add optional `backend` and `input_content_hash` fields.
`render(job, *, cancelled=None)` retains existing callers and admits bounded
queue cancellation. Artifacts now live under a hash of the PDF and every page,
so retries cannot invalidate previously issued artifact references. Consumers
must follow receipt `relative_path`, never construct paths from job IDs.

The frozen 4.x parity receipts stay immutable. Tests apply exactly these three
reviewed differences to their expected copy: additive callback, additive fields,
and content-addressed artifact paths. All other signatures, values and artifact
hashes remain compared against the historical receipt.

Mac export uses a unique staged document and closes/discards only that document.
The adapter locks the desktop across worker instances and kills only its own
osascript on cancellation. It never kills Hancom or closes another document's
save sheet. Inability to prove cleanup produces an unverified result. Complete
PDF EOF, non-repaired parsing, nonempty pages, content hashes, and the installed
bundle build are recorded; PDF export alone does not certify visual layout.

A damaged input can be refused before GUI entry. This is separate from actual
watchdog recovery and from visually reviewing pages; evidence reports each axis.
