from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument

from hwpx_automation.office.authoring.design import Profile, ProfileRequiredError, compose_bytes
from hwpx_automation.office.authoring.design.marked import (
    MarkedTemplateError,
    harvest_marked_profile,
)

BAND_FILL = "#3E57A5"


def _template(path: Path, *, extra=None) -> Path:
    """A report template: band table, □/ㅇ levels, spacer lines between them."""

    doc = HwpxDocument.new()  # its first, empty paragraph carries the page setup
    band = doc.add_table(1, 3)
    band.cell(0, 0).text = "{{띠.번호}}"
    band.cell(0, 2).text = "{{띠.제목}}"
    band.set_cell_shading(0, 0, BAND_FILL)
    doc.add_paragraph("")
    doc.add_paragraph("□ {{1단계}}")
    doc.add_paragraph("")
    doc.add_paragraph(" ㅇ {{2단계}}")
    doc.add_paragraph("이 줄은 자리표시가 없는 고정 문장")
    if extra is not None:
        extra(doc)
    doc.save_to_path(path)
    doc.close()
    return path


def _section_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("Contents/section0.xml").decode("utf-8")


def _harvest(tmp_path: Path, **kwargs) -> tuple[dict, Profile]:
    manifest = harvest_marked_profile(_template(tmp_path / "t.hwpx", **kwargs), "report", tmp_path / "p")
    return manifest, Profile.load(tmp_path / "p" / "report")


def _plan(*blocks: dict) -> dict:
    return {"profile": "report", "blocks": list(blocks)}


def test_harvest_names_roles_and_slots_from_placeholders(tmp_path: Path) -> None:
    manifest, profile = _harvest(tmp_path)

    assert manifest["kind"] == "marked"
    assert manifest["slots"] == {"띠": ["번호", "제목"], "1단계": [""], "2단계": [""]}
    assert manifest["ignored_static_paragraphs"] == 1
    assert manifest["skeleton_open_safe"] is True
    assert sorted(profile.roles) == ["1단계", "2단계", "띠"]
    # The blank line above each role travels with it (spacing is cloned too).
    for role in profile.roles:
        assert len(profile.fragment(role)) == 2
    # The page setup on the template's first paragraph is not part of a role.
    band = profile.fragment("띠")
    assert not [e for e in band.iter() if str(e.tag).endswith("}secPr")]


def test_compose_clones_roles_fills_slots_and_keeps_band_fill(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)
    plan = _plan(
        {"role": "띠", "values": {"번호": "Ⅰ", "제목": "추진 배경"}},
        {"role": "1단계", "text": "추진 근거"},
        {"role": "2단계", "text": "학교교육계획"},
        {"role": "띠", "values": {"번호": "Ⅱ", "제목": "세부 계획"}},
        {"role": "1단계", "text": "교원 연수"},
    )

    data, result = compose_bytes(plan, profile=profile)

    assert result.ok, result.errors
    assert result.style_coverage.ok
    section = _section_xml(data)
    assert "{{" not in section
    for text in ("Ⅰ", "추진 배경", "□ 추진 근거", " ㅇ 학교교육계획", "Ⅱ", "세부 계획", "□ 교원 연수"):
        assert f">{text}<" in section
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        header = archive.read("Contents/header.xml").decode("utf-8")
    assert BAND_FILL in header


def test_cloned_tables_get_unique_deterministic_ids(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)
    plan = _plan(*({"role": "띠", "values": {"번호": n, "제목": "장"}} for n in ("Ⅰ", "Ⅱ", "Ⅲ")))

    first, _ = compose_bytes(plan, profile=profile)
    second, _ = compose_bytes(plan, profile=profile)

    ids = [re.findall(r'<hp:tbl id="(\d+)"', _section_xml(data)) for data in (first, second)]
    assert len(ids[0]) == 3 and len(set(ids[0])) == 3
    assert ids[0] == ids[1]


def test_missing_slot_is_blank_and_reported(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)

    data, result = compose_bytes(_plan({"role": "띠", "values": {"번호": "Ⅰ"}}), profile=profile)

    assert result.ok
    assert "{{" not in _section_xml(data)
    assert any("{{띠.제목}}" in warning for warning in result.warnings)


def test_block_without_text_or_values_uses_the_role_blank_silently(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)

    data, result = compose_bytes(_plan({"role": "1단계"}), profile=profile)

    assert result.ok
    assert "{{" not in _section_xml(data)
    assert not any("MARKED_SLOT_EMPTY" in warning for warning in result.warnings)


def test_unknown_role_is_refused_in_production(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)

    with pytest.raises(ProfileRequiredError, match="no role '3단계'"):
        compose_bytes(_plan({"role": "3단계", "text": "x"}), profile=profile)


def test_placeholder_split_across_runs_is_still_filled(tmp_path: Path) -> None:
    def split_run(doc: HwpxDocument) -> None:
        para = doc.add_paragraph("{{3단")
        para.add_run("계}}")

    _, profile = _harvest(tmp_path, extra=split_run)
    data, result = compose_bytes(_plan({"role": "3단계", "text": "나뉜 자리표시"}), profile=profile)

    assert result.ok
    assert "나뉜 자리표시" in _section_xml(data)
    assert "{{" not in _section_xml(data)


def test_one_paragraph_with_two_roles_is_rejected(tmp_path: Path) -> None:
    def mixed(doc: HwpxDocument) -> None:
        doc.add_paragraph("{{가}} {{나}}")

    with pytest.raises(MarkedTemplateError, match="several roles"):
        _harvest(tmp_path, extra=mixed)


def test_repeated_role_is_rejected(tmp_path: Path) -> None:
    def repeat(doc: HwpxDocument) -> None:
        doc.add_paragraph("□ {{1단계}}")

    with pytest.raises(MarkedTemplateError, match="more than once"):
        _harvest(tmp_path, extra=repeat)


def test_template_without_placeholders_is_rejected(tmp_path: Path) -> None:
    doc = HwpxDocument.new()
    doc.add_paragraph("자리표시 없음")
    doc.save_to_path(tmp_path / "plain.hwpx")
    doc.close()

    with pytest.raises(MarkedTemplateError, match="no \\{\\{placeholder\\}\\}"):
        harvest_marked_profile(tmp_path / "plain.hwpx", "x", tmp_path / "p")


def test_skeleton_drops_later_sections(tmp_path: Path) -> None:
    def second_section(doc: HwpxDocument) -> None:
        section = doc.add_section()
        doc.add_paragraph("둘째 구역의 원문", section=section)

    _harvest(tmp_path, extra=second_section)

    with zipfile.ZipFile(tmp_path / "p" / "report" / "template.hwpx") as archive:
        names = archive.namelist()
        texts = "".join(archive.read(n).decode("utf-8", "ignore") for n in names if n.endswith(".xml"))
    assert "Contents/section1.xml" not in names
    assert "둘째 구역의 원문" not in texts


def test_skeleton_keeps_images_used_by_header_fills(tmp_path: Path) -> None:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
        b"\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )

    def image_fill(doc: HwpxDocument) -> None:
        table = doc.add_table(1, 1)
        table.cell(0, 0).text = "{{그림칸}}"
        table.set_cell_fill_image(0, 0, doc.media.add_image(png, "png"))

    manifest, profile = _harvest(tmp_path, extra=image_fill)

    assert manifest["skeleton_open_safe"] is True
    _, result = compose_bytes(_plan({"role": "그림칸", "text": "x"}), profile=profile)
    assert result.ok, result.errors


def _with_click_here(doc: HwpxDocument) -> None:
    doc.add_paragraph("담당: {{담당}} ").add_form_field("연락처", prompt="여기에 입력")


def test_cloned_click_here_fields_keep_their_own_begin_end_pair(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path, extra=_with_click_here)

    data, result = compose_bytes(
        _plan({"role": "담당", "text": "갑"}, {"role": "담당", "text": "을"}), profile=profile
    )

    assert result.ok, result.errors
    section = _section_xml(data)
    begins = re.findall(r'<hp:fieldBegin id="(\d+)"', section)
    ends = re.findall(r'<hp:fieldEnd beginIDRef="(\d+)"', section)
    assert len(begins) == 2 and len(set(begins)) == 2
    assert ends == begins  # each end points at the begin of its own clone
    reopened = HwpxDocument.open(data)
    try:
        assert [field.name for field in reopened.fields.all] == ["연락처", "연락처"]
    finally:
        reopened.close()


def test_connector_follows_its_shapes_new_instance_id() -> None:
    from lxml import etree

    from hwpx_automation.office.authoring.design.composer import _reassign_object_ids

    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    clone = (
        f'<hp:p xmlns:hp="{hp}" id="0"><hp:run>'
        '<hp:rect id="7" instid="70"/><hp:connectLine id="8" instid="80">'
        '<hp:startPt subjectIDRef="70"/></hp:connectLine></hp:run></hp:p>'
    )
    paragraphs = [etree.fromstring(clone), etree.fromstring(clone)]

    _reassign_object_ids(paragraphs)

    instance_ids = [e.get("instid") for p in paragraphs for e in p.iter() if e.get("instid")]
    assert len(set(instance_ids)) == 4
    for paragraph in paragraphs:
        rect = next(e for e in paragraph.iter() if e.tag.endswith("}rect"))
        start = next(e for e in paragraph.iter() if e.tag.endswith("}startPt"))
        assert start.get("subjectIDRef") == rect.get("instid")


def test_value_with_no_placeholder_is_refused_in_production(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)
    lossy = _plan({"role": "띠", "values": {"번호": "Ⅰ", "제목": "장", "부제": "사라질 값"}})

    with pytest.raises(ProfileRequiredError, match="MARKED_VALUE_UNKNOWN"):
        compose_bytes(lossy, profile=profile)
    _, debug = compose_bytes(lossy, profile=profile, production=False)
    assert any("MARKED_VALUE_UNKNOWN" in warning for warning in debug.warnings)
    with pytest.raises(ProfileRequiredError, match="MARKED_VALUE_UNKNOWN"):
        compose_bytes(_plan({"role": "띠", "text": "어느 칸?"}), profile=profile)


def test_value_line_breaks_become_hancom_line_breaks(tmp_path: Path) -> None:
    _, profile = _harvest(tmp_path)

    data, result = compose_bytes(_plan({"role": "1단계", "text": "첫 줄\n둘째 줄"}), profile=profile)

    assert result.ok, result.errors
    section = _section_xml(data)
    assert "□ 첫 줄<hp:lineBreak/>둘째 줄" in section
    assert "첫 줄\n" not in section


def test_split_placeholder_leaves_the_other_runs_and_styles_alone(tmp_path: Path) -> None:
    def split_run(doc: HwpxDocument) -> None:
        para = doc.add_paragraph("{{3단")
        para.add_run("계}} 뒤 문구", bold=True)

    _, profile = _harvest(tmp_path, extra=split_run)
    data, result = compose_bytes(_plan({"role": "3단계", "text": "값"}), profile=profile)

    assert result.ok, result.errors
    from lxml import etree

    section = etree.fromstring(_section_xml(data).encode("utf-8"))
    runs = [
        (run.get("charPrIDRef"), "".join(t.text or "" for t in run if t.tag.endswith("}t")))
        for run in section.iter()
        if run.tag.endswith("}run")
    ]
    filled = [(ref, text) for ref, text in runs if text]
    assert [text for _, text in filled] == ["값", " 뒤 문구"]
    # The fixed text after the placeholder keeps its own (bold) run.
    assert filled[0][0] != filled[1][0]
