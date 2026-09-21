from __future__ import annotations

from pathlib import Path

from hwpx.document import HwpxDocument
from hwpx_automation.office.authoring import create_document_from_plan


def _plan(row_count: int) -> dict:
    return {
        "schemaVersion": "hwpx.document_plan.v1",
        "title": "Inventory",
        "blocks": [
            {
                "type": "table",
                "columns": [{"key": "no", "label": "No"}, {"key": "item", "label": "Item"}],
                "rows": [
                    {"no": str(index), "item": f"asset {index}"}
                    for index in range(1, row_count + 1)
                ],
            }
        ],
    }


def test_plan_authored_long_table_flows_and_short_table_keeps_layout(tmp_path: Path) -> None:
    for row_count, expected_inline in ((2, True), (30, False)):
        path = tmp_path / f"inventory-{row_count}.hwpx"
        with create_document_from_plan(_plan(row_count)) as document:
            document.save_to_path(path)
        with HwpxDocument.open(path) as reopened:
            table = reopened.tables.all[0]
            assert table.treat_as_char is expected_inline
            assert table.element.get("pageBreak") == "CELL"
            assert table.row_count == row_count + 1
            assert table.cell(row_count, 1).text == f"asset {row_count}"
