# SPDX-License-Identifier: Apache-2.0
"""MCP owns Hancom discovery and injection into the neutral core save gate."""
from __future__ import annotations

from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.quality import QualityPolicy, SavePipeline
from hwpx.quality.rendering import VisualReport

from hwpx_automation import quality as quality_contract
from hwpx_automation.office import rendering


class _FakeOracle:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready

    def available(self) -> bool:
        return self.ready


def test_hancom_adapter_runs_visual_check(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str | None, str]] = []

    def _check(before, after, **_options):
        calls.append((before, after))
        return VisualReport(ok=True, render_checked=True)

    monkeypatch.setattr(rendering, "visual_check", _check)
    backend = rendering.HancomRenderBackend(_FakeOracle())
    pipeline = SavePipeline(oracle=backend)
    document = HwpxDocument.new()
    document.add_paragraph("render adapter")

    report = pipeline.run(
        document.to_bytes(),
        output_path=tmp_path / "out.hwpx",
        quality=QualityPolicy(
            render_check="required",
            require_visual_complete=True,
        ),
    )

    assert report.ok is True
    assert report.visual_complete_status == "verified"
    assert len(calls) == 1


def _render_policy() -> QualityPolicy:
    return QualityPolicy(render_check="required", require_visual_complete=True)


def _bind_fake_hancom(monkeypatch, *, ready: bool = True) -> list[int]:
    """Make resolve_hancom_backend hand out a fake Hancom; return the call record."""

    calls: list[int] = []

    def _resolve(*, dpi: int = 150, **_options):
        calls.append(dpi)
        return rendering.HancomRenderBackend(_FakeOracle(ready=ready))

    monkeypatch.setattr(rendering, "resolve_hancom_backend", _resolve)
    monkeypatch.setattr(
        rendering,
        "visual_check",
        lambda before, after, **_options: VisualReport(ok=True, render_checked=True),
    )
    return calls


def test_no_private_save_pipeline_is_left() -> None:
    """python-hwpx 7.0 (#745) dropped the document's private ``_save_pipeline``; an
    assignment to it is silently ignored, so nothing here may still use it."""

    root = Path(__file__).resolve().parents[1]
    attribute = "_save" + "_pipeline"  # split so this file does not find itself
    users = [
        str(path.relative_to(root))
        for folder in ("src", "tests")
        for path in (root / folder).rglob("*.py")
        if f".{attribute} " in path.read_text(encoding="utf-8")
        or f".{attribute}=" in path.read_text(encoding="utf-8")
        or f'"{attribute}"' in path.read_text(encoding="utf-8")
    ]
    assert users == []


def test_quality_save_renders_with_hancom_through_the_pipeline_argument(monkeypatch, tmp_path) -> None:
    calls = _bind_fake_hancom(monkeypatch)
    document = HwpxDocument.new()
    document.add_paragraph("render through pipeline=")
    target = tmp_path / "out.hwpx"

    report = quality_contract.save_through_pipeline(document, target, quality=_render_policy())

    assert calls == [150]  # core asked for the renderer once, with its dpi
    assert report.ok is True
    assert report.visual_complete_status == "verified"
    assert target.is_file()


def test_quality_save_does_not_start_hancom_when_the_policy_does_not_render(monkeypatch, tmp_path) -> None:
    calls = _bind_fake_hancom(monkeypatch)
    document = HwpxDocument.new()
    document.add_paragraph("transparent")
    target = tmp_path / "out.hwpx"

    report = quality_contract.save_through_pipeline(document, target, quality=QualityPolicy.transparent())

    assert calls == []
    assert report.ok is True
    assert target.is_file()


def test_refused_render_returns_the_report_and_writes_nothing(monkeypatch, tmp_path) -> None:
    calls = _bind_fake_hancom(monkeypatch, ready=False)
    document = HwpxDocument.new()
    document.add_paragraph("no hancom")
    target = tmp_path / "out.hwpx"

    report = rendering.save_gate_report(
        document, target, quality=_render_policy(), pipeline=rendering.hancom_save_pipeline()
    )

    assert calls == [150]
    assert report.ok is False
    assert not target.exists()
    with pytest.raises(quality_contract.QualityGateError):
        quality_contract.save_through_pipeline(document, target, quality=_render_policy())
    assert not target.exists()


def test_save_gate_report_without_a_pipeline_keeps_core_s_non_rendering_gate(monkeypatch, tmp_path) -> None:
    calls = _bind_fake_hancom(monkeypatch)
    document = HwpxDocument.new()
    document.add_paragraph("core gate")

    report = rendering.save_gate_report(document, tmp_path / "out.hwpx", quality=_render_policy())

    assert calls == []
    assert report.ok is False  # required render, no renderer: refused as before
