# SPDX-License-Identifier: Apache-2.0
"""Optional dependency extras: [hwp] is now empty, [http] stays uvicorn.

python-hwpx reads HWP 5.0 itself, so the ``.hwp`` text reader no longer needs
``olefile``. The ``[hwp]`` extra stays declared (installing nothing) so existing
install commands keep working.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hwpx_automation import hwp_support

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "hwp5" / "border_3d.hwp"


def test_hwp_extra_is_declared_and_empty() -> None:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - python < 3.11
        import tomli as tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["optional-dependencies"]["hwp"] == []
    assert not any(item.startswith("olefile") for item in project["dependencies"])


def test_hwp_text_reader_works_without_olefile(tmp_path: Path) -> None:
    source = tmp_path / "form.hwp"
    shutil.copy2(FIXTURE, source)
    script = textwrap.dedent(
        """
        import importlib.abc
        import sys
        from pathlib import Path

        class BlockOlefile(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "olefile" or fullname.startswith("olefile."):
                    raise ModuleNotFoundError("olefile intentionally blocked", name=fullname)
                return None

        sys.meta_path.insert(0, BlockOlefile())
        from hwpx_automation.hwp_support import extract_hwp_text
        snapshot = extract_hwp_text(Path(sys.argv[1]))
        print(snapshot.source)
        print("\\n".join(snapshot.paragraphs))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(source)],
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[0] == hwp_support.CORE_TEXT_SOURCE
    assert any("가나다라 ABC abc 123" in line for line in lines[1:])


def test_extract_hwp_text_rejects_other_suffixes(tmp_path: Path) -> None:
    path = tmp_path / "x.hwpx"
    path.write_bytes(b"PK")
    with pytest.raises(hwp_support.HwpBinaryError, match=".hwp"):
        hwp_support.extract_hwp_text(path)


def test_extract_hwp_text_reports_unreadable_files(tmp_path: Path) -> None:
    path = tmp_path / "x.hwp"
    path.write_bytes(b"not really ole")
    with pytest.raises(hwp_support.HwpBinaryError) as excinfo:
        hwp_support.extract_hwp_text(path)
    assert "HWP" in str(excinfo.value)
