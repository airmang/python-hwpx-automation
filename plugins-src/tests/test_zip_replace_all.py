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

    stats = zip_replace_all_module._zip_replace_all_unchecked(
        source,
        target,
        {"OLD": "NEW TEXT"},
    )

    with zipfile.ZipFile(target) as archive:
        changed_xml = archive.read("Contents/section0.xml").decode("utf-8")
        unchanged_xml = archive.read("Contents/unchanged.xml").decode("utf-8")

    assert "NEW TEXT" in changed_xml
    assert "lineSegArray" not in changed_xml
    assert "standalone='yes'" in changed_xml or 'standalone="yes"' in changed_xml
    assert "xmlns:ha=" in changed_xml
    assert "xmlns:hp10=" in changed_xml
    assert "lineSegArray" in unchanged_xml
    assert stats["replacements"] == 1
    assert stats["layout_caches_removed"] == 1


def test_zip_replace_all_includes_hpf_metadata_parts(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<root/>")
        archive.writestr(
            "Contents/content.hpf",
            '<opf:package xmlns:opf="urn:opf"><opf:meta>OLD AUTHOR</opf:meta></opf:package>',
        )

    stats = zip_replace_all_module._zip_replace_all_unchecked(
        source,
        target,
        {"OLD AUTHOR": "synthetic-fixture-author"},
    )

    with zipfile.ZipFile(target) as archive:
        metadata = archive.read("Contents/content.hpf").decode("utf-8")

    assert "synthetic-fixture-author" in metadata
    assert "OLD AUTHOR" not in metadata
    assert stats["replacements"] == 1


def test_zip_replace_all_public_api_does_not_accept_open_safety_bypass(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)

    try:
        zip_replace_all_module.zip_replace_all(
            source,
            target,
            {"OLD": "NEW"},
            verify_open_safety=False,
        )
    except TypeError as exc:
        assert "verify_open_safety" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("public zip_replace_all should not expose a safety bypass")


def _write_minimal_zip(path: Path, text: str = "OLD") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", f"<root>{text}</root>")


def test_zip_replace_all_function_preserves_existing_output_when_open_safety_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")
    monkeypatch.setattr(
        zip_replace_all_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    try:
        zip_replace_all_module.zip_replace_all(source, target, {"OLD": "NEW"})
    except RuntimeError as exc:
        assert "unsafe" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("zip_replace_all should reject unsafe output")

    assert target.read_bytes() == b"existing output"
    assert not list(tmp_path.glob("hwpx-replace-*.hwpx"))


def test_main_preserves_existing_output_when_open_safety_validation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")
    monkeypatch.setattr(
        zip_replace_all_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    result = zip_replace_all_module.main(
        [str(source), str(target), "--replace", "OLD=NEW"]
    )

    assert result == 1
    assert target.read_bytes() == b"existing output"
    assert not list(tmp_path.glob("hwpx-replace-*.hwpx"))


def test_main_preserves_inplace_source_when_open_safety_validation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original = source.read_bytes()
    monkeypatch.setattr(
        zip_replace_all_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    result = zip_replace_all_module.main(
        [str(source), "--inplace", "--replace", "OLD=NEW"]
    )

    assert result == 1
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("hwpx-replace-*.hwpx"))
