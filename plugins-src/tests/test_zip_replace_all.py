# SPDX-License-Identifier: Apache-2.0
"""zip_replace_all.py is a CLI wrapper around python-hwpx (#62).

What is replaced, where and how the package is kept is python-hwpx's
``hwpx.patch.replace_package_text`` and is tested there
(``tests/test_package_text_and_namespaces.py``). These tests cover what the
wrapper still owns: arguments, the target, backups, the stats it prints, and
that a result failing open-safety never replaces a file.
"""

import importlib.util
import zipfile
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "scripts" / "zip_replace_all.py"
spec = importlib.util.spec_from_file_location("zip_replace_all", SPEC)
zip_replace_all_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(zip_replace_all_module)

hwpx_patch = pytest.importorskip("hwpx.patch")
if not hasattr(hwpx_patch, "replace_package_text"):  # pragma: no cover - older core
    pytest.skip("needs python-hwpx with replace_package_text", allow_module_level=True)

from hwpx import HwpxDocument  # noqa: E402


def _template(path: Path, *texts: str) -> Path:
    doc = HwpxDocument.new()
    for text in texts:
        doc.add_paragraph(text)
    doc.add_table(1, 1).cell(0, 0).text = "{CELL}"
    path.write_bytes(doc.to_bytes())
    return path


def _text(path: Path) -> str:
    return HwpxDocument.open(path.read_bytes()).text.plain()


def _write_minimal_zip(path: Path, text: str = "OLD") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", f"<root>{text}</root>")


def test_function_replaces_body_and_cells_and_reports_stats(tmp_path: Path) -> None:
    source = _template(tmp_path / "source.hwpx", "{NAME} 님께")
    target = tmp_path / "out" / "target.hwpx"

    stats = zip_replace_all_module.zip_replace_all(source, target, {"{NAME}": "홍길동", "{CELL}": "칸"})

    assert "홍길동 님께" in _text(target) and "칸" in _text(target)
    assert stats["replacements"] == 2
    assert stats["changed_xml"] == 1
    assert stats["parts"] >= stats["xml_parts"] >= 1
    assert set(stats) == {
        "parts",
        "xml_parts",
        "changed_xml",
        "replacements",
        "layout_caches_removed",
        "decode_failed",
    }


def test_public_api_does_not_accept_open_safety_bypass(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)

    with pytest.raises(TypeError, match="verify_open_safety"):
        zip_replace_all_module.zip_replace_all(source, target, {"OLD": "NEW"}, verify_open_safety=False)


def test_function_preserves_existing_output_when_open_safety_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)  # not an editor-openable package
    target.write_bytes(b"existing output")

    with pytest.raises(RuntimeError, match="open-safety"):
        zip_replace_all_module.zip_replace_all(source, target, {"OLD": "NEW"})

    assert target.read_bytes() == b"existing output"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.hwpx", "target.hwpx"]


def test_main_preserves_existing_output_when_open_safety_validation_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    target = tmp_path / "target.hwpx"
    _write_minimal_zip(source)
    target.write_bytes(b"existing output")

    result = zip_replace_all_module.main([str(source), str(target), "--replace", "OLD=NEW"])

    assert result == 1
    assert target.read_bytes() == b"existing output"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.hwpx", "target.hwpx"]


def test_main_preserves_inplace_source_when_open_safety_validation_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    _write_minimal_zip(source)
    original = source.read_bytes()

    result = zip_replace_all_module.main([str(source), "--inplace", "--backup", "--replace", "OLD=NEW"])

    assert result == 1
    assert source.read_bytes() == original
    assert not (tmp_path / "source.hwpx.bak").exists()  # no backup before validation passes


def test_main_inplace_with_backup_and_namespace_fix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _template(tmp_path / "source.hwpx", "{NAME}")
    original = source.read_bytes()

    result = zip_replace_all_module.main(
        [str(source), "--inplace", "--backup", "--auto-fix-ns", "--replace", "{NAME}=새 이름"]
    )

    out = capsys.readouterr().out
    assert result == 0
    assert (tmp_path / "source.hwpx.bak").read_bytes() == original
    assert "새 이름" in _text(source)
    assert "[STATS] parts=" in out and "replacements=1" in out
    assert "[NS] parts=" in out
    with zipfile.ZipFile(source) as archive:
        section = archive.read("Contents/section0.xml")
    assert b"xmlns:hp10=" in section


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["{in}", "--replace", "A=B"], 2),  # no output and no --inplace
        (["{in}", "{out}", "--inplace", "--replace", "A=B"], 2),
        (["{in}", "{out}", "--replace", "=B"], 2),
        (["{missing}", "{out}", "--replace", "A=B"], 2),
        (["{notzip}", "{out}", "--replace", "A=B"], 3),
    ],
)
def test_main_argument_errors(tmp_path: Path, argv: list[str], code: int) -> None:
    source = _template(tmp_path / "in.hwpx", "A")
    notzip = tmp_path / "notzip.hwpx"
    notzip.write_bytes(b"plain")
    paths = {
        "{in}": str(source),
        "{out}": str(tmp_path / "out.hwpx"),
        "{missing}": str(tmp_path / "missing.hwpx"),
        "{notzip}": str(notzip),
    }
    assert zip_replace_all_module.main([paths.get(item, item) for item in argv]) == code
    assert not (tmp_path / "out.hwpx").exists()


def test_xml_like_keys_warn(capsys: pytest.CaptureFixture[str]) -> None:
    assert zip_replace_all_module.warn_if_xml_like_keys({"<hp:t>": "x", "{A}": "y"}) == 1
    assert "plain text only" in capsys.readouterr().err
