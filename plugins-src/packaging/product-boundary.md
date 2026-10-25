# hwpx-skill product boundary

`hwpx-skill` is the judgment and routing layer. It tells an agent which
capability to use, in what order, and with which evidence; it does not become a
second Python document library or MCP server.

## Skill owns

- task classification and workflow selection;
- genre/profile choice and bounded variation guidance;
- model-facing examples, evidence rules, and retry guidance;
- multi-host packaging and exact version/contract pins.

Document/package/XML implementation belongs to `python-hwpx`. Workflow,
profile, policy, workspace, and renderer binding belongs to
`python-hwpx-automation`. Its MCP transport is an optional `[mcp]` adapter, not
the identity of the application layer. `hwpx-mcp-server` is a 6.x compatibility
distribution/import/console surface only. New bundles call the canonical
`scripts/hwpx-automation-mcp` launcher; `scripts/hwpx-mcp-server` is only a
6.x wrapper that delegates to it.

Generated plugin bundles may contain the approved support scripts and examples
already required by the hosts. A new Python file outside `examples/`, or a new
runtime script not in the approved support-script set, fails
`scripts/check_product_boundary.py` until the responsibility decision is
reviewed. This prevents application logic from drifting into the prompt layer.
The two package-editing support scripts, `zip_replace_all.py` and
`fix_namespaces.py`, are command-line wrappers around python-hwpx's public
`hwpx.patch.replace_package_text` and
`hwpx.tools.repair.normalize_package_namespaces`. The gate checks the root
scripts and every generated copy: each must call its core function and must not
import `lxml`, `xml`, `re` or `copy`, use `zipfile` beyond `is_zipfile`, touch
`ZipFile`/`ZipInfo`/`writestr`/`etree`, or import a private hwpx name.
Viewer detection and visual-review batch evidence orchestration are approved
skill support roles: they select/report an external viewer and aggregate
evidence, but do not implement HWPX document, workflow, policy, or renderer
behavior.
