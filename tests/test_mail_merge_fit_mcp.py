# SPDX-License-Identifier: Apache-2.0
"""MCP surface for fit-aware batch fill (M2 P4 / FR-004, FR-005)."""
from __future__ import annotations

from pathlib import Path

import hwpx_automation.server as server
from hwpx.document import HwpxDocument

OVERFLOW = "아주아주아주아주아주긴이름입니다정말로깁니다"


def _narrow_cell_template(path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("안내 — {{title}}")
    table = doc.add_paragraph("").add_table(1, 2)
    table.cell(0, 0).set_text("이름")
    cell = table.cell(0, 1)
    # 5.4.0부터 add_table 셀이 실한컴 기본 안여백(좌우 510)을 갖는다 —
    # 가용폭이 그만큼 줄므로 "깨끗한 행"이 실제로 들어갈 폭을 준다.
    cell.set_size(width=4600)
    cell.set_text("{{name}}")
    doc.save(str(path))


def test_mail_merge_fit_mode_surfaces_needs_review(tmp_path):
    template = tmp_path / "tmpl.hwpx"
    _narrow_cell_template(template)
    report = server.mail_merge(
        str(template),
        data_rows=[
            {"title": "협조", "name": "홍길동"},
            {"title": "협조", "name": OVERFLOW},
        ],
        output_dir=str(tmp_path / "out"),
        fit_mode="keep",
    )
    assert report["fitAware"] is True
    review_rows = {r["rowIndex"] for r in report["needsReview"]}
    assert 2 in review_rows  # the overflow row
    assert 1 not in review_rows  # the clean row
    overflow = next(r for r in report["needsReview"] if r["rowIndex"] == 2)
    assert "overflow" in overflow["reasons"]


def test_mail_merge_without_fit_mode_is_raw(tmp_path):
    template = tmp_path / "tmpl2.hwpx"
    _narrow_cell_template(template)
    report = server.mail_merge(
        str(template),
        data_rows=[{"title": "협조", "name": OVERFLOW}],
        output_dir=str(tmp_path / "out2"),
    )
    assert report["fitAware"] is False
    assert report["needsReview"] == []
