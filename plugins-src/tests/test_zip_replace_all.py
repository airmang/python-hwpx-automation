# SPDX-License-Identifier: Apache-2.0
import importlib.util
import zipfile
from pathlib import Path


SPEC = Path(__file__).resolve().parents[1] / "scripts" / "zip_replace_all.py"
spec = importlib.util.spec_from_file_location("zip_replace_all", SPEC)
zip_replace_all_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(zip_replace_all_module)


def test_zip_replace_all_removes_layout_cache_from_changed_xml(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p>
    <hp:run><hp:t>OLD</hp:t></hp:run>
    <hp:lineSegArray><hp:lineseg textpos="0"/></hp:lineSegArray>
  </hp:p>
</hs:sec>
"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", xml)
        archive.writestr("Contents/unchanged.xml", "<root><hp:lineSegArray xmlns:hp='x'/></root>")

    stats = zip_replace_all_module.zip_replace_all(source, target, {"OLD": "NEW TEXT"})

    with zipfile.ZipFile(target) as archive:
        changed_xml = archive.read("Contents/section0.xml").decode("utf-8")
        unchanged_xml = archive.read("Contents/unchanged.xml").decode("utf-8")

    assert "NEW TEXT" in changed_xml
    assert "lineSegArray" not in changed_xml
    assert "lineSegArray" in unchanged_xml
    assert stats["replacements"] == 1
    assert stats["layout_caches_removed"] == 1
