# MCP SDK patch re-audit procedure

The server pins the MCP SDK exactly (`mcp==1.30.0` in `pyproject.toml`) and the
runtime admits exactly the audited set (`AUDITED_MCP_PATCHES` in
`src/hwpx_automation/fastmcp_adapter.py`). These two are the same set by
invariant — `tests/test_fastmcp_adapter.py::
test_resolver_pin_and_audited_set_admit_the_same_versions` fails if they drift.
Anything pip can install must also start; a version that has not been re-audited
must not install at all.

## Why exact-pin

The compatibility adapter reaches six audited private SDK access points
(`_mcp_server`, `request_handlers`, `_tool_manager`, `_tools`). A new SDK patch
can silently change those internals, so a resolver range wider than the audited
set produces installs that fail at startup — the failure mode S-081 removed.

## Admitting a new SDK patch (e.g. 1.28.2)

1. Create a scratch venv with the candidate: `pip install mcp==1.28.2` plus this
   package with the pin temporarily overridden.
2. Run the compatibility matrix:
   - `pytest tests/test_fastmcp_adapter.py tests/test_fastmcp_runtime_compatibility.py -q`
   - `pytest tests/test_tool_contract.py tests/test_tool_schemas.py -q`
   - full suite `pytest -q` if the above pass.
3. Verify the six private access points still exist and behave: the adapter's
   fail-closed guards must not fire during registration or a strict tool call.
4. Update, in ONE commit:
   - `pyproject.toml` — `mcp==<new>` (or a multi-pin via environment markers is
     NOT used; one exact version per release),
   - `AUDITED_MCP_PATCHES` — the new audited tuple,
   - `SUPPORTED_MCP_RANGE` — `==<new>`,
   - the two locked tests (`test_fastmcp_adapter.py`, `test_public_product_boundary.py`).
5. Run `scripts/check_architecture_ratchets.py` and the full suite; ship as at
   least a patch release so installers pick up the new resolver pin.

If the candidate fails step 2–3, do nothing: the pin keeps the broken patch
uninstallable, which is the intended fail-closed behavior.
