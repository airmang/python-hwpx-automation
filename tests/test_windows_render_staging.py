# SPDX-License-Identifier: Apache-2.0
"""Windows renders must not stop at Hancom's file-access approval prompt.

Hancom asks the user to approve every automated open or save of a file outside
the user's temporary folder unless a file-path check module is registered, and
nobody answers that prompt in an automated run: the render waited out its
timeout and returned ``None``. ``WindowsComOracle`` therefore renders a copy
staged in a private temporary folder and moves only a finished PDF to the
requested path. The packaged scripts also register an installed module with
its module type, ``FilePathCheckDLL`` (#150).

Nothing here starts Hancom: ``subprocess.run`` is a fake that plays the
PowerShell backend.
"""

from __future__ import annotations

import errno
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from hwpx_automation.office.rendering.oracle import WindowsComOracle

ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / "src" / "hwpx_automation" / "office" / "rendering"
_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.mark.parametrize(
    "script",
    [
        RENDERING / "_render_hwpx.ps1",
        RENDERING / "_hancom_open_rate.ps1",
        ROOT / "scripts" / "m9_p0_box_render_probe.ps1",
        ROOT / "scripts" / "m9_p0_redline_text_probe.ps1",
    ],
    ids=lambda path: path.name,
)
def test_the_file_path_check_module_is_registered_with_its_module_type(script: Path) -> None:
    module_types = re.findall(r'RegisterModule\(\s*"([^"]*)"', script.read_text(encoding="utf-8"))
    assert module_types, "the script registers no file-path check module"
    assert set(module_types) == {"FilePathCheckDLL"}


def _fake_powershell(seen: list[dict[str, Any]], *, saved: bool = True) -> Any:
    """Play ``_render_hwpx.ps1``: read the job list, write each PDF, write the result."""

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        jobs = json.loads(Path(cmd[cmd.index("-Jobs") + 1]).read_text(encoding="utf-8"))
        entries = []
        for job in jobs:
            seen.append(dict(job, staged_bytes=Path(job["src"]).read_bytes()))
            if saved:
                Path(job["pdf"]).write_bytes(_PDF)
            entries.append(
                {"src": job["src"], "pdf": job["pdf"], "opened": True, "saved": saved,
                 "error": None, "registered": False}
            )
        # ConvertTo-Json writes a lone object for one job, and Set-Content a BOM.
        payload = entries[0] if len(entries) == 1 else entries
        Path(cmd[cmd.index("-ResultPath") + 1]).write_text(json.dumps(payload), encoding="utf-8-sig")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return run


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WindowsComOracle, "available", lambda self: True)


def _source(folder: Path, name: str = "원고.hwpx") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / name
    source.write_bytes(b"not a real package; the backend is a fake")
    return source


@pytest.mark.usefixtures("windows")
def test_hancom_opens_a_temporary_copy_and_the_pdf_lands_at_the_requested_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _fake_powershell(seen))
    source = _source(tmp_path / "docs")
    out = tmp_path / "out" / "원고.pdf"
    out.parent.mkdir()

    assert WindowsComOracle().render_many([(str(source), str(out))]) == {str(source): str(out)}
    assert out.read_bytes() == _PDF

    [job] = seen
    staged, staged_pdf = Path(job["src"]), Path(job["pdf"])
    assert staged.name == source.name
    assert job["staged_bytes"] == source.read_bytes()
    assert staged.is_relative_to(Path(tempfile.gettempdir()))
    assert not staged.is_relative_to(tmp_path)
    assert staged_pdf.parent == staged.parent
    assert not staged.parent.exists()  # the staging folder is removed afterwards


@pytest.mark.usefixtures("windows")
def test_a_batch_keeps_each_source_apart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _fake_powershell(seen))
    first = _source(tmp_path / "a", "같은이름.hwpx")
    second = _source(tmp_path / "b", "같은이름.hwpx")
    pairs = [(str(first), str(tmp_path / "1.pdf")), (str(second), str(tmp_path / "2.pdf"))]

    assert WindowsComOracle().render_many(pairs) == dict(pairs)
    assert len({Path(job["src"]).parent for job in seen}) == 2


@pytest.mark.usefixtures("windows")
def test_a_failed_render_leaves_an_existing_output_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_powershell([], saved=False))
    source = _source(tmp_path)
    out = tmp_path / "out.pdf"
    out.write_bytes(b"previous render")

    assert WindowsComOracle().render_pdf(str(source), str(out)) is None
    assert out.read_bytes() == b"previous render"


@pytest.mark.usefixtures("windows")
def test_a_missing_source_never_reaches_hancom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    missing = tmp_path / "missing.hwpx"

    assert WindowsComOracle().render_many([(str(missing), str(tmp_path / "o.pdf"))]) == {
        str(missing): None
    }
    assert calls == []


@pytest.mark.usefixtures("windows")
def test_a_pdf_from_another_volume_is_copied_beside_the_target_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_powershell([]))
    source = _source(tmp_path / "docs")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "원고.pdf"
    real_replace = os.replace
    moves: list[tuple[str, str]] = []

    def replace(src: Any, dst: Any) -> None:
        moves.append((os.fspath(src), os.fspath(dst)))
        if len(moves) == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)

    assert WindowsComOracle().render_many([(str(source), str(out))]) == {str(source): str(out)}
    assert out.read_bytes() == _PDF
    assert Path(moves[1][0]).parent == out_dir and moves[1][0].endswith(".part")
    assert sorted(path.name for path in out_dir.iterdir()) == [out.name]


@pytest.mark.usefixtures("windows")
def test_an_unwritable_output_folder_is_a_failed_render(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_powershell([]))
    source = _source(tmp_path)

    assert WindowsComOracle().render_pdf(str(source), str(tmp_path / "no" / "such" / "o.pdf")) is None
