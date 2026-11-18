from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from hwpx_automation.core.document import open_doc, save_doc
from hwpx_automation.server import (
    add_memo_by_anchor,
    batch_replace,
    create_document,
    find_text,
    get_document_text,
    get_paragraph_text,
    search_and_replace,
)


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    target = tmp_path / "sample.hwpx"
    create_document(str(target))
    return target


def _append_paragraph(path: Path, text: str) -> None:
    doc = open_doc(str(path))
    doc.add_paragraph(text)
    save_doc(doc, str(path))


def _set_split_runs(path: Path, paragraph_index: int, chunks: list[str]) -> None:
    doc = open_doc(str(path))
    paragraph = doc.paragraphs[paragraph_index]
    for run in list(paragraph.runs):
        run.remove()
    for index, chunk in enumerate(chunks):
        paragraph.add_run(chunk, bold=(index == 0), italic=(index == 1))
    save_doc(doc, str(path))


def _linesegarray_count(element: ET.Element) -> int:
    return sum(
        1
        for child in element
        if child.tag.rsplit("}", 1)[-1].lower() == "linesegarray"
    )


def test_search_and_replace_basic(sample_file: Path):
    _append_paragraph(sample_file, "2025학년도 운영계획")

    result = search_and_replace(str(sample_file), "2025", "2026")
    text_result = get_document_text(str(sample_file))

    assert "2026학년도" in text_result["text"]
    assert result["replaced_count"] == 1
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["filePath"] == str(sample_file)


def test_batch_replace_order(sample_file: Path):
    _append_paragraph(sample_file, "2025. 3. 1. ~ 2026. 2. 28.")

    result = batch_replace(
        str(sample_file),
        [
            {"find": "2026", "replace": "2027"},
            {"find": "2025", "replace": "2026"},
        ],
    )
    text_result = get_document_text(str(sample_file))

    assert "2026. 3. 1. ~ 2027. 2. 28." in text_result["text"]
    assert result["total_replaced"] == 2
    assert result["openSafety"]["ok"] is True
    assert result["verificationReport"]["filePath"] == str(sample_file)


def test_search_and_replace_in_table(sample_file: Path):
    doc = open_doc(str(sample_file))
    table = doc.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "표 안의 2025 데이터"
    save_doc(doc, str(sample_file))

    result = search_and_replace(str(sample_file), "2025", "2026")
    text_result = get_document_text(str(sample_file))

    assert result["replaced_count"] == 1
    assert "표 안의 2026 데이터" in text_result["text"]


def test_search_and_replace_cross_run_in_paragraph(sample_file: Path):
    _append_paragraph(sample_file, "")
    _set_split_runs(sample_file, 1, ["20", "26학년도 운영"])
    doc = open_doc(str(sample_file))
    paragraph = doc.paragraphs[1]
    ET.SubElement(paragraph.element, "{http://www.hancom.co.kr/hwpml/2011/paragraph}lineSegArray")
    save_doc(doc, str(sample_file))

    result = search_and_replace(str(sample_file), "2026", "2027")
    find_result = find_text(str(sample_file), "2026")
    doc = open_doc(str(sample_file))
    paragraph = doc.paragraphs[1]

    assert result["replaced_count"] == 1
    assert find_result["total_matches"] == 0
    # Each new character takes the run of the old one at its place, as Hancom's 찾아 바꾸기 writes.
    assert [(run.text, run.bold, run.italic) for run in paragraph.runs if run.text] == [
        ("20", True, False),
        ("27학년도 운영", False, True),
    ]
    assert _linesegarray_count(paragraph.element) == 0


def test_cross_run_replace_keeps_the_runs_of_every_match(sample_file: Path):
    _append_paragraph(sample_file, "")
    _set_split_runs(sample_file, 1, ["가나", "다	라 가나다"])

    result = search_and_replace(str(sample_file), "가나다", "마바")
    paragraph = open_doc(str(sample_file)).paragraphs[1]

    assert result["replaced_count"] == 2
    assert paragraph.text == "마바	라 마바"
    assert [(run.text, run.bold) for run in paragraph.runs if run.text] == [("마바", True), ("	라 마바", False)]


def test_cross_run_match_with_a_tab_inside_is_left_whole(sample_file: Path):
    _append_paragraph(sample_file, "")
    _set_split_runs(sample_file, 1, ["가나", "다	라"])

    result = search_and_replace(str(sample_file), "나다	라", "X")
    paragraph = open_doc(str(sample_file)).paragraphs[1]

    assert result["replaced_count"] == 0
    assert paragraph.text == "가나다	라"
    assert [(run.text, run.bold) for run in paragraph.runs if run.text] == [("가나", True), ("다	라", False)]


def test_search_and_replace_cross_run_in_table_cell(sample_file: Path):
    doc = open_doc(str(sample_file))
    table = doc.add_table(rows=1, cols=1)
    cell = table.rows[0].cells[0]
    cell.text = "2026 데이터"

    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    para_element = cell.element.find(f".//{hp}p")
    assert para_element is not None
    run_elements = list(para_element.findall(f"{hp}run"))
    assert run_elements
    first_run = run_elements[0]
    for run_element in run_elements[1:]:
        para_element.remove(run_element)

    text_node = first_run.find(f"{hp}t")
    if text_node is None:
        text_node = ET.SubElement(first_run, f"{hp}t")
    text_node.text = "20"

    maker = getattr(para_element, "makeelement", None)
    if callable(maker):
        second_run = maker(f"{hp}run", {"charPrIDRef": "0"})
        second_text = second_run.makeelement(f"{hp}t", {})
        second_text.text = "26 데이터"
        second_run.append(second_text)
    else:
        second_run = ET.Element(f"{hp}run", {"charPrIDRef": "0"})
        ET.SubElement(second_run, f"{hp}t").text = "26 데이터"
    para_element.append(second_run)
    save_doc(doc, str(sample_file))

    result = search_and_replace(str(sample_file), "2026", "2027")
    table_result = get_document_text(str(sample_file))

    assert result["replaced_count"] == 1
    assert "2027 데이터" in table_result["text"]
    assert "2026 데이터" not in table_result["text"]


def test_cross_run_replace_in_table_cell_keeps_the_runs(sample_file: Path):
    doc = open_doc(str(sample_file))
    cell = doc.add_table(rows=1, cols=1).rows[0].cells[0]
    cell.text = ""
    paragraph = cell.paragraphs[0]
    for run in list(paragraph.runs):
        run.remove()
    paragraph.add_run("20", bold=True)
    paragraph.add_run("26 데이터", italic=True)
    save_doc(doc, str(sample_file))

    result = search_and_replace(str(sample_file), "2026", "2027")
    cell_paragraph = open_doc(str(sample_file)).paragraphs[1].tables[0].rows[0].cells[0].paragraphs[0]

    assert result["replaced_count"] == 1
    assert [(run.text, run.bold, run.italic) for run in cell_paragraph.runs if run.text] == [
        ("20", True, False),
        ("27 데이터", False, True),
    ]


def test_replace_in_paragraph_across_runs_keeps_the_runs(sample_file: Path):
    from hwpx_automation.server import replace_in_paragraph

    _append_paragraph(sample_file, "")
    _set_split_runs(sample_file, 1, ["홍길", "동 귀하"])

    result = replace_in_paragraph(str(sample_file), "홍길동", "김철수", paragraph_index=1)
    paragraph = open_doc(str(sample_file)).paragraphs[1]

    assert result["replaced_count"] == 1
    assert [(run.text, run.bold, run.italic) for run in paragraph.runs if run.text] == [
        ("김철", True, False),
        ("수 귀하", False, True),
    ]


def test_get_document_text_truncation(sample_file: Path):
    _append_paragraph(sample_file, "가" * 200)

    result = get_document_text(str(sample_file), max_chars=30)

    assert result["truncated"] is True
    assert len(result["text"]) == 30


def test_create_document(tmp_path: Path):
    target = tmp_path / "new.hwpx"
    result = create_document(str(target))

    assert result["created"] is True
    assert result["openSafety"]["ok"] is True
    assert result["verification"]["openSafety"]["ok"] is True
    assert open_doc(str(target)) is not None


def test_find_text(sample_file: Path):
    _append_paragraph(sample_file, "검색 대상 문장입니다")

    result = find_text(str(sample_file), "대상")

    assert result["total_matches"] >= 1
    first = result["matches"][0]
    assert "paragraph_index" in first
    assert "context" in first
    assert first["location"] == {"kind": "body_paragraph", "paragraph_index": first["paragraph_index"]}
    assert first["anchor"]["location"] == first["location"]


def test_find_text_returns_table_cell_location_and_anchor(sample_file: Path):
    doc = open_doc(str(sample_file))
    table = doc.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "표 안 코드 TARGET"
    save_doc(doc, str(sample_file))

    result = find_text(str(sample_file), "TARGET")
    match = result["matches"][0]
    memo_result = add_memo_by_anchor(str(sample_file), match["anchor"], "표 셀 메모")
    text_result = get_paragraph_text(str(sample_file), location=match["location"])

    assert result["total_matches"] == 1
    assert match["location"] == {
        "kind": "table_cell_paragraph",
        "table_index": 0,
        "row": 0,
        "col": 0,
        "cell_paragraph_index": 0,
    }
    assert match["anchor"]["anchor_id"] == "table:0:0:0:0@7"
    assert memo_result["location"] == match["location"]
    assert text_result["text"] == "표 안 코드 TARGET"
    assert len(open_doc(str(sample_file)).notes.memos) == 1


def test_search_and_replace_rejects_empty_find(sample_file: Path):
    _append_paragraph(sample_file, "abc")

    with pytest.raises(ValueError):
        search_and_replace(str(sample_file), "", "X")


def test_batch_replace_rejects_empty_find(sample_file: Path):
    _append_paragraph(sample_file, "abc")

    with pytest.raises(ValueError):
        batch_replace(str(sample_file), [{"find": "", "replace": "X"}])


def test_get_document_text_uses_env_default_limit(sample_file: Path, monkeypatch: pytest.MonkeyPatch):
    _append_paragraph(sample_file, "가" * 300)
    monkeypatch.setenv("HWPX_MCP_MAX_CHARS", "40")

    result = get_document_text(str(sample_file))

    assert result["truncated"] is True
    assert len(result["text"]) == 40


def test_search_and_replace_does_not_replace_its_own_output(sample_file: Path):
    # replace_text contains find_text: each occurrence is replaced once (#164).
    _append_paragraph(sample_file, "성명 홍길동, 보호자 홍길동")

    result = search_and_replace(str(sample_file), "홍길동", "홍길동(인)")
    text = get_document_text(str(sample_file))["text"]

    assert result["replaced_count"] == 2
    assert "성명 홍길동(인), 보호자 홍길동(인)" in text
    assert "(인)(인)" not in text


def test_cross_run_replace_does_not_replace_its_own_output(sample_file: Path):
    _append_paragraph(sample_file, "")
    _set_split_runs(sample_file, 1, ["홍", "길동 귀하"])

    result = search_and_replace(str(sample_file), "홍길동", "홍길동(인)")
    doc = open_doc(str(sample_file))

    assert result["replaced_count"] == 1
    assert doc.paragraphs[1].text == "홍길동(인) 귀하"
