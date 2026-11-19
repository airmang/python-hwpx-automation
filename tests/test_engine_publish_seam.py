# SPDX-License-Identifier: Apache-2.0
"""The one python-hwpx private name this package depends on: ``SavePipeline._publish``.

``GuardedSavePipeline`` subclasses replace it so a publication goes through the workspace guard.
python-hwpx 7.0 changed what it returns (a path -> a path and whether a stream was read back) and
nothing here noticed: the engine never called the replacements. These tests pin the engine's shape
and run a publish the engine makes through a replacement.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

from hwpx import HwpxDocument
from hwpx.quality import SavePipeline

from hwpx_automation.mixed_form import _WorkspaceSavePipeline
from hwpx_automation.office.agent._batch_publication import GuardedSavePipeline, _BatchSavePipeline


def test_the_engine_seam_has_the_shape_the_replacements_keep() -> None:
    parameters = list(inspect.signature(SavePipeline._publish).parameters)
    assert parameters == ["self", "data", "output_path", "output_stream"]
    assert get_type_hints(SavePipeline._publish)["return"] == tuple[str | None, bool]
    for replacement in (_BatchSavePipeline, _WorkspaceSavePipeline):
        assert issubclass(replacement, GuardedSavePipeline)
        assert list(inspect.signature(replacement._publish).parameters) == parameters
        assert inspect.signature(replacement._publish).return_annotation == "tuple[str | None, bool]"


def test_a_publish_the_engine_makes_through_a_replacement_reports_its_path(tmp_path: Path) -> None:
    """``SavePipeline.run(publish="on_pass")`` unpacks what ``_publish`` returns."""

    written: list[bytes] = []

    class Recording(GuardedSavePipeline):
        def _publish(self, data, output_path, output_stream):  # type: ignore[no-untyped-def]
            written.append(bytes(data))
            return str(output_path), True

    document = HwpxDocument.new()
    document.add_paragraph("본문")
    target = tmp_path / "out.hwpx"

    report = document.save(target, pipeline=Recording())

    assert written and report.path == str(target)
    assert not target.exists()  # the replacement published; the engine wrote nothing itself
