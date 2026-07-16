from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "024-mixed-form"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_reference_024",
        DEMO / "build_reference.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _xml_member(path: Path, member: str) -> ElementTree.Element:
    with zipfile.ZipFile(path) as package:
        return ElementTree.fromstring(package.read(member))


def test_native_field_command_uses_the_payload_length() -> None:
    module = _module()
    direction = "사업명"
    payload = "Direction:wstring:3:사업명 HelpState:wstring:0:  "

    assert module._native_field_command(direction) == (
        f"Clickhere:set:{len(payload) - 1}:{payload}"
    )


def test_demo_024_uses_hancom_native_click_here_field_shape() -> None:
    module = _module()
    source_spec = json.loads((DEMO / "source-spec.json").read_text(encoding="utf-8"))
    native = source_spec["nativeField"]
    expected_command = module._native_field_command(native["name"])
    assert native["controlId"].isdigit()
    assert native["fieldId"].isdigit()
    assert native["controlId"] != native["fieldId"]

    for package_name in ("source.hwpx", "expected.hwpx"):
        package_path = DEMO / package_name
        section = _xml_member(package_path, "Contents/section0.xml")
        header = _xml_member(package_path, "Contents/header.xml")
        field_begin = section.find(f".//{{{HP}}}fieldBegin")
        field_end = section.find(f".//{{{HP}}}fieldEnd")
        assert field_begin is not None
        assert field_end is not None

        control = next(
            element
            for element in section.iter(f"{{{HP}}}ctrl")
            if field_begin in list(element)
        )
        assert control.attrib == {}
        assert field_begin.attrib == {
            "id": native["controlId"],
            "fieldid": native["fieldId"],
            "type": "CLICK_HERE",
            "name": native["name"],
            "editable": "1",
            "dirty": "0",
            "zorder": "-1",
            "metaTag": "",
        }
        assert field_end.attrib == {
            "beginIDRef": native["controlId"],
            "fieldid": native["fieldId"],
        }

        parameters = field_begin.find(f"{{{HP}}}parameters")
        assert parameters is not None
        assert parameters.attrib == {"cnt": "3", "name": ""}
        assert [child.attrib["name"] for child in parameters] == [
            "Prop",
            "Command",
            "Direction",
        ]
        values = {
            child.attrib["name"]: child.text or ""
            for child in parameters
        }
        assert values == {
            "Prop": "9",
            "Command": expected_command,
            "Direction": native["name"],
        }

        char_pr_ids = {
            element.attrib["id"]
            for element in header.iter(f"{{{HH}}}charPr")
        }
        field_runs = [
            run
            for run in section.iter(f"{{{HP}}}run")
            if run.find(f".//{{{HP}}}fieldBegin") is not None
            or run.find(f".//{{{HP}}}fieldEnd") is not None
        ]
        assert field_runs
        assert all(run.attrib["charPrIDRef"] in char_pr_ids for run in field_runs)

        with module.HwpxDocument.open(package_path) as document:
            fields = document.list_form_fields()
        assert len(fields) == 1
        assert fields[0]["field_id"] == native["controlId"]
        assert fields[0]["fieldid"] == native["fieldId"]
        assert fields[0]["name"] == native["name"]
