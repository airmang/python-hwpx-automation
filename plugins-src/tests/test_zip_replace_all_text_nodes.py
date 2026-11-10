# SPDX-License-Identifier: Apache-2.0
"""zip_replace_all.py replaces text nodes only (audit ENG-02 / ENG-35).

Attribute values (sizes, ids, font names) must survive any key, values are
escaped, and a line break in a value becomes ``hp:lineBreak``.
"""

import importlib.util
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "zip_replace_all.py"
spec = importlib.util.spec_from_file_location("zip_replace_all_text_nodes", SPEC)
zip_replace_all_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(zip_replace_all_module)

_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HEADER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" version="1.4" secCnt="1">'
    '<hh:fontface lang="HANGUL" fontCnt="2">'
    '<hh:font id="0" face="함초롬바탕" type="TTF"/><hh:font id="1" face="함초롬돋움" type="TTF"/>'
    "</hh:fontface>"
    '<hh:charPr id="0" height="1000" textColor="#000000"/>'
    '<hh:charPr id="1" height="1100" textColor="#000000"/>'
    "</hh:head>"
)
_SECTION_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{_HP}">'
    '<hp:p id="100" paraPrIDRef="0"><hp:run charPrIDRef="0">'
    "<hp:t>바탕 화면에 100원, {NAME} 귀하</hp:t></hp:run>"
    '<hp:linesegarray><hp:lineseg textpos="0" vertpos="100" horzsize="1000"/></hp:linesegarray>'
    "</hp:p>"
    '<hp:p id="101" paraPrIDRef="0"><hp:run charPrIDRef="1">'
    "<hp:t>A &amp; B &lt;끝&gt;</hp:t></hp:run></hp:p>"
    "<!-- 바탕 100 {NAME} -->"
    "</hs:sec>"
)
_HPF_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.4" unique-identifier="100">'
    "<opf:metadata><opf:title>{NAME}</opf:title></opf:metadata></opf:package>"
)


def _write_styled_package(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", _HEADER_XML)
        archive.writestr("Contents/section0.xml", _SECTION_XML)
        archive.writestr("Contents/content.hpf", _HPF_XML)


def _attributes(xml: str) -> list[tuple[str, str, str]]:
    """Every attribute value outside the line-layout caches, which a changed part drops."""

    root = ET.fromstring(xml.encode("utf-8"))
    return sorted(
        (element.tag, name, value)
        for element in root.iter()
        for name, value in element.attrib.items()
        if "lineseg" not in element.tag.lower()
    )


def _text_of(xml: str) -> str:
    return "".join(ET.fromstring(xml.encode("utf-8")).itertext())


def _run(path_kind: str, source: Path, target: Path, replacements: dict[str, str]) -> dict[str, int]:
    if path_kind == "builtin":
        return zip_replace_all_module._builtin_zip_replace_all(source, target, replacements)
    if zip_replace_all_module._engine_replace_package_text() is None:
        pytest.skip("installed python-hwpx has no hwpx.patch.replace_package_text")
    return zip_replace_all_module._zip_replace_all_unchecked(source, target, replacements)


def _read(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


@pytest.mark.parametrize("path_kind", ["builtin", "engine"])
def test_digit_key_leaves_sizes_ids_and_other_attribute_values_alone(tmp_path: Path, path_kind: str) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)

    stats = _run(path_kind, source, target, {"100": "999"})

    section = _read(target, "Contents/section0.xml")
    # height="1000" must not become "9990".
    assert _read(target, "Contents/header.xml") == _HEADER_XML
    assert _read(target, "Contents/content.hpf") == _HPF_XML
    assert _attributes(section) == _attributes(_SECTION_XML)
    assert "999원" in _text_of(section)
    assert "<!-- 바탕 100 {NAME} -->" in section
    assert "linesegarray" not in section
    assert stats["replacements"] == 1
    assert stats["changed_xml"] == 1
    assert stats["layout_caches_removed"] == 1


@pytest.mark.parametrize("path_kind", ["builtin", "engine"])
def test_word_inside_a_font_name_does_not_rename_the_font(tmp_path: Path, path_kind: str) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)

    stats = _run(path_kind, source, target, {"바탕": "기반"})

    header = _read(target, "Contents/header.xml")
    assert header == _HEADER_XML
    assert re.findall(r'face="([^"]+)"', header) == ["함초롬바탕", "함초롬돋움"]
    assert _text_of(_read(target, "Contents/section0.xml")).startswith("기반 화면에")
    assert stats["replacements"] == 1


@pytest.mark.parametrize("path_kind", ["builtin", "engine"])
def test_values_with_xml_special_characters_are_escaped(tmp_path: Path, path_kind: str) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)

    stats = _run(
        path_kind,
        source,
        target,
        {"{NAME}": "R&D <1팀>", "끝": "</hp:t><hp:t>주입"},
    )

    section = _read(target, "Contents/section0.xml")
    root = ET.fromstring(section.encode("utf-8"))  # still well-formed
    texts = [element.text for element in root.iter(f"{{{_HP}}}t")]
    assert texts == ["바탕 화면에 100원, R&D <1팀> 귀하", "A & B <</hp:t><hp:t>주입>"]
    assert "R&amp;D &lt;1팀&gt;" in section
    assert _text_of(_read(target, "Contents/content.hpf")) == "R&D <1팀>"
    assert stats["replacements"] == 3


@pytest.mark.parametrize("path_kind", ["builtin", "engine"])
def test_key_with_ampersand_matches_escaped_source_text(tmp_path: Path, path_kind: str) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)

    stats = _run(path_kind, source, target, {"A & B": "갑과 을"})

    assert stats["replacements"] == 1
    assert "갑과 을 &lt;끝&gt;" in _read(target, "Contents/section0.xml")


def test_newline_in_value_becomes_line_break_element_whatever_the_engine(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)

    stats = zip_replace_all_module._zip_replace_all_unchecked(
        source, target, {"{NAME}": "홍길동\r\n2학년 3반\n담임"}
    )

    section = _read(target, "Contents/section0.xml")
    assert "홍길동<hp:lineBreak/>2학년 3반<hp:lineBreak/>담임 귀하</hp:t>" in section
    root = ET.fromstring(section.encode("utf-8"))
    first = next(root.iter(f"{{{_HP}}}t"))
    assert "\n" not in "".join(first.itertext())
    assert len(first.findall(f"{{{_HP}}}lineBreak")) == 2
    # Outside a paragraph text element there is no lineBreak to write: it stays plain text.
    hpf = _read(target, "Contents/content.hpf")
    assert "lineBreak" not in hpf
    assert "홍길동\n2학년 3반\n담임" in hpf
    assert stats["replacements"] == 2


def test_engine_api_is_used_when_available_and_no_value_has_a_line_break(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)
    calls: list[dict[str, str]] = []

    class _Result:
        data = b"engine-bytes"
        entries = ("a", "b", "c")
        scanned_parts = ("a", "b")
        changed_parts = ("a",)
        replacements = 5
        layout_caches_removed = 2
        undecodable_parts = ()

    def fake_replace_package_text(data, replacements):
        assert isinstance(data, bytes)
        calls.append(dict(replacements))
        return _Result()

    monkeypatch.setattr(
        zip_replace_all_module, "_engine_replace_package_text", lambda: fake_replace_package_text
    )

    stats = zip_replace_all_module._zip_replace_all_unchecked(source, target, {"{NAME}": "홍길동"})
    assert calls == [{"{NAME}": "홍길동"}]
    assert target.read_bytes() == b"engine-bytes"
    assert stats == {
        "parts": 3,
        "xml_parts": 2,
        "changed_xml": 1,
        "replacements": 5,
        "layout_caches_removed": 2,
        "decode_failed": 0,
    }

    zip_replace_all_module._zip_replace_all_unchecked(source, target, {"{NAME}": "홍\n길동"})
    assert len(calls) == 1  # a line break keeps the work in the built-in replacer
    assert "홍<hp:lineBreak/>길동" in _read(target, "Contents/section0.xml")


def test_builtin_replacer_is_used_when_engine_has_no_package_text_api(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)
    monkeypatch.setattr(zip_replace_all_module, "_engine_replace_package_text", lambda: None)

    stats = zip_replace_all_module._zip_replace_all_unchecked(source, target, {"100": "999"})

    assert _read(target, "Contents/header.xml") == _HEADER_XML
    assert stats["replacements"] == 1


@pytest.mark.parametrize(
    "replacements",
    [{"100": "999"}, {"바탕": "기반"}, {"0": "9", "돋움": "X&<"}],
)
def test_real_document_keeps_every_attribute_value_and_font_name(
    tmp_path: Path, replacements: dict[str, str]
) -> None:
    """The audit case: digits and a font-name fragment on a Hangul-saved document."""

    source = ROOT / "demo" / "024-mixed-form" / "source.hwpx"
    with zipfile.ZipFile(source) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".xml", ".hpf"))]
        before = {name: archive.read(name).decode("utf-8") for name in names}

    target = tmp_path / "out.hwpx"
    zip_replace_all_module._builtin_zip_replace_all(source, target, replacements)

    for name in names:
        assert _attributes(_read(target, name)) == _attributes(before[name]), name


def test_main_warns_when_nothing_matched(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_styled_package(source)
    monkeypatch.setattr(zip_replace_all_module, "validate_open_safety", lambda _path: None)

    result = zip_replace_all_module.main([str(source), str(target), "--replace", "1000=9990"])

    captured = capsys.readouterr()
    assert result == 0
    assert "replacements=0" in captured.out
    assert "no text matched" in captured.err
    assert _read(target, "Contents/header.xml") == _HEADER_XML
