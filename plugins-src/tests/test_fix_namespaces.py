# SPDX-License-Identifier: Apache-2.0
"""fix_namespaces.py is a CLI wrapper around python-hwpx (#62).

The normalization itself is python-hwpx's
``hwpx.tools.repair.normalize_package_namespaces`` and is tested there. These
tests cover the wrapper: arguments, the target, backups, the stats it prints,
and that a result failing open-safety never replaces a file.
"""

import builtins
import importlib.util
import zipfile
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "scripts" / "fix_namespaces.py"
spec = importlib.util.spec_from_file_location("fix_namespaces", SPEC)
fix_namespaces_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fix_namespaces_module)

hwpx_repair = pytest.importorskip("hwpx.tools.repair")
if not hasattr(hwpx_repair, "normalize_package_namespaces"):  # pragma: no cover - older core
    pytest.skip("needs python-hwpx with normalize_package_namespaces", allow_module_level=True)

from hwpx import HwpxDocument  # noqa: E402


def _write_minimal_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<root/>")


def _document(path: Path) -> Path:
    doc = HwpxDocument.new()
    doc.add_paragraph("본문")
    path.write_bytes(doc.to_bytes())
    return path


def test_fix_namespaces_writes_the_hancom_root_surface_and_stats(tmp_path: Path) -> None:
    source = _document(tmp_path / "source.hwpx")
    target = tmp_path / "target.hwpx"

    stats = fix_namespaces_module.fix_namespaces(str(source), str(target))

    assert set(stats) == {"total_parts", "xml_parts", "xml_fixed", "xml_failed"}
    assert stats["total_parts"] >= stats["xml_parts"] >= 2 and stats["xml_failed"] == 0
    with zipfile.ZipFile(target) as archive:
        for name in ("Contents/header.xml", "Contents/section0.xml"):
            payload = archive.read(name)
            assert b"standalone='yes'" in payload or b'standalone="yes"' in payload
            assert b"xmlns:ha=" in payload and b"xmlns:hp10=" in payload


def test_fix_namespaces_public_api_does_not_accept_open_safety_bypass(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)

    with pytest.raises(TypeError, match="verify_open_safety"):
        fix_namespaces_module.fix_namespaces(str(source), str(target), verify_open_safety=False)


def test_fix_namespaces_function_preserves_existing_output_when_open_safety_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")

    with pytest.raises(RuntimeError, match="open-safety"):
        fix_namespaces_module.fix_namespaces(str(source), str(target))

    assert target.read_bytes() == b"existing output"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.hwpx", "target.hwpx"]


def test_validate_open_safety_fails_closed_when_editor_safety_validator_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original_import = builtins.__import__

    def fail_editor_safety_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "hwpx.tools.package_validator" and "validate_editor_open_safety" in fromlist:
            raise ImportError("old python-hwpx")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_editor_safety_import)

    with pytest.raises(RuntimeError, match=r"python-hwpx>=2\.10\.3"):
        fix_namespaces_module.validate_open_safety(str(source))


def test_main_preserves_existing_output_when_open_safety_validation_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")

    assert fix_namespaces_module.main([str(source), "--out", str(target)]) == 1
    assert target.read_bytes() == b"existing output"


def test_main_preserves_inplace_source_when_open_safety_validation_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original = source.read_bytes()

    assert fix_namespaces_module.main([str(source), "--inplace", "--backup"]) == 1
    assert source.read_bytes() == original
    assert not (tmp_path / "source.hwpx.bak").exists()


def test_main_inplace_backup_and_default_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _document(tmp_path / "source.hwpx")
    original = source.read_bytes()

    assert fix_namespaces_module.main([str(source)]) == 0
    assert (tmp_path / "source.hwpx.fixed.hwpx").is_file()
    assert fix_namespaces_module.main([str(source), "--inplace", "--backup"]) == 0
    assert (tmp_path / "source.hwpx.bak").read_bytes() == original
    out = capsys.readouterr().out
    assert "[OK] wrote (inplace):" in out and "[STATS] parts=" in out


def test_main_argument_errors(tmp_path: Path) -> None:
    assert fix_namespaces_module.main([str(tmp_path / "missing.hwpx")]) == 2
    notzip = tmp_path / "notzip.hwpx"
    notzip.write_bytes(b"plain")
    assert fix_namespaces_module.main([str(notzip)]) == 3
