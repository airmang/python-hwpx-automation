# SPDX-License-Identifier: Apache-2.0
"""The shipped ZIP scripts do not write an HWPX package over an ``.hwp`` that is already there.

``.hwp`` is an input format: an ``.hwp`` on disk is a file Hancom Office saved, and these
scripts write ZIP bytes. Before this, ``zip_replace_all.py in.hwpx old.hwp`` and
``fix_namespaces.py in.hwpx --out old.hwp`` ended with exit code 0 and ``old.hwp`` replaced.
"""

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


fix_namespaces_module = _load("fix_namespaces")
zip_replace_all_module = _load("zip_replace_all")

OLD_HWP = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"synthetic hwp bytes"


def _package(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", "<root>OLD</root>")
    return path


def _old_hwp(path: Path) -> Path:
    path.write_bytes(OLD_HWP)
    return path


def _names(folder: Path) -> list[str]:
    return sorted(item.name for item in folder.iterdir())


def test_zip_replace_all_refuses_an_existing_hwp_output(tmp_path: Path, capsys) -> None:
    source = _package(tmp_path / "in.hwpx")
    target = _old_hwp(tmp_path / "old.hwp")

    code = zip_replace_all_module.main([str(source), str(target), "--replace", "OLD=NEW"])

    assert code == 2
    assert ".hwp" in capsys.readouterr().err
    assert target.read_bytes() == OLD_HWP
    assert _names(tmp_path) == ["in.hwpx", "old.hwp"]

    with pytest.raises(FileExistsError):
        zip_replace_all_module.zip_replace_all(str(source), str(target), {"OLD": "NEW"})
    assert target.read_bytes() == OLD_HWP
    assert _names(tmp_path) == ["in.hwpx", "old.hwp"]


def test_fix_namespaces_refuses_an_existing_hwp_output(tmp_path: Path, capsys) -> None:
    source = _package(tmp_path / "in.hwpx")
    target = _old_hwp(tmp_path / "old.hwp")

    code = fix_namespaces_module.main([str(source), "--out", str(target)])

    assert code == 2
    assert ".hwp" in capsys.readouterr().err
    assert target.read_bytes() == OLD_HWP
    assert _names(tmp_path) == ["in.hwpx", "old.hwp"]

    with pytest.raises(FileExistsError):
        fix_namespaces_module.fix_namespaces(str(source), str(target))
    assert target.read_bytes() == OLD_HWP
    assert _names(tmp_path) == ["in.hwpx", "old.hwp"]


def test_a_new_hwp_name_is_not_what_the_refusal_is_about(tmp_path: Path) -> None:
    # Only a file that is already there is protected; the check does not look at new names.
    fix_namespaces_module.refuse_existing_hwp_output(tmp_path / "new.hwp")
    fix_namespaces_module.refuse_existing_hwp_output(_package(tmp_path / "there.hwpx"))
