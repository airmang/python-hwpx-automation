# SPDX-License-Identifier: Apache-2.0
import builtins
import importlib.util
import zipfile
from pathlib import Path


SPEC = Path(__file__).resolve().parents[1] / "scripts" / "fix_namespaces.py"
spec = importlib.util.spec_from_file_location("fix_namespaces", SPEC)
fix_namespaces_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fix_namespaces_module)


def _write_minimal_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<root/>")


def test_fix_namespaces_normalizes_hwpml_root_namespace_surface(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>'
        "</hs:sec>"
    )
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"/>'
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)

    stats = fix_namespaces_module._fix_namespaces_unchecked(
        str(source),
        str(target),
    )

    assert stats["xml_parts"] == 2
    with zipfile.ZipFile(target) as archive:
        header_xml = archive.read("Contents/header.xml")
        section_xml = archive.read("Contents/section0.xml")
    for payload in (header_xml, section_xml):
        assert b"standalone='yes'" in payload or b'standalone="yes"' in payload
        assert b"xmlns:ha=" in payload
        assert b"xmlns:hp10=" in payload


def test_fix_namespaces_public_api_does_not_accept_open_safety_bypass(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)

    try:
        fix_namespaces_module.fix_namespaces(
            str(source),
            str(target),
            verify_open_safety=False,
        )
    except TypeError as exc:
        assert "verify_open_safety" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("public fix_namespaces should not expose a safety bypass")


def test_fix_namespaces_function_preserves_existing_output_when_open_safety_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")
    monkeypatch.setattr(
        fix_namespaces_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    try:
        fix_namespaces_module.fix_namespaces(str(source), str(target))
    except RuntimeError as exc:
        assert "unsafe" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("fix_namespaces should reject unsafe output")

    assert target.read_bytes() == b"existing output"
    assert not list(tmp_path.glob("hwpx-ns-*.hwpx"))


def test_validate_open_safety_fails_closed_when_editor_safety_validator_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original_import = builtins.__import__

    def fail_editor_safety_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (
            name == "hwpx.tools.package_validator"
            and "validate_editor_open_safety" in fromlist
        ):
            raise ImportError("old python-hwpx")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_editor_safety_import)

    try:
        fix_namespaces_module.validate_open_safety(str(source))
    except RuntimeError as exc:
        assert "python-hwpx>=2.10.3" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("open-safety validation should fail without the validator")


def test_main_preserves_existing_output_when_open_safety_validation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")
    monkeypatch.setattr(
        fix_namespaces_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    result = fix_namespaces_module.main([str(source), "--out", str(target)])

    assert result == 1
    assert target.read_bytes() == b"existing output"
    assert not list(tmp_path.glob("hwpx-ns-*.hwpx"))


def test_main_preserves_inplace_source_when_open_safety_validation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original = source.read_bytes()
    monkeypatch.setattr(
        fix_namespaces_module,
        "validate_open_safety",
        lambda _path: (_ for _ in ()).throw(RuntimeError("unsafe")),
    )

    result = fix_namespaces_module.main([str(source), "--inplace"])

    assert result == 1
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("hwpx-ns-*.hwpx"))
