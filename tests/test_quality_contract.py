# SPDX-License-Identifier: Apache-2.0
"""Phase F — MCP quality contract tests (VisualComplete plan §2 F).

Pins: every write surfaces a VisualCompleteReport; the capability handshake fails
closed on skew; an elevated gate failure becomes a structured, retry-able error
carrying FIELD_OVERFLOW/… codes + suggestedRetry.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpx_automation import quality as Q
from hwpx_automation import server as server_module
from hwpx_automation.server import apply_edits, create_document, mcp_server_health


def _doc(tmp_path: Path) -> str:
    path = str(tmp_path / "d.hwpx")
    create_document(path)
    return path


# --------------------------------------------------------------------------- #
# Every write surfaces a VisualCompleteReport.
# --------------------------------------------------------------------------- #
def test_apply_edits_returns_visual_complete(tmp_path: Path):
    res = apply_edits(_doc(tmp_path), [{"op": "add_paragraph", "text": "안녕하세요"}])
    assert res["ok"] is True
    vc = res["visualComplete"]
    assert set(vc) >= {"ok", "visualComplete", "status", "errorCodes", "warnings"}
    assert vc["status"] == "unverified"  # transparent default: open-safe, not rendered


def test_dry_run_also_reports_visual_complete(tmp_path: Path):
    res = apply_edits(_doc(tmp_path), [{"op": "add_paragraph", "text": "x"}], dry_run=True)
    assert res["dryRun"] is True and res["wouldSave"] is True
    assert "visualComplete" in res


# --------------------------------------------------------------------------- #
# Capability handshake (doctor) + policy resolution.
# --------------------------------------------------------------------------- #
def test_doctor_reports_capability_handshake():
    cap = mcp_server_health()["capability"]
    assert cap["handshake"] == "hwpx.capability.v1"
    assert set(cap["versions"]) == {"core", "automation", "mcp", "plugin"}
    assert cap["versions"]["automation"] == cap["versions"]["mcp"]
    assert cap["minAutomationVersion"] == cap["minMcpVersion"]
    assert cap["savePipelineAvailable"] is True
    assert isinstance(cap["hash"], str) and cap["ok"] is True
    assert cap["writesBlocked"] is False


def test_capability_state_judges_release_combo_as_healthy(
    monkeypatch: pytest.MonkeyPatch,
):
    """WP-F handshake-floor guard (release plan item B): the coordinated
    release combo (core 6.3.0, automation 7.0.3) must clear the capability
    skew check under whatever MIN_PYTHON_HWPX/MIN_AUTOMATION_VERSION floor
    is pinned at merge time — a regression here would fail-closed-reject a
    healthy post-release stack."""

    monkeypatch.setattr(
        Q,
        "package_version",
        lambda package: {
            "python-hwpx": "6.3.0",
            "python-hwpx-automation": "7.0.3",
        }[package],
    )
    state = Q.capability_state()
    assert state["skew"] == []
    assert state["ok"] is True
    assert state["versions"]["core"] == "6.3.0"
    assert state["versions"]["automation"] == "7.0.3"
    assert state["versions"]["mcp"] == "7.0.3"  # 6.x compatibility alias


def test_resolve_policy_default_is_transparent():
    pol = Q.resolve_policy(None)
    assert pol.render_check == "off"
    assert pol.require_visual_complete is False
    assert pol.layout_lint == "off"


def test_resolve_policy_strict_and_dict_override():
    strict = Q.resolve_policy("strict")
    assert strict.overflow_policy == "fail" and strict.layout_lint == "strict"
    blended = Q.resolve_policy({"mode": "transparent", "overflowPolicy": "fail", "layoutLint": "strict"})
    assert blended.overflow_policy == "fail" and blended.layout_lint == "strict"
    assert blended.render_check == "off"  # stayed on the transparent base


# --------------------------------------------------------------------------- #
# Fail-closed on capability skew.
# --------------------------------------------------------------------------- #
_SKEW = {
    "versions": {
        "core": "2.11.1",
        "automation": "2.4.1",
        "mcp": "2.4.1",
        "plugin": "x",
    },
    "minPythonHwpx": "2.24.1",
    "minAutomationVersion": "2.18.1",
    "minMcpVersion": "2.18.1",
    "minSkillVersion": "0.1.25",
    "savePipelineAvailable": False,
    "toolContractHash": "contractdeadbeef",
    "hash": "deadbeef",
    "skew": ["python-hwpx is missing the hwpx.quality SavePipeline gate"],
    "ok": False,
}


def test_skew_fails_closed_blocks_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = _doc(tmp_path)
    monkeypatch.setattr(Q, "capability_state", lambda: _SKEW)
    with pytest.raises(Q.CapabilitySkewError):
        apply_edits(path, [{"op": "add_paragraph", "text": "blocked"}])


def test_skew_doctor_reports_writes_blocked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server_module.quality_contract, "capability_state", lambda: _SKEW)
    cap = mcp_server_health()["capability"]
    assert cap["ok"] is False
    assert cap["writesBlocked"] is True


def test_fail_closed_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Q, "capability_state", lambda: _SKEW)
    monkeypatch.setenv("HWPX_MCP_REQUIRE_CAPABILITY", "0")
    Q.assert_write_capability()  # expert/debug bypass → no raise despite skew


# --------------------------------------------------------------------------- #
# Elevated gate failure → structured, retry-able error.
# --------------------------------------------------------------------------- #
def _failing_report():
    from hwpx.quality.report import (
        AestheticReport,
        FormReport,
        LayoutReport,
        OpenSafetyReport,
        QualityError,
        SemanticReport,
        VisualCompleteReport,
    )
    from hwpx.quality.rendering import VisualReport

    return VisualCompleteReport(
        ok=False,
        output_path=None,
        visual_complete=False,
        open_safety=OpenSafetyReport.passed(),
        semantic=SemanticReport.passed(),
        form=FormReport(ok=False, errors=["FIELD_OVERFLOW: value overflows the slot"]),
        layout=LayoutReport.passed(),
        visual=VisualReport(ok=False, render_checked=True, overflow_detected=True),
        aesthetic=AestheticReport.passed(),
        errors=[
            QualityError("FIELD_OVERFLOW", "value overflows the slot",
                         suggested_retry={"action": "shrink_or_shorten"}),
        ],
        visual_complete_status="failed",
        render_checked=True,
    )


def test_quality_gate_error_carries_codes_and_retry():
    err = Q.QualityGateError(_failing_report())
    assert err.code == "FIELD_OVERFLOW"
    assert "FIELD_OVERFLOW" in err.block["errorCodes"]
    assert err.block["suggestedRetry"]["code"] == "FIELD_OVERFLOW"
    assert err.block["suggestedRetry"]["action"] == "shrink_or_shorten"
    assert err.block["ok"] is False


def test_save_through_pipeline_raises_quality_gate_error_on_gate_fail(tmp_path: Path):
    report = _failing_report()

    class FakeDoc:
        def save_report(self, output_path, quality=None):
            return report

    with pytest.raises(Q.QualityGateError) as excinfo:
        Q.save_through_pipeline(FakeDoc(), tmp_path / "x.hwpx", quality="strict")
    assert excinfo.value.code == "FIELD_OVERFLOW"


def test_version_comparison_is_pep440_aware():
    # The fail-closed handshake must not trip on a healthy 2-part version, and a
    # pre-release of the boundary must still count as older.
    assert not Q._version_lt("2.12.0", "2.12.0")
    assert not Q._version_lt("2.12", "2.12.0")  # would falsely skew before the fix
    assert not Q._version_lt("2.12.1", "2.12.0")
    assert not Q._version_lt("2.13", "2.12.0")
    assert Q._version_lt("2.11.9", "2.12.0")
    assert Q._version_lt("2.12.0rc1", "2.12.0")
    assert Q._version_lt("2.12.0.dev1", "2.12.0")


def test_real_strict_save_fails_closed_without_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # With an explicitly unavailable backend, a real strict save cannot reach
    # visual_complete=true; it fails the gate with VISUAL_COMPLETE_FAILED and an
    # empty per-error code list (the render never ran).
    from hwpx.document import HwpxDocument
    from hwpx.quality.rendering import UnavailableRenderBackend
    from hwpx_automation.office import rendering

    monkeypatch.setattr(
        rendering,
        "resolve_hancom_backend",
        lambda **_options: UnavailableRenderBackend(),
    )

    path = _doc(tmp_path)
    doc = HwpxDocument.open(path)
    try:
        with pytest.raises(Q.QualityGateError) as excinfo:
            Q.save_through_pipeline(doc, tmp_path / "strict.hwpx", quality="strict")
    finally:
        doc.close()
    assert excinfo.value.code == "VISUAL_COMPLETE_FAILED"
    assert excinfo.value.block["errorCodes"] == []
    assert excinfo.value.block["status"] == "unverified"


def _fake_request(name: str, arguments: dict):
    from types import SimpleNamespace

    return SimpleNamespace(params=SimpleNamespace(name=name, arguments=arguments))


def test_strict_handler_converts_skew_to_structured_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    path = _doc(tmp_path)
    monkeypatch.setattr(server_module.quality_contract, "capability_state", lambda: _SKEW)
    req = _fake_request("apply_edits", {"filename": path, "operations": [{"op": "add_paragraph", "text": "x"}]})
    err = asyncio.run(server_module._strict_call_tool_handler(req))
    assert "CAPABILITY_SKEW" in err.message
    assert err.data["errorCode"] == "CAPABILITY_SKEW"
    assert "capability" in err.data


def test_strict_handler_converts_gate_error_to_structured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import asyncio

    path = _doc(tmp_path)
    report = _failing_report()

    def boom(document, output_path, quality=None):
        raise Q.QualityGateError(report)

    monkeypatch.setattr(server_module.quality_contract, "save_through_pipeline", boom)
    req = _fake_request("apply_edits", {"filename": path, "operations": [{"op": "add_paragraph", "text": "x"}]})
    err = asyncio.run(server_module._strict_call_tool_handler(req))
    assert err.data["errorCode"] == "FIELD_OVERFLOW"
    assert err.data["visualComplete"]["suggestedRetry"]["code"] == "FIELD_OVERFLOW"


def test_visual_complete_block_passthrough_shape():
    from hwpx.quality.report import VisualCompleteReport, OpenSafetyReport, SemanticReport, FormReport, LayoutReport, AestheticReport
    from hwpx.quality.rendering import VisualReport

    ok_report = VisualCompleteReport(
        ok=True, output_path="x.hwpx", visual_complete=False,
        open_safety=OpenSafetyReport.passed(), semantic=SemanticReport.passed(),
        form=FormReport.passed(), layout=LayoutReport.passed(),
        visual=VisualReport(ok=True, render_checked=False),
        aesthetic=AestheticReport.passed(),
        visual_complete_status="unverified", render_checked=False,
    )
    block = Q.visual_complete_block(ok_report)
    assert block["ok"] is True and block["errorCodes"] == [] and block["suggestedRetry"] is None
