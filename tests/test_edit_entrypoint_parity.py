"""The same external form plan through Python, actual CLI parser, and MCP stdio."""

from __future__ import annotations
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import pytest
from hwpx import HwpxDocument
from hwpx_automation.office.agent import apply_mixed_form_fill
from hwpx_automation.office.agent.model import AgentContractError
from hwpx_automation.office.agent.cli import main

FIXTURES = Path(__file__).parent / "fixtures/edit-fidelity"


def plan(source, output):
    return {
        "schemaVersion": "hwpx.mixed-form-plan/v1",
        "source": str(source),
        "output": str(output),
        "expectedRevision": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "idempotencyKey": "entrypoint-test",
        "dryRun": False,
        "overwrite": True,
        "quality": "transparent",
        "verificationRequirements": [
            "package",
            "reopen",
            "openSafety",
            "semanticDiff",
            "bytePreservation",
        ],
        "operations": [
            {
                "operationId": "grade",
                "target": {
                    "kind": "labelCell",
                    "sectionPath": "/section[1]",
                    "tableIndex": 0,
                    "cellAnchor": {"label": "개똥이", "direction": "right"},
                },
                "value": "90",
            }
        ],
    }


@pytest.mark.parametrize("entry", ["python", "cli", "mcp"])
@pytest.mark.parametrize(
    "case", ["apply", "replay", "stale", "missing", "count", "duplicate", "partial"]
)
def test_external_form_guard_parity(entry, case, tmp_path, mcp_server_factory):
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    shutil.copyfile(
        FIXTURES / ("sample1.hwpx" if case == "partial" else "table.hwpx"), source
    )
    original = source.read_bytes()
    output.write_bytes(b"existing output")
    request = plan(source, output)
    if case == "stale":
        request["expectedRevision"] = "sha256:" + "0" * 64
    if case == "missing":
        request["operations"][0]["target"] = {
            "kind": "canonicalPath",
            "path": '/section[1]/paragraph[@id="missing"]',
        }
    if case == "count":
        request["operations"][0]["target"] = {
            "kind": "bodyAnchor",
            "sectionPath": "/section[1]",
            "anchor": "C반",
            "expectedCount": 2,
        }
    if case == "duplicate":
        request["operations"][0]["target"]["cellAnchor"]["label"] = "77"
    if case == "partial":
        request["operations"][0]["target"] = {
            "kind": "bodyAnchor",
            "sectionPath": "/section[1]",
            "anchor": "수학",
            "expectedCount": 1,
        }
    count = 2 if case == "replay" else 1
    if entry == "python":
        store = {}
        results = []
        for _ in range(count):
            try:
                results.append(
                    apply_mixed_form_fill(
                        deepcopy(request), idempotency_store=store
                    ).to_dict()
                )
            except AgentContractError as exc:
                results.append(
                    {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
                )
    elif entry == "cli":
        stdout = io.StringIO()
        stderr = io.StringIO()
        main(
            ["batch", "-", "--jsonl-input"],
            stdin=io.StringIO("\n".join(json.dumps(request) for _ in range(count))),
            stdout=stdout,
            stderr=stderr,
        )
        payload = json.loads(stdout.getvalue() or stderr.getvalue())
        results = payload if isinstance(payload, list) else [payload]
    else:
        client = mcp_server_factory(
            cwd=tmp_path, extra_env={"HWPX_ORACLE_STRUCTURAL_ONLY": "1"}
        )
        results = []
        for _ in range(count):
            raw = client.call_tool_raw("apply_form_fill", {"plan": request})
            if "error" in raw:
                client.assert_error_object(raw["error"], require_data=True)
                payload = {"ok": False, "error": raw["error"]["data"]["error"]}
            else:
                payload = client.parse_tool_result_payload(raw["result"])
            results.append(payload)
    assert source.read_bytes() == original
    if case in {"apply", "replay"}:
        assert all(r.get("ok") is True for r in results), results
        with HwpxDocument.open(output) as doc:
            assert doc.tables.all[0].cell(1, 1).text == "90"
        if case == "replay":
            assert results[-1]["verificationReport"]["idempotency"]["replayed"] is True
    else:
        assert all(r.get("ok") is False for r in results), results
        assert output.read_bytes() == b"existing output"
        for result in results:
            if case == "count" and entry == "mcp":
                # MCP rejects expectedCount=2 at its published const=1 schema.
                assert result["error"]["code"] == "INVALID_ARGUMENT"
                assert result["error"]["category"] == "validation"
                continue
            assert result["error"]["code"] in {
                "stale_revision",
                "not_found",
                "invalid_syntax",
                "invalid_params",
                "ambiguous_target",
            }, result


def test_indexed_navigation_is_read_only_and_revision_bound(tmp_path):
    from hwpx_automation.office.agent import HwpxAgentDocument

    source = tmp_path / "source.hwpx"
    shutil.copyfile(FIXTURES / "sample1.hwpx", source)
    with HwpxAgentDocument.open(source) as doc:
        # This first paragraph has a native ID; positional spelling is a read alias only.
        alias = "/section[1]/paragraph[1]"
        with pytest.raises(AgentContractError) as missing_revision:
            doc.get(alias)
        assert missing_revision.value.code == "volatile_target"
        canonical = doc.get(alias, expected_revision=doc.revision).path
        assert "@id=" in canonical
        with pytest.raises(AgentContractError) as mutation_target:
            doc.resolve_record(alias, expected_revision=doc.revision)
        assert mutation_target.value.code == "not_found"
        with pytest.raises(AgentContractError) as stale:
            doc.get(alias, expected_revision="sha256:" + "0" * 64)
        assert stale.value.code == "stale_revision"


@pytest.mark.parametrize("case", ["apply", "dry-run", "tampered"])
def test_cli_compiled_plan_keeps_domain_validation(case, tmp_path):
    from hwpx_automation.office.agent import plan_mixed_form_fill

    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    shutil.copyfile(FIXTURES / "table.hwpx", source)
    original = source.read_bytes()
    output.write_bytes(b"existing output")
    request = plan(source, output)
    if case == "dry-run":
        request["dryRun"] = True
    compiled = plan_mixed_form_fill(request).to_dict()
    if case == "tampered":
        compiled["batch"]["commands"][0]["properties"]["text"] = "99"
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        ["batch", "-"],
        stdin=io.StringIO(json.dumps(compiled)),
        stdout=stdout,
        stderr=stderr,
    )
    result = json.loads(stdout.getvalue() or stderr.getvalue())
    assert source.read_bytes() == original
    if case == "tampered":
        assert code != 0 and result["ok"] is False
        assert result["error"]["code"] == "verification_failed"
    else:
        assert code == 0 and result["ok"] is True
    if case != "apply":
        assert output.read_bytes() == b"existing output"
    else:
        with HwpxDocument.open(output) as doc:
            assert doc.tables.all[0].cell(1, 1).text == "90"
