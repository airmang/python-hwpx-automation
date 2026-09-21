import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.server import (
    add_paragraph,
    add_table,
    copy_document,
    create_custom_style,
    create_document,
    format_text,
    list_styles,
    merge_table_cells,
)

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _inject_stale_lineseg(path: Path) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path, "r") as source:
        with zipfile.ZipFile(tmp_path, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "Contents/section0.xml":
                    root = ET.fromstring(data)
                    paragraph = None
                    for candidate in root.findall(f".//{{{_HP_NS}}}p"):
                        text_nodes = candidate.findall(f".//{{{_HP_NS}}}t")
                        has_visible_text = any((node.text or "") for node in text_nodes)
                        if has_visible_text and all(
                            child.tag.rsplit("}", 1)[-1].lower() == "run" for child in candidate
                        ):
                            paragraph = candidate
                            break
                    assert paragraph is not None
                    lineseg_array = ET.SubElement(paragraph, f"{{{_HP_NS}}}linesegarray")
                    ET.SubElement(lineseg_array, f"{{{_HP_NS}}}lineseg", {"textpos": "999"})
                    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(info, data)
    path.write_bytes(tmp_path.read_bytes())
    tmp_path.unlink()


def test_format_text_persists_run_level_style_changes(tmp_path: Path):
    target = tmp_path / "format_text.hwpx"
    create_document(str(target))
    add_paragraph(str(target), "Hello World")

    result = format_text(
        str(target),
        paragraph_index=1,
        start_pos=6,
        end_pos=11,
        bold=True,
        color="FF0000",
        font_size=14,
    )

    assert result["formatted"] is True

    doc = open_doc(str(target))
    paragraph = doc.paragraphs[1]
    runs = list(paragraph.runs)

    assert [run.text for run in runs] == ["Hello ", "World"]
    assert runs[0].char_pr_id_ref != runs[1].char_pr_id_ref

    plain_style = runs[0].style
    accent_style = runs[1].style
    assert plain_style is not None
    assert accent_style is not None
    assert plain_style.text_color() == "#000000"
    assert accent_style.text_color() == "#FF0000"
    assert "bold" not in plain_style.child_attributes
    assert "bold" in accent_style.child_attributes
    assert accent_style.attributes.get("height") == "1400"


def test_format_text_colored_underline_uses_position_type(tmp_path: Path):
    target = tmp_path / "underline.hwpx"
    create_document(str(target))
    add_paragraph(str(target), "Hello World")
    format_text(str(target), 1, 6, 11, underline=True, color="0000FF")

    with zipfile.ZipFile(target) as package:
        header = ET.fromstring(package.read("Contents/header.xml"))
        section = ET.fromstring(package.read("Contents/section0.xml"))
    runs = section.findall(f".//{{{_HP_NS}}}p")[1].findall(f"{{{_HP_NS}}}run")
    assert ["".join(run.itertext()) for run in runs] == ["Hello ", "World"]
    char_id = runs[1].get("charPrIDRef")
    hh_ns = "http://www.hancom.co.kr/hwpml/2011/head"
    char_pr = next(
        node for node in header.iter(f"{{{hh_ns}}}charPr") if node.get("id") == char_id
    )
    underline = char_pr.find(f"{{{hh_ns}}}underline")
    assert underline is not None
    assert underline.attrib == {"type": "BOTTOM", "shape": "SOLID", "color": "#0000FF"}


def test_create_custom_style_creates_distinct_style_and_name_resolves_on_insert(tmp_path: Path):
    target = tmp_path / "custom_style.hwpx"
    create_document(str(target))

    before = list_styles(str(target))["styles"]
    body_style = next(style for style in before if style.get("name") in {"본문", "Body"})

    created = create_custom_style(
        str(target),
        "AccentStyle",
        bold=True,
        color="FF0000",
        font_size=14,
    )
    add_paragraph(str(target), "Styled paragraph", style="AccentStyle")

    after = list_styles(str(target))["styles"]
    assert len(after) == len(before) + 1
    assert created["created"] is True
    assert created["style_name"] == "AccentStyle"
    assert created["style_id"] != body_style["id"]
    assert created["char_pr_id_ref"] != body_style["char_pr_id_ref"]

    doc = open_doc(str(target))
    paragraph = doc.paragraphs[-1]
    assert paragraph.style_id_ref == created["style_id"]

    style = doc.styles.get(paragraph.style_id_ref)
    assert style is not None
    assert style.name == "AccentStyle"
    assert str(style.char_pr_id_ref) == created["char_pr_id_ref"]

    char_style = doc.styles.char_property(style.char_pr_id_ref)
    assert char_style is not None
    assert char_style.text_color() == "#FF0000"
    assert "bold" in char_style.child_attributes
    assert char_style.attributes.get("height") == "1400"


def test_create_custom_style_reuses_existing_name(tmp_path: Path):
    target = tmp_path / "style_reuse.hwpx"
    create_document(str(target))

    first = create_custom_style(str(target), "AccentStyle", bold=True)
    second = create_custom_style(str(target), "AccentStyle", bold=True)

    styles = list_styles(str(target))["styles"]
    assert len([style for style in styles if style.get("name") == "AccentStyle"]) == 1
    assert first["style_id"] == second["style_id"]
    assert second["created"] is False


def test_save_doc_uses_atomic_write_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "atomic.hwpx"
    create_document(str(target))
    add_paragraph(str(target), "original")
    original_bytes = target.read_bytes()

    doc = open_doc(str(target))
    doc.add_paragraph("updated")

    def flaky_save(path: str | Path | None = None, *args: object, **kwargs: object):
        if path is not None:
            Path(path).write_text("not-a-valid-hwpx", encoding="utf-8")
        raise RuntimeError("forced save failure")

    # Phase F routes saves through the SavePipeline (save_report), so inject the
    # failure there to exercise the storage's atomic-write-on-failure path.
    monkeypatch.setattr(doc, "save_report", flaky_save)

    with pytest.raises(RuntimeError, match="forced save failure"):
        save_doc(doc, str(target))

    assert target.read_bytes() == original_bytes
    assert target.with_suffix(".hwpx.bak").exists()
    assert [path.name for path in tmp_path.glob("*.hwpx")] == ["atomic.hwpx"]


def test_list_styles(tmp_path: Path):
    target = tmp_path / "list_styles.hwpx"
    create_document(str(target))

    result = list_styles(str(target))

    assert result["count"] > 0
    assert len(result["styles"]) == result["count"]
    sample = result["styles"][0]
    assert set(sample) >= {
        "id",
        "name",
        "eng_name",
        "type",
        "para_pr_id_ref",
        "char_pr_id_ref",
    }
    assert any(style.get("char_pr_id_ref") for style in result["styles"])


def test_merge_table_cells(tmp_path: Path):
    target = tmp_path / "merge_table.hwpx"
    create_document(str(target))
    add_table(str(target), 2, 2, [["A", "B"], ["C", "D"]])

    merge_table_cells(str(target), 0, 0, 0, 1, 1)

    doc = open_doc(str(target))
    cell = doc.paragraphs[-1].tables[0].rows[0].cells[0]
    span = cell.element.find("{http://www.hancom.co.kr/hwpml/2011/paragraph}cellSpan")
    assert span is not None
    assert span.get("rowSpan") == "2"
    assert span.get("colSpan") == "2"


def test_copy_document(tmp_path: Path):
    source = tmp_path / "source.hwpx"
    create_document(str(source))
    add_paragraph(str(source), "copy me")

    copied = copy_document(str(source))
    copied_path = tmp_path / copied["destination"]

    assert copied_path.exists()
    assert copied["openSafety"]["ok"] is True
    assert open_doc(str(source)) is not None
    assert open_doc(str(copied_path)) is not None


def test_copy_document_rejects_unsafe_hwpx_and_preserves_destination(tmp_path: Path):
    source = tmp_path / "source.hwpx"
    destination = tmp_path / "destination.hwpx"
    create_document(str(source))
    add_paragraph(str(source), "short")
    create_document(str(destination))
    destination_before = destination.read_bytes()
    _inject_stale_lineseg(source)

    with pytest.raises(ValueError, match="open-safety"):
        copy_document(str(source), str(destination))

    assert destination.read_bytes() == destination_before
