import logging
from pathlib import Path
from typing import Any

import pytest

from hwpx.document import HwpxDocument
from hwpx_automation.hwpx_ops import HH_NS, HP_NS, HwpxOps
import hwpx_automation.hwpx_ops as ops_module
import hwpx_automation.ops_services.context as context_module
import hwpx_automation.ops_services.read_query as read_query_module

PNG_1X1_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/axwAqkAAAAASUVORK5CYII="
PNG_1X1_ALT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/l8EydgAAAABJRU5ErkJggg=="


@pytest.fixture()
def ops_with_sample(tmp_path) -> tuple[HwpxOps, Path]:
    sample = Path(__file__).with_name("sample.hwpx")
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    target = workdir / "sample.hwpx"
    target.write_bytes(sample.read_bytes())
    ops = HwpxOps(base_directory=workdir, auto_backup=True)
    return ops, target


def test_open_info_counts(ops_with_sample):
    ops, path = ops_with_sample
    info = ops.open_info(str(path))
    assert info["sectionCount"] >= 1
    assert info["paragraphCount"] >= 1
    assert info["meta"]["absolutePath"].endswith("sample.hwpx")


def test_picture_operations_preserve_a_safe_asset_graph(tmp_path):
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    target = workdir / "picture.hwpx"
    HwpxDocument.new().save_to_path(target)
    ops = HwpxOps(base_directory=workdir, auto_backup=True)

    inserted = ops.insert_picture(
        target.name,
        PNG_1X1_B64,
        image_format="png",
        width=11111,
        height=22222,
    )

    assert inserted["openSafety"]["ok"] is True
    assert inserted["idIntegrity"]["ok"] is True
    assert inserted["picture"]["binaryItemIDRef"] == "BIN0001"

    replaced = ops.replace_picture(
        target.name,
        PNG_1X1_ALT_B64,
        image_format="png",
    )

    assert replaced["openSafety"]["ok"] is True
    assert replaced["idIntegrity"]["ok"] is True
    assert replaced["replacement"]["old_binaryItemIDRef"] == "BIN0001"
    assert replaced["replacement"]["new_binaryItemIDRef"] == "BIN0002"


def test_read_text_pagination(ops_with_sample):
    ops, path = ops_with_sample
    result = ops.read_text(str(path), limit=2)
    assert "HWPX" in result["textChunk"]
    assert result["nextOffset"] >= 1


def test_get_paragraphs_returns_requested_indices(ops_with_sample):
    ops, path = ops_with_sample
    result = ops.get_paragraphs(str(path), paragraph_indexes=[1, 4, 9])
    paragraphs = result["paragraphs"]
    assert [item["paragraphIndex"] for item in paragraphs] == [1, 4, 9]
    assert "Hello HWPX!" in paragraphs[0]["text"]
    assert "Table below demonstrates cell editing." in paragraphs[1]["text"]
    assert paragraphs[2]["text"].strip() == "B2"
    assert len(paragraphs) == 3


def test_read_text_uses_default_limit(monkeypatch, tmp_path):
    class FakeParagraph:
        def __init__(self, index: int, content: str) -> None:
            self.index = index
            self._content = content

        def text(
            self,
            *,
            annotations=None,
            preserve_breaks: bool = False,
        ) -> str:
            return self._content

    paragraphs = [FakeParagraph(index, f"Paragraph {index}") for index in range(500)]

    class FakeExtractor:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_document_paragraphs(self):
            yield from paragraphs

    monkeypatch.setattr(read_query_module, "create_text_extractor", FakeExtractor)

    ops = HwpxOps(base_directory=tmp_path)
    dummy = tmp_path / "dummy.hwpx"
    dummy.write_bytes(b"")

    result = ops.read_text(dummy.name)
    lines = result["textChunk"].splitlines()
    assert len(lines) <= ops_module.DEFAULT_PAGING_PARAGRAPH_LIMIT
    assert result["nextOffset"] == ops_module.DEFAULT_PAGING_PARAGRAPH_LIMIT

    expanded_limit = ops_module.DEFAULT_PAGING_PARAGRAPH_LIMIT + 50
    expanded = ops.read_text(dummy.name, limit=expanded_limit)
    expanded_lines = expanded["textChunk"].splitlines()
    assert len(expanded_lines) == expanded_limit
    assert expanded["nextOffset"] == expanded_limit


def test_read_text_marks_pagination_complete_with_null_next_offset(ops_with_sample):
    ops, path = ops_with_sample
    result = ops.read_text(str(path), limit=10_000)

    assert result["textChunk"]
    assert result["nextOffset"] is None


def test_read_text_consumes_only_requested_slice(monkeypatch, tmp_path):
    class TrackingParagraph:
        def __init__(self, index: int) -> None:
            self.index = index
            self._content = f"Paragraph {index}"
            self.text_calls = 0

        def text(
            self,
            *,
            annotations=None,
            preserve_breaks: bool = False,
        ) -> str:
            self.text_calls += 1
            return self._content

    paragraphs = [TrackingParagraph(index) for index in range(10)]
    yielded_indexes: list[int] = []

    class FakeExtractor:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_document_paragraphs(self):
            for paragraph in paragraphs:
                yielded_indexes.append(paragraph.index)
                yield paragraph

    monkeypatch.setattr(read_query_module, "create_text_extractor", FakeExtractor)

    ops = HwpxOps(base_directory=tmp_path)
    dummy = tmp_path / "dummy.hwpx"
    dummy.write_bytes(b"")

    offset = 2
    limit = 2
    result = ops.read_text(dummy.name, offset=offset, limit=limit)

    assert result["textChunk"] == "Paragraph 2\nParagraph 3"
    assert result["nextOffset"] == offset + limit
    assert yielded_indexes == [0, 1, 2, 3, 4]

    for index, paragraph in enumerate(paragraphs):
        expected_calls = 1 if offset <= index < offset + limit else 0
        assert paragraph.text_calls == expected_calls

def test_resolve_path_permission_error_maps_code(tmp_path, monkeypatch):
    ops = HwpxOps(base_directory=tmp_path)

    def deny(path: str, *, must_exist: bool = True):
        raise PermissionError(path)

    monkeypatch.setattr(ops.storage, "resolve_path", deny)

    with pytest.raises(ops_module.HwpxOperationError) as exc_info:
        ops.open_info("secret.hwpx")

    assert exc_info.value.code == "PERMISSION_DENIED"
    assert exc_info.value.details == {"requestedName": "secret.hwpx"}

def test_find_returns_matches(ops_with_sample):
    ops, path = ops_with_sample
    matches = ops.find(str(path), "HWPX")
    assert matches["matches"]
    assert any("HWPX" in match["context"] for match in matches["matches"])


def test_find_truncates_context_and_respects_radius(monkeypatch, tmp_path):
    text = "A" * 200 + "needle" + "B" * 200

    class FakeParagraph:
        def __init__(self, index: int, content: str) -> None:
            self.index = index
            self._content = content

        def text(self) -> str:
            return self._content

    class FakeExtractor:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_document_paragraphs(self):
            yield FakeParagraph(0, text)

    monkeypatch.setattr(read_query_module, "create_text_extractor", FakeExtractor)

    ops = HwpxOps(base_directory=tmp_path)
    dummy = tmp_path / "dummy.hwpx"
    dummy.write_bytes(b"")

    default = ops.find(dummy.name, "needle")
    context = default["matches"][0]["context"]
    assert context.startswith("...")
    assert context.endswith("...")
    assert len(context) < len(text)
    assert "needle" in context

    expanded = ops.find(dummy.name, "needle", context_radius=500)
    expanded_context = expanded["matches"][0]["context"]
    assert expanded_context == text


def test_replace_text_in_runs_dry_run_does_not_modify(ops_with_sample):
    ops, path = ops_with_sample
    ops.replace_text_in_runs(str(path), "HWPX", "DOCX", dry_run=True)
    text = ops.read_text(str(path), limit=5)["textChunk"]
    assert "DOCX" not in text


def test_ensure_char_style_applies_shared_color_style_logic(ops_with_sample):
    ops, path = ops_with_sample
    document = HwpxDocument.open(path)

    char_id = ops._ensure_char_style(
        document,
        {"bold": True, "underline": True, "colorHex": "FF0000"},
    )

    assert char_id is not None
    style = document.styles.char_property(char_id)
    assert style is not None
    assert style.text_color() == "#FF0000"
    assert "bold" in style.child_attributes
    underline_attrs = style.child_attributes.get("underline") or {}
    assert underline_attrs.get("type") != "NONE"


def test_planning_flow_registers_document(ops_with_sample):
    ops, path = ops_with_sample
    operations = [
        {
            "target": {"sectionIndex": 0, "paraIndex": 1},
            "match": "Hello HWPX!",
            "replacement": "Hello HWPX!",
            "dryRun": True,
        }
    ]

    plan_result = ops.plan_edit(path=str(path), operations=operations)
    assert plan_result.get("ok") is True

    search_result = ops.search(path=str(path), pattern="HWPX")
    assert search_result["matches"], "Expected at least one search match"

    context_result = ops.get_context(
        path=str(path), target={"sectionIndex": 0, "paraIndex": 1}
    )
    assert context_result["focus"].startswith("Hello HWPX!")


def test_replace_text_in_runs_updates_file_and_backup(ops_with_sample):
    ops, path = ops_with_sample
    ops.replace_text_in_runs(str(path), "HWPX", "DOCX", dry_run=False)
    text = ops.read_text(str(path), limit=5)["textChunk"]
    assert "DOCX" in text
    backup = path.with_suffix(path.suffix + ".bak")
    assert backup.exists()


def test_save_as_creates_new_file(ops_with_sample, tmp_path):
    ops, path = ops_with_sample
    out = path.with_name("copy.hwpx")
    result = ops.save_as(str(path), str(out))
    assert Path(result["outPath"]).exists()
    assert Path(result["outPath"]) == out
    assert result["verificationReport"]["openSafety"]["ok"] is True

    source_text = ops.read_text(str(path), limit=5)["textChunk"]
    copied_text = ops.read_text(str(out), limit=5)["textChunk"]
    assert copied_text == source_text


def test_make_blank_returns_open_safety_verification(tmp_path):
    ops = HwpxOps(base_directory=tmp_path, auto_backup=False)

    result = ops.make_blank("blank.hwpx")

    assert Path(result["outPath"]).exists()
    assert result["verificationReport"]["openSafety"]["ok"] is True


def test_fill_template_replaces_multiple_tokens_without_modifying_source(ops_with_sample):
    ops, path = ops_with_sample
    out = path.with_name("filled.hwpx")

    result = ops.fill_template(
        str(path),
        str(out),
        {"HWPX": "DOCX", "sample": "example"},
    )

    assert result["replacedCount"] >= 2
    assert Path(result["outPath"]).exists()
    assert result["verificationReport"]["openSafety"]["ok"] is True

    source_text = ops.read_text(str(path), limit=5)["textChunk"]
    filled_text = ops.read_text(str(out), limit=5)["textChunk"]
    assert "HWPX" in source_text
    assert "DOCX" in filled_text
    assert "example DOCX" in filled_text

def test_add_table_returns_valid_index(ops_with_sample):
    ops, path = ops_with_sample
    result = ops.add_table(str(path), rows=2, cols=2)

    assert result["cellCount"] == 4
    index = result["tableIndex"]

    # ensure the table can be edited using the reported index
    update = ops.set_table_cell_text(
        str(path),
        table_index=index,
        row=0,
        col=0,
        text="이름",
    )

    assert update == {"ok": True}

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)
    target_table = refreshed_tables[index]
    assert target_table.cell(0, 0).text == "이름"

    basic_border_id = str(refreshed._root.ensure_basic_border_fill())
    assert target_table.element.get("borderFillIDRef") == basic_border_id


def test_add_table_border_style_none_uses_empty_border(ops_with_sample):
    ops, path = ops_with_sample
    result = ops.add_table(str(path), rows=2, cols=2, border_style="none")

    index = result["tableIndex"]

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)

    assert refreshed_tables[index].element.get("borderFillIDRef") == "0"


def test_add_table_custom_border_fill_reuses_definition(ops_with_sample):
    ops, path = ops_with_sample
    first = ops.add_table(
        str(path),
        rows=2,
        cols=2,
        border_color="#336699",
        border_width="0.45 mm",
        fill_color="#abc123",
    )

    document = HwpxDocument.open(path)
    tables: list = []
    for paragraph in document.paragraphs:
        tables.extend(paragraph.tables)
    first_table = tables[first["tableIndex"]]
    border_id = first_table.element.get("borderFillIDRef")

    assert border_id not in (None, "", "0")
    assert first_table.cell(0, 0).element.get("borderFillIDRef") == border_id

    header = document.parts.headers[0]
    ref_list = header.element.find(f"{HH_NS}refList")
    assert ref_list is not None
    border_fills = ref_list.find(f"{HH_NS}borderFills")
    assert border_fills is not None
    target = None
    for candidate in border_fills.findall(f"{HH_NS}borderFill"):
        if candidate.get("id") == border_id:
            target = candidate
            break
    assert target is not None

    left_border = target.find(f"{HH_NS}leftBorder")
    assert left_border is not None
    assert (left_border.get("color") or "").upper() == "#336699"
    assert left_border.get("type") == "SOLID"
    assert (left_border.get("width") or "").replace(" ", "").lower() == "0.45mm"

    fill_brush = target.find(f"{HH_NS}fillBrush")
    assert fill_brush is not None
    solid_brush = fill_brush.find(f"{HH_NS}solidBrush")
    assert solid_brush is not None
    assert (solid_brush.get("color") or "").upper() == "#ABC123"

    second = ops.add_table(
        str(path),
        rows=1,
        cols=1,
        border_color="#336699",
        border_width="0.45 mm",
        fill_color="#abc123",
    )

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)

    assert refreshed_tables[second["tableIndex"]].element.get("borderFillIDRef") == border_id


def test_set_table_cell_text_sanitizes_tab_character(ops_with_sample):
    ops, path = ops_with_sample

    result = ops.set_table_cell_text(
        str(path),
        table_index=0,
        row=0,
        col=0,
        text="hello\tworld",
    )

    assert result == {"ok": True}

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)
    assert refreshed_tables[0].cell(0, 0).text == "helloworld"


def test_set_table_cell_text_strips_cr_keeps_lf(ops_with_sample):
    ops, path = ops_with_sample

    result = ops.set_table_cell_text(
        str(path),
        table_index=0,
        row=0,
        col=0,
        text="line1\r\nline2",
    )

    assert result == {"ok": True}

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)
    assert refreshed_tables[0].cell(0, 0).text == "line1\nline2"


def test_set_table_cell_text_keeps_normal_text_unchanged(ops_with_sample):
    ops, path = ops_with_sample
    text = "plain text 123"

    result = ops.set_table_cell_text(
        str(path),
        table_index=0,
        row=0,
        col=0,
        text=text,
    )

    assert result == {"ok": True}

    refreshed = HwpxDocument.open(path)
    refreshed_tables: list = []
    for paragraph in refreshed.paragraphs:
        refreshed_tables.extend(paragraph.tables)
    assert refreshed_tables[0].cell(0, 0).text == text


def test_set_table_cell_text_logs_warning_when_sanitised(ops_with_sample, caplog):
    ops, path = ops_with_sample
    value = "bad\ttext"
    expected_message = "cell text contained illegal characters and was sanitised"

    with caplog.at_level(logging.WARNING, logger=ops_module.logger.name):
        ops.set_table_cell_text(
            str(path),
            table_index=0,
            row=0,
            col=0,
            text=value,
        )

    warning_records = [
        record
        for record in caplog.records
        if record.name == ops_module.logger.name
        and record.levelno == logging.WARNING
        and record.getMessage() == expected_message
    ]

    assert warning_records
    assert warning_records[0].original_len == len(value)
    assert warning_records[0].cleaned_len == len("badtext")


def test_set_table_cell_supports_logical_and_split_flags(ops_with_sample):
    ops, path = ops_with_sample
    table_info = ops.add_table(str(path), rows=3, cols=3)
    index = table_info["tableIndex"]

    document = HwpxDocument.open(path)
    tables = []
    for paragraph in document.paragraphs:
        tables.extend(paragraph.tables)
    tables[index].merge_cells(0, 0, 1, 1)
    document.save_to_path(path)

    logical_result = ops.set_table_cell_text(
        str(path),
        table_index=index,
        row=1,
        col=1,
        text="Merged anchor",
        logical=True,
    )

    assert logical_result == {"ok": True}

    merged_state = HwpxDocument.open(path)
    merged_tables: list = []
    for paragraph in merged_state.paragraphs:
        merged_tables.extend(paragraph.tables)
    merged_cell = merged_tables[index].cell(0, 0)
    assert merged_cell.span == (2, 2)
    assert merged_cell.text == "Merged anchor"

    split_result = ops.set_table_cell_text(
        str(path),
        table_index=index,
        row=1,
        col=1,
        text="Bottom-right",
        logical=True,
        split_merged=True,
    )

    assert split_result == {"ok": True}

    split_state = HwpxDocument.open(path)
    split_tables: list = []
    for paragraph in split_state.paragraphs:
        split_tables.extend(paragraph.tables)
    top_left = split_tables[index].cell(0, 0)
    bottom_right = split_tables[index].cell(1, 1)
    assert top_left.span == (1, 1)
    assert top_left.text == "Merged anchor"
    assert bottom_right.span == (1, 1)
    assert bottom_right.text == "Bottom-right"


def test_replace_region_and_split_tool_handle_merged_cells(ops_with_sample):
    ops, path = ops_with_sample
    table_info = ops.add_table(str(path), rows=3, cols=3)
    index = table_info["tableIndex"]

    document = HwpxDocument.open(path)
    tables = []
    for paragraph in document.paragraphs:
        tables.extend(paragraph.tables)
    target_table = tables[index]
    target_table.merge_cells(0, 0, 1, 1)
    document.save_to_path(path)

    region_result = ops.replace_table_region(
        str(path),
        table_index=index,
        start_row=0,
        start_col=0,
        values=[["A", "B"], ["C", "D"]],
        logical=True,
        split_merged=True,
    )

    assert region_result["updatedCells"] == 4

    updated_state = HwpxDocument.open(path)
    updated_tables: list = []
    for paragraph in updated_state.paragraphs:
        updated_tables.extend(paragraph.tables)
    updated_table = updated_tables[index]
    assert updated_table.cell(0, 0).span == (1, 1)
    assert updated_table.cell(0, 0).text == "A"
    assert updated_table.cell(0, 1).text == "B"
    assert updated_table.cell(1, 0).text == "C"
    assert updated_table.cell(1, 1).text == "D"

    # Merge a new column region and split it using the dedicated tool
    updated_table.merge_cells(0, 2, 1, 2)
    updated_state.save_to_path(path)

    split_meta = ops.split_table_cell(str(path), table_index=index, row=0, col=2)

    assert split_meta == {"startRow": 0, "startCol": 2, "rowSpan": 2, "colSpan": 1}

    split_state = HwpxDocument.open(path)
    split_tables: list = []
    for paragraph in split_state.paragraphs:
        split_tables.extend(paragraph.tables)
    column_cell = split_tables[index].cell(0, 2)
    assert column_cell.span == (1, 1)


def test_get_table_cell_map_serializes_grid_with_merges(ops_with_sample):
    ops, path = ops_with_sample
    # the last column keeps a cell in every row, so no row is left without a cell of its own
    # (a merge that leaves one folds it, as Hancom's does)
    table_info = ops.add_table(str(path), rows=3, cols=4)
    index = table_info["tableIndex"]

    document = HwpxDocument.open(path)
    tables: list = []
    for paragraph in document.paragraphs:
        tables.extend(paragraph.tables)
    target_table = tables[index]
    for row in range(3):
        for col in range(4):
            target_table.cell(row, col).text = f"R{row}C{col}"
    target_table.merge_cells(0, 0, 1, 1)
    target_table.merge_cells(0, 2, 2, 2)
    document.save_to_path(path)

    grid_info = ops.get_table_cell_map(str(path), table_index=index)
    grid = grid_info["grid"]

    assert grid_info["rowCount"] == 3
    assert grid_info["columnCount"] == 4
    assert all(len(row) == 4 for row in grid)

    coords = {(cell["row"], cell["column"]) for row in grid for cell in row}
    assert coords == {(r, c) for r in range(3) for c in range(4)}

    top_left = grid[0][0]
    assert {key: value for key, value in top_left.items() if key != "text"} == {
        "row": 0,
        "column": 0,
        "anchor": {"row": 0, "column": 0},
        "rowSpan": 2,
        "colSpan": 2,
    }
    # the merged cell starts with its own text (python-hwpx may also keep the covered cells' text)
    assert top_left["text"].startswith("R0C0")

    overlapped = grid[1][1]
    assert overlapped["anchor"] == {"row": 0, "column": 0}
    assert overlapped["rowSpan"] == 2
    assert overlapped["colSpan"] == 2
    assert overlapped["text"] == top_left["text"]

    vertical_anchor = grid[0][2]
    assert vertical_anchor["anchor"] == {"row": 0, "column": 2}
    assert vertical_anchor["rowSpan"] == 3
    assert vertical_anchor["colSpan"] == 1
    assert vertical_anchor["text"].startswith("R0C2")

    bottom_left = grid[2][0]
    assert bottom_left["anchor"] == {"row": 2, "column": 0}
    assert bottom_left["rowSpan"] == 1
    assert bottom_left["colSpan"] == 1
    assert bottom_left["text"] == "R2C0"


def test_set_table_border_fill_updates_anchor_cells(ops_with_sample):
    ops, path = ops_with_sample
    table_info = ops.add_table(str(path), rows=3, cols=3)
    index = table_info["tableIndex"]

    result = ops.set_table_border_fill(
        str(path),
        table_index=index,
        border_style="none",
        fill_color="#112233",
    )

    assert result["borderFillIDRef"] != "0"
    assert result["anchorCells"] == 9

    document = HwpxDocument.open(path)
    tables: list = []
    for paragraph in document.paragraphs:
        tables.extend(paragraph.tables)
    target_table = tables[index]

    assert target_table.element.get("borderFillIDRef") == result["borderFillIDRef"]

    anchor_elements: dict[tuple[int, int], Any] = {}
    for position in target_table.iter_grid():
        if position.is_anchor:
            anchor_elements[position.anchor] = position.cell.element
            assert (
                position.cell.element.get("borderFillIDRef")
                == result["borderFillIDRef"]
            )

    assert len(anchor_elements) == result["anchorCells"]
    header = document.parts.headers[0]
    ref_list = header.element.find(f"{HH_NS}refList")
    assert ref_list is not None
    border_fills = ref_list.find(f"{HH_NS}borderFills")
    assert border_fills is not None
    target = None
    for candidate in border_fills.findall(f"{HH_NS}borderFill"):
        if candidate.get("id") == result["borderFillIDRef"]:
            target = candidate
            break
    assert target is not None

    left_border = target.find(f"{HH_NS}leftBorder")
    assert left_border is not None
    assert left_border.get("type") == "NONE"

    fill_brush = target.find(f"{HH_NS}fillBrush")
    assert fill_brush is not None
    solid_brush = fill_brush.find(f"{HH_NS}solidBrush")
    assert solid_brush is not None
    assert (solid_brush.get("color") or "").upper() == "#112233"


def test_set_table_cell_text_auto_fit_adjusts_widths(ops_with_sample):
    ops, path = ops_with_sample
    table_info = ops.add_table(str(path), rows=1, cols=2)
    index = table_info["tableIndex"]

    ops.set_table_cell_text(
        str(path),
        table_index=index,
        row=0,
        col=0,
        text="짧음",
        auto_fit=True,
    )
    ops.set_table_cell_text(
        str(path),
        table_index=index,
        row=0,
        col=1,
        text="이 셀은 훨씬 더 긴 설명을 포함합니다",
        auto_fit=True,
    )

    refreshed = HwpxDocument.open(path)
    tables: list = []
    for paragraph in refreshed.paragraphs:
        tables.extend(paragraph.tables)
    table = tables[index]

    left_width = int(table.cell(0, 0).element.find(f"{HP_NS}cellSz").get("width"))
    right_width = int(table.cell(0, 1).element.find(f"{HP_NS}cellSz").get("width"))

    assert right_width > left_width

    size_element = table.element.find(f"{HP_NS}sz")
    assert size_element is not None
    assert int(size_element.get("width")) == left_width + right_width


def test_replace_table_region_auto_fit_scales_each_column(ops_with_sample):
    ops, path = ops_with_sample
    table_info = ops.add_table(str(path), rows=1, cols=3)
    index = table_info["tableIndex"]

    ops.replace_table_region(
        str(path),
        table_index=index,
        start_row=0,
        start_col=0,
        values=[["짧", "중간길이", "이 열은 아주 길고 자세한 설명을 담고 있습니다"]],
        auto_fit=True,
    )

    refreshed = HwpxDocument.open(path)
    tables: list = []
    for paragraph in refreshed.paragraphs:
        tables.extend(paragraph.tables)
    table = tables[index]

    widths = [
        int(table.cell(0, col).element.find(f"{HP_NS}cellSz").get("width"))
        for col in range(table.column_count)
    ]

    assert widths[2] > widths[1] > widths[0]

def test_hwp_open_info_returns_read_only_metadata(monkeypatch, tmp_path):
    # A core that cannot open .hwp leaves only the preview-text reader.
    monkeypatch.setattr(context_module, "native_hwp5_supported", lambda: False)
    ops = HwpxOps(base_directory=tmp_path)
    hwp_path = tmp_path / "sample.hwp"
    hwp_path.write_bytes(b"fake")

    monkeypatch.setattr(
        ops._services.context,
        "_read_only_hwp_paragraphs",
        lambda path: (["첫 문단", "둘째 문단"], hwp_path, "PrvText"),
    )

    info = ops.open_info(hwp_path.name)

    assert info["paragraphCount"] == 2
    assert info["meta"]["format"] == "hwp"
    assert info["meta"]["readOnly"] is True
    assert info["meta"]["extractionSource"] == "PrvText"


def test_hwp_read_text_and_find_use_read_only_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(context_module, "native_hwp5_supported", lambda: False)
    ops = HwpxOps(base_directory=tmp_path)
    hwp_path = tmp_path / "sample.hwp"
    hwp_path.write_bytes(b"fake")

    monkeypatch.setattr(
        ops._services.context,
        "_read_only_hwp_paragraphs",
        lambda path: (["학교 안내문", "2026년 행사 공지", "문의처"], hwp_path, "PrvText"),
    )

    page = ops.read_text(hwp_path.name, offset=1, limit=1)
    assert page["textChunk"] == "2026년 행사 공지"
    assert page["nextOffset"] == 2

    found = ops.find(hwp_path.name, "2026")
    assert found["matches"][0]["paragraphIndex"] == 1


def test_hwp_edit_tools_raise_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(context_module, "native_hwp5_supported", lambda: False)
    ops = HwpxOps(base_directory=tmp_path)
    hwp_path = tmp_path / "sample.hwp"
    hwp_path.write_bytes(b"fake")

    with pytest.raises(Exception) as exc_info:
        ops.replace_text_in_runs(hwp_path.name, "A", "B")

    assert exc_info.value.code == "READ_ONLY_HWP_DOCUMENT"
    # The refusal must not name a tool the server does not expose.
    assert "convert_hwp_to_hwpx" not in str(exc_info.value)


def test_analyze_template_structure_returns_regions_and_placeholders(ops_with_sample):
    ops, path = ops_with_sample

    result = ops.analyze_template_structure(
        str(path),
        placeholder_patterns=[r"HWPX"],
        lock_keywords=["sample"],
    )

    assert result["summary"]["paragraphCount"] >= 1
    assert len(result["regions"]) == 3
    assert any(item["name"] == "body" for item in result["regions"])
    assert result["placeholders"]
    assert result["placeholders"][0]["token"] == "HWPX"


def test_handle_registry_lifecycle(ops_with_sample):
    ops, path = ops_with_sample
    opened = ops.open_document_handle(str(path))
    handle = opened["handle"]

    listed = ops.list_open_documents()
    assert listed["documents"]
    assert listed["sessionPolicy"]["registryScope"] == "process"
    assert any(item["handleId"] == handle["handleId"] for item in listed["documents"])

    closed = ops.close_document_handle(handle["handleId"])
    assert closed == {"closed": True}


def test_copy_table_between_documents_with_handles(ops_with_sample):
    ops, source_path = ops_with_sample
    target_path = source_path.with_name("target.hwpx")
    target_path.write_bytes(source_path.read_bytes())

    source_handle = ops.open_document_handle(str(source_path))["handle"]["handleId"]
    target_handle = ops.open_document_handle(str(target_path))["handle"]["handleId"]

    source_path_from_handle = ops.resolve_document_path(handle_id=source_handle)
    target_path_from_handle = ops.resolve_document_path(handle_id=target_handle)

    source_document = HwpxDocument.open(ops.storage.resolve_path(source_path_from_handle))
    source_tables_before: list = []
    for paragraph in source_document.paragraphs:
        source_tables_before.extend(paragraph.tables)

    target_document_before = HwpxDocument.open(ops.storage.resolve_path(target_path_from_handle))
    target_tables_before: list = []
    for paragraph in target_document_before.paragraphs:
        target_tables_before.extend(paragraph.tables)
    result = ops.copy_table_between_documents(
        source_path=source_path_from_handle,
        source_table_index=0,
        target_path=target_path_from_handle,
    )

    assert result["copiedCells"] >= 1
    assert result["rowCount"] >= 1
    assert result["columnCount"] >= 1

    target_document_after = HwpxDocument.open(ops.storage.resolve_path(target_path_from_handle))
    target_tables_after: list = []
    for paragraph in target_document_after.paragraphs:
        target_tables_after.extend(paragraph.tables)

    assert len(source_tables_before) >= 1
    assert len(target_tables_after) == len(target_tables_before) + 1


def test_read_text_supports_a_registered_handle_path(ops_with_sample):
    ops, path = ops_with_sample
    handle_id = ops.open_document_handle(str(path))["handle"]["handleId"]
    registered_path = ops.resolve_document_path(handle_id=handle_id)
    result = ops.read_text(registered_path, limit=2)

    assert result["textChunk"]


def test_get_tables_by_handle_reports_logical_column_count(tmp_path):
    """S-082 regression: HwpxOxmlTable has column_count, not .columns — the old
    code crashed on any handle-registered document that contains a table."""

    workdir = tmp_path / "workspace"
    workdir.mkdir()
    target = workdir / "tables-handle.hwpx"
    document = HwpxDocument.new()
    document.add_table(rows=2, cols=3)
    document.save_to_path(target)

    ops = HwpxOps(base_directory=workdir, auto_backup=False)
    handle = ops._register_handle(
        "tables-handle.hwpx", ops._services.context._resolve_path("tables-handle.hwpx")
    )
    result = ops.get_tables_by_handle(handle.handle_id)
    assert result["tables"], "expected at least one table entry"
    entry = result["tables"][0]
    assert entry["rowCount"] == 2
    assert entry["columnCount"] == 3
