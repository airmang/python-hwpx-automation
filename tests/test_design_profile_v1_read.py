"""A design profile written in the v1 format (fragments as <hp:p> XML files) still composes in 8.x."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from hwpx import HwpxDocument

from hwpx_automation.office.authoring.design import Profile, compose_bytes
from hwpx_automation.office.authoring.design.profile import _v1_template

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _fragment(text: str, para_pr: str = "0", char_pr: str = "0") -> bytes:
    return (
        f'<hp:p xmlns:hp="{HP}" id="1" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" '
        f'columnBreak="0" merged="0"><hp:run charPrIDRef="{char_pr}"><hp:t>{text}</hp:t></hp:run></hp:p>'
    ).encode("utf-8")


def _v1_profile(root: Path, *, section_namespace_carrier: bool = False) -> Path:
    folder = root / "legacy"
    (folder / "fragments").mkdir(parents=True)
    with HwpxDocument.new() as document:
        if section_namespace_carrier:
            # Skeletons harvested before 8.0 wrote the page-setup paragraph as hs:p/hs:run/hs:t.
            carrier = document.sections[0].paragraphs[0].element
            for node in carrier.iter():
                if isinstance(node.tag, str) and node.tag.split("}")[-1] in ("p", "run", "t") and node.tag.startswith(f"{{{HP}}}"):
                    node.tag = f"{{{HS}}}" + node.tag.split("}")[-1]
            document.sections[0].mark_dirty()
        document.save(folder / "template.hwpx")
    (folder / "fragments" / "title.xml").write_bytes(_fragment("{{title}}"))
    (folder / "fragments" / "body.xml").write_bytes(_fragment("{{body}}"))
    manifest = {
        "schemaVersion": "hwpx.design.profile.v1",
        "id": "legacy",
        "template": "template.hwpx",
        "fragments": {"title": "fragments/title.xml", "body": "fragments/body.xml"},
        "style_coverage_threshold": 0.98,
    }
    (folder / "profile.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def _fingerprint(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}


def _section_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("Contents/section0.xml").decode("utf-8")


def test_v1_profile_composes_and_its_files_are_not_rewritten(tmp_path: Path) -> None:
    folder = _v1_profile(tmp_path)
    before = _fingerprint(folder)

    profile = Profile.load(folder)
    data, result = compose_bytes(
        {"profile": "legacy", "title": "제목 줄", "blocks": [{"type": "paragraph", "role": "body", "text": "본문 줄"}]},
        profile=profile,
    )

    assert profile.schema == "hwpx.design.profile.v1"
    assert sorted(profile.roles) == ["body", "title"]
    assert result.ok, result.errors
    section = _section_xml(data)
    assert ">제목 줄<" in section and ">본문 줄<" in section and "{{" not in section
    assert _fingerprint(folder) == before


def test_v1_skeleton_with_a_section_namespace_carrier_is_read_as_a_paragraph(tmp_path: Path) -> None:
    folder = _v1_profile(tmp_path, section_namespace_carrier=True)
    assert "<hs:p" in _section_xml((folder / "template.hwpx").read_bytes())

    repaired = _v1_template((folder / "template.hwpx").read_bytes())
    assert "<hs:p" not in _section_xml(repaired)

    data, result = compose_bytes(
        {"profile": "legacy", "title": "제목", "blocks": []}, profile=Profile.load(folder)
    )
    assert result.ok, result.errors
    section = _section_xml(data)
    assert "<hs:p" not in section and "<hs:run" not in section and "secPr" in section
