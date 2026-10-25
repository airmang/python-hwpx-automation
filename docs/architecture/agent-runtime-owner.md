# Canonical agent runtime owner

`hwpx_automation.office.agent` is the canonical application-layer owner of the
semantic agent runtime. It was transplanted from the prior core compatibility
line at `python-hwpx` commit
`fd879637f97a796c7a038e2c0c4a647a9b501064`:

- 19 Python files;
- 10,024 LOC;
- the same internal relative-package structure;
- one ownership import change in `model.py`:
  `hwpx.mutation_report` replaces the former core-package relative import;
- one compatibility-only presentation normalization in `cli.py`: fixed
  80-column help formatting and normalized choice-list quoting keep public CLI
  output byte-stable across supported Python minors.

That list records the transplant as it was frozen. Later changes to the owner
are intentional and reviewed one by one; the transplant baseline is history,
not the current source. Wire identifiers such as `hwpx.agent-batch/v1`, the CLI program
name `hwpx`, JSON schemas, results, errors, and exit codes are compatibility
contracts and do not change with the Python owner namespace.

MCP production traffic enters this owner through:

- `hwpx_automation.agent_document`;
- `hwpx_automation.mixed_form`;
- `hwpx_automation.runtime`.

The product-boundary gate rejects any production import from the frozen core
`hwpx.agent` copy and limits the canonical runtime to the approved public core
seams: document, OXML, mutation report, quality, table targeting, and package
open-safety validation.

An approved module import does not make every member of its objects public:
python-hwpx's contract is the member list in its `docs/stable-api.md`. Since
#178 the runtime reads headers, styles, numbering definitions, character
properties and fonts through `doc.oxml.headers`, `doc.styles` and
`doc.package`, and blueprint replay mints paragraph styles with
`doc.styles.ensure_style`/`ensure_paragraph_format` (python-hwpx PR #566):
the collision-free name is this owner's policy, the style record, its id and
`itemCnt` are core's. The gate counts every `obj._name` use whose name
automation never defines, so a new private core access fails. The uses that
remain are listed in `CORE_PRIVATE_MEMBER_EXCEPTIONS` in
`scripts/check_product_boundary.py`, each with its reason, the core contract
that would remove it and its removal condition; two of them are in this owner
(`commands.py` memo groups, `document.py` form-field matches).

The prior core 4.x copy was compatibility-only and accepted no feature work.
The 5.0 boundary removes that application runtime from core; the canonical
automation owner above is now the only implementation. Generic HWPX primitives
remain in core under their own stable contracts.
