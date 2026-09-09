# SPDX-License-Identifier: Apache-2.0
"""Parity between the MCP rendering owner and core's frozen 4.x visual shape.

``hwpx.visual.oracle``/``page_qa``/``qa_metrics``/``fixture_corpus``/
``hancom_worker`` — the application half of ``hwpx.visual`` — are scheduled
for physical deletion from core once python-hwpx is reduced to a library, so
this file no longer imports them. Instead:

- Structural claims (exports, signatures, dataclass fields) compare the live
  automation modules' ``tests.parity_fingerprint.fingerprint()`` against
  ``tests/parity_fingerprints/visual.json``, frozen from core while it still
  existed.
- Behavioural claims with a deterministic, fixed-input value (the
  structural-only oracle report, the fixture/page-QA/metrics projections,
  and the deterministic worker's success/failure JSON) compare against
  ``tests/parity_fingerprints/visual.golden.json`` — values captured from
  that same frozen core commit and confirmed identical to MCP's own output
  at freeze time.

One assertion genuinely could not be preserved and was reduced rather than
dropped: ``test_reachable_selection_and_exhausted_budget_...`` used to prove
core's *and* MCP's ``resolve_oracle`` pick the same backend class under the
same monkeypatched availability. That needs live monkeypatching of
``WindowsComOracle``/``MacHancomOracle`` class methods, which cannot be
expressed against a frozen fingerprint or a golden value — there is no
single "the call returned X" to snapshot; the point of the test is the
branch it takes. It now monkeypatches and asserts only MCP's own class,
checked against ``expectedBackend`` in
``tests/visual_runtime_parity/fixtures/scenarios.json`` (already a fixture,
not a core import) instead of against a live core call. This drops the "core
and MCP agree" half of the claim; MCP's own selection behaviour and the
render-doesn't-mutate-the-source guarantee are still fully exercised. See
the task report for this gap.

The owned-render recovery change explicitly adds a cancellation callback and
backend/input binding fields, and gives artifacts immutable content addresses.
Those exact additive differences are asserted below against a copy of the old
receipt; the historical frozen JSON files are never regenerated.
"""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path

from parity_fingerprint import fingerprint

from hwpx_automation.office.rendering import fixture_corpus as mcp_fixture
from hwpx_automation.office.rendering import oracle as mcp_oracle
from hwpx_automation.office.rendering import page_qa as mcp_page_qa
from hwpx_automation.office.rendering import qa_metrics as mcp_metrics
from hwpx_automation.office.rendering import worker as mcp_worker

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads(
    (
        ROOT
        / "tests"
        / "visual_runtime_parity"
        / "fixtures"
        / "scenarios.json"
    ).read_text(encoding="utf-8")
)
_PARITY_FIXTURES = Path(__file__).parent / "parity_fingerprints"
FROZEN = json.loads((_PARITY_FIXTURES / "visual.json").read_text(encoding="utf-8"))[
    "modules"
]
GOLDEN = json.loads(
    (_PARITY_FIXTURES / "visual.golden.json").read_text(encoding="utf-8")
)["calls"]


def _scenario(identifier: str) -> dict[str, object]:
    return next(
        item for item in SCENARIOS["scenarios"] if item["id"] == identifier
    )


def _clean_fixture(tmp_path: Path) -> Path:
    # The page bytes are a checked-in fixture, not encoded at test time: the
    # golden receipt freezes this file's sha256, and PNG encoder output varies
    # across Pillow builds/platforms even for identical pixels. Regenerate via
    # tests/visual_runtime_parity/fixtures/ (same 150-point pattern) only when
    # deliberately refreezing the golden.
    page = tmp_path / "page.png"
    page.write_bytes(
        (
            Path(__file__).parent
            / "visual_runtime_parity"
            / "fixtures"
            / "page_clean.png"
        ).read_bytes()
    )
    manifest = {
        "schema": "hwpx.visual-fixture-manifest/v1",
        "taxonomyVersion": "hwpx-visual-defects/1.0",
        "assurance": "fixture",
        "cases": [
            {
                "id": "clean-parity",
                "classification": "clean",
                "pages": [
                    {
                        "page": 0,
                        "path": page.name,
                        "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
                    }
                ],
                "annotations": [],
                "provenance": {"kind": "synthetic-parity"},
            }
        ],
    }
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    return target


def test_frozen_scenario_corpus_covers_all_required_paths() -> None:
    assert SCENARIOS["schema"] == "hwpx.visual-runtime-parity/v1"
    assert {item["id"] for item in SCENARIOS["scenarios"]} == {
        "structural-only",
        "oracle-unreachable",
        "reachable-mac-selection",
        "bounded-timeout",
        "deterministic-worker",
        "fixture-qa",
    }


def test_frozen_visual_modules_shape_matches_frozen_core() -> None:
    # hwpx.visual.oracle.__all__ re-exports WordBox (from hwpx.form_fit.wordbox,
    # for convenience) but hwpx_automation.office.rendering.oracle does not —
    # a pre-existing asymmetry, not something this freeze changed. The
    # pre-freeze version of this file never asserted full __all__ parity for
    # oracle either (unlike the agent/authoring/exam parity files), only
    # specific behaviour; excluded here rather than silently made to pass.
    oracle_fingerprint = fingerprint(mcp_oracle)
    frozen_oracle = {
        name: entry
        for name, entry in FROZEN["hwpx.visual.oracle"].items()
        if name != "WordBox"
    }
    assert oracle_fingerprint == frozen_oracle

    assert fingerprint(mcp_page_qa) == FROZEN["hwpx.visual.page_qa"]
    assert fingerprint(mcp_metrics) == FROZEN["hwpx.visual.qa_metrics"]
    assert fingerprint(mcp_fixture) == FROZEN["hwpx.visual.fixture_corpus"]
    expected_worker = copy.deepcopy(FROZEN["hwpx.visual.hancom_worker"])
    expected_worker["SerializedHancomWorker"]["methods"]["render"] = (
        "(self, job: 'WorkerJob', *, cancelled: 'Callable[[], bool] | None' = None) -> 'WorkerResult'"
    )
    for field in ("backend", "input_content_hash"):
        expected_worker["WorkerResult"]["fields"][field] = {"type": "str | None", "hasDefault": True}
    assert fingerprint(mcp_worker) == expected_worker


def test_structural_only_report_matches_frozen_core(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HWPX_ORACLE_STRUCTURAL_ONLY", "1")
    mcp_backend = mcp_oracle.resolve_oracle()
    expected = _scenario("structural-only")

    assert type(mcp_backend).__name__ == expected["expectedBackend"] == (
        GOLDEN["structuralOnly"]["backendType"]
    )
    mcp_report = mcp_oracle.visual_check(
        "before.hwpx",
        "after.hwpx",
        oracle=mcp_backend,
    )
    assert mcp_report.to_dict() == GOLDEN["structuralOnly"]["reportToDict"]
    assert mcp_report.render_checked is expected["renderChecked"]
    assert str(expected["terminalReason"]) in mcp_report.warnings[0]


def test_reachable_selection_and_exhausted_budget_do_not_mutate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("HWPX_ORACLE_STRUCTURAL_ONLY", raising=False)
    monkeypatch.setattr(
        mcp_oracle.WindowsComOracle,
        "available",
        lambda self: False,
    )
    monkeypatch.setattr(mcp_oracle.MacHancomOracle, "available", lambda self: True)

    mcp_backend = mcp_oracle.resolve_oracle(budget_seconds=0.0)
    expected = _scenario("reachable-mac-selection")
    assert type(mcp_backend).__name__ == expected["expectedBackend"]
    assert mcp_backend.budget_seconds == 0.0

    source = tmp_path / "input.hwpx"
    source.write_bytes(b"immutable-input")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert mcp_backend.render_pdf(str(source), str(tmp_path / "mcp.pdf")) is None
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not (tmp_path / "mcp.pdf").exists()


def test_fixture_loader_page_qa_and_metrics_projections_match_frozen_core(
    tmp_path: Path,
) -> None:
    manifest = _clean_fixture(tmp_path)
    mcp_corpus = mcp_fixture.load_fixture_manifest(manifest)

    assert mcp_corpus.receipt(mcp_corpus.cases[0]) == GOLDEN["fixtureQa"]["receipt"]
    assert mcp_page_qa.inspect_fixture_case(mcp_corpus.cases[0]).to_dict() == (
        GOLDEN["fixtureQa"]["qaToDict"]
    )
    assert mcp_metrics.measure_fixture_corpus(mcp_corpus) == (
        GOLDEN["fixtureQa"]["metrics"]
    )


def test_serialized_worker_success_and_hash_failure_match_frozen_core(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.hwpx"
    source.write_bytes(b"worker-parity")

    def fake_rasterize(_pdf: Path, destination: Path, _dpi: int) -> list[Path]:
        page = destination / "page-0001.png"
        page.write_bytes(b"PNG-PARITY")
        return [page]

    monkeypatch.setattr(
        mcp_worker.SerializedHancomWorker,
        "_rasterize",
        staticmethod(fake_rasterize),
    )
    digest = mcp_worker.sha256_file(source)
    mcp = mcp_worker.SerializedHancomWorker(
        tmp_path / "mcp-worker",
        session_factory=mcp_worker.DeterministicFakeSession,
        worker_version="parity",
    )
    try:
        mcp_success = mcp.render(mcp_worker.WorkerJob("success", source, digest))
        expected_success = copy.deepcopy(GOLDEN["worker"]["successToJson"])
        expected_success.update(backend="fake-worker", input_content_hash=digest)
        bundle_hash = hashlib.sha256("\n".join(
            item["content_hash"] for item in expected_success["artifacts"]
        ).encode()).hexdigest()
        for item in expected_success["artifacts"]:
            item["relative_path"] = "success/" + bundle_hash + "/" + Path(item["relative_path"]).name
        assert json.loads(mcp_success.to_json()) == expected_success
        assert mcp_success.terminal_reason == _scenario(
            "deterministic-worker"
        )["terminalReason"]

        mcp_failure = mcp.render(
            mcp_worker.WorkerJob("failure", source, "sha256:wrong")
        )
        expected_failure = copy.deepcopy(GOLDEN["worker"]["failureToJson"])
        expected_failure.update(backend=None, input_content_hash="sha256:wrong")
        assert json.loads(mcp_failure.to_json()) == expected_failure
        assert mcp_failure.terminal_reason == "INPUT_HASH_MISMATCH"
    finally:
        mcp.close()
