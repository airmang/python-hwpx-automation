# SPDX-License-Identifier: Apache-2.0
"""render_preview viewer mode (S-092 P3).

Extends render_preview with an additive optional ``viewer`` parameter that emits
a self-contained scrollable document viewer (equations as native MathML) under
``structuredContent.viewer``. These tests pin:

* default (no ``viewer``) output shape is unchanged — no ``viewer`` block;
* viewer mode renders the equation fixture to MathML and reports the honest
  fidelity tier;
* the reused guards (non-HWPX rejection, workspace-outside write refusal) still
  fire in viewer mode;
* the inline-HTML byte cap degrades to path-only.
"""

from __future__ import annotations


import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from hwpx.document import HwpxDocument

from hwpx_automation import server
from hwpx_automation.ops_services.preview_export import (
    _count_equation_modes,
    _equation_tier,
)
from hwpx_automation.tool_contract import bound_tool_registry
from hwpx_automation.workspace import WorkspacePathError

_EQUATION_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "equation_preview" / "equation_p0.hwpx"
)


def _plain_source(tmp_path: Path) -> Path:
    source = tmp_path / "plain.hwpx"
    document = HwpxDocument.new()
    document.add_paragraph("Preview title")
    document.save(source)
    return source


# --------------------------------------------------------------------------- #
# Characterization: default behavior is unchanged (no viewer block).           #
# --------------------------------------------------------------------------- #
def test_render_preview_default_omits_viewer_block(tmp_path: Path) -> None:
    source = _plain_source(tmp_path)

    result = server.render_preview(
        str(source), output_dir=str(tmp_path / "preview"), screenshot="off"
    )
    manifest = result.structuredContent

    # The manifest keys stay exactly the pre-viewer set; the additive field is
    # absent (default None is dropped from structuredContent) when not requested.
    assert manifest["status"] == "html_only"
    assert "viewer" not in manifest
    assert set(manifest) == {
        "schemaVersion",
        "status",
        "generatedAt",
        "sourcePath",
        "outputDir",
        "htmlPath",
        "manifestPath",
        "visualReviewPath",
        "mode",
        "pageCount",
        "pages",
        "screenshots",
        "screenshotEngine",
        "warnings",
        "suggestion",
    }
    assert not list(
        Draft202012Validator(
            bound_tool_registry().by_name()["render_preview"].output_schema
        ).iter_errors(manifest)
    )


# --------------------------------------------------------------------------- #
# Viewer mode: MathML fidelity + honest tier surface.                          #
# --------------------------------------------------------------------------- #
def test_render_preview_viewer_renders_mathml(tmp_path: Path) -> None:
    output_dir = tmp_path / "viewer-out"

    result = server.render_preview(
        str(_EQUATION_FIXTURE),
        output_dir=str(output_dir),
        screenshot="off",
        viewer=True,
    )
    manifest = result.structuredContent
    viewer = manifest["viewer"]

    assert manifest["status"] == "html_only"
    # Equations render as native MathML (latex2mathml, the [preview] extra, present in the venv).
    assert viewer["equationLibrary"] == "latex2mathml"
    assert viewer["equationRendering"] == {
        "mathml": 3,
        "latexFallback": 0,
        "scriptFallback": 0,
    }
    assert viewer["fidelityTier"].endswith("; equations=mathml")
    # Any of the three honest tiers: an engine that places every equation gives the full engine tier.
    assert viewer["fidelityTier"].split(";")[0] in {
        "text-approx-pagination", "partial-engine-estimated-pagination", "engine-estimated-pagination",
    }
    assert "<math" in viewer["html"]
    assert viewer["byteSize"] == len(viewer["html"].encode("utf-8"))
    assert viewer["pageCount"] >= 1

    # The viewer HTML is written to the workspace-guarded output directory.
    assert viewer["viewerPath"].endswith("viewer.html")
    assert (output_dir / "viewer.html").exists()

    # structuredContent validates against the owned output schema.
    assert not list(
        Draft202012Validator(
            bound_tool_registry().by_name()["render_preview"].output_schema
        ).iter_errors(manifest)
    )

    # The on-disk manifest stays lean: the large inline HTML is not persisted.
    disk_manifest = json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert "html" not in disk_manifest["viewer"]
    assert disk_manifest["viewer"]["viewerPath"] == viewer["viewerPath"]


# --------------------------------------------------------------------------- #
# Reused guards still fire in viewer mode.                                      #
# --------------------------------------------------------------------------- #
def test_render_preview_viewer_rejects_non_hwpx(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-package.hwpx"
    bogus.write_text("this is not a zip", encoding="utf-8")

    with pytest.raises(ValueError, match="unable to read HWPX package"):
        server._OPS.render_preview(
            path=str(bogus),
            output_dir=str(tmp_path / "out"),
            screenshot="off",
            viewer=True,
        )


def test_render_preview_viewer_refuses_workspace_outside_output(tmp_path: Path) -> None:
    outside = Path("/hwpx-s092-outside-workspace/out")

    with pytest.raises(WorkspacePathError):
        server._OPS.render_preview(
            path=str(_EQUATION_FIXTURE),
            output_dir=str(outside),
            screenshot="off",
            viewer=True,
        )
    assert not outside.exists()


# --------------------------------------------------------------------------- #
# Inline HTML byte cap degrades to path-only (DoS guard, house pattern).        #
# --------------------------------------------------------------------------- #
def test_build_viewer_block_respects_byte_cap(tmp_path: Path) -> None:
    output_path = tmp_path / "cap-out"
    output_path.mkdir()

    block = server._OPS._services.preview_export._build_viewer_block(
        _EQUATION_FIXTURE,
        "pages",
        output_path,
        max_viewer_bytes=10,
    )

    assert block["htmlOmitted"] == "exceeds_max_viewer_bytes"
    assert "html" not in block
    # The full viewer is still written to disk under the cap.
    assert (output_path / "viewer.html").exists()
    assert block["byteSize"] > 10


# --------------------------------------------------------------------------- #
# Pure helpers.                                                                 #
# --------------------------------------------------------------------------- #
def test_count_equation_modes_counts_data_eq_markers() -> None:
    html = (
        '<span class="hwpx-equation" data-eq-mode="mathml"></span>'
        '<span class="hwpx-equation-fallback" data-eq-mode="latex"></span>'
        '<span class="hwpx-equation-fallback" data-eq-mode="script"></span>'
        '<span class="hwpx-equation" data-eq-mode="mathml"></span>'
    )
    assert _count_equation_modes(html) == {
        "mathml": 2,
        "latexFallback": 1,
        "scriptFallback": 1,
    }


def test_equation_tier_reports_worst_case() -> None:
    assert _equation_tier({"mathml": 0, "latexFallback": 0, "scriptFallback": 0}) == "none"
    assert _equation_tier({"mathml": 3, "latexFallback": 0, "scriptFallback": 0}) == "mathml"
    assert (
        _equation_tier({"mathml": 2, "latexFallback": 1, "scriptFallback": 0})
        == "latex-fallback"
    )
    assert (
        _equation_tier({"mathml": 2, "latexFallback": 1, "scriptFallback": 1})
        == "script-fallback"
    )
