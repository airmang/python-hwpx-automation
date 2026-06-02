# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "scripts" / "visual_review.py"
spec = importlib.util.spec_from_file_location("visual_review", SPEC)
visual_review = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(visual_review)

pytest.importorskip("hwpx")  # axis A round-trip needs python-hwpx


def test_structural_acceptance_passes_for_valid_doc(tmp_path):
    from hwpx.document import HwpxDocument

    doc = HwpxDocument.new()
    doc.add_paragraph("수용성 확인")
    path = tmp_path / "ok.hwpx"
    doc.save_to_path(path)

    result = visual_review.structural_acceptance(path)
    assert result["opens"] is True
    assert result["roundtrip_ok"] is True
    assert result["status"] == "accepted"
