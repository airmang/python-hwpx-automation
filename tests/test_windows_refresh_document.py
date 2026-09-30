# SPDX-License-Identifier: Apache-2.0
"""``WindowsComOracle.refresh_document``: Hancom lays a document out and saves it.

The Mac backend already re-saves a document through Hancom so that the file
carries Hancom's own line layout cache (``hp:linesegarray``); the Windows COM
backend had no such method (#152). It saves through the same PowerShell
backend as the render, from a copy in a private temporary folder, and replaces
the original only with a complete package.

Nothing here starts Hancom: ``subprocess.run`` is a fake that plays the
PowerShell backend.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from hwpx_automation.office.rendering.oracle import WindowsComOracle

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src" / "hwpx_automation" / "office" / "rendering" / "_render_hwpx.ps1"
)


def _package(section: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        package.writestr("Contents/section0.xml", section)
    return buffer.getvalue()


_ORIGINAL = _package(b"<hs:sec><hp:p/></hs:sec>")
_SAVED = _package(b"<hs:sec><hp:p><hp:linesegarray/></hp:p></hs:sec>")


def _fake_powershell(seen: list[dict[str, Any]], *, saved: bool = True, payload: bytes = _SAVED) -> Any:
    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        jobs = json.loads(Path(cmd[cmd.index("-Jobs") + 1]).read_text(encoding="utf-8"))
        entries = []
        for job in jobs:
            seen.append(dict(job, staged_bytes=Path(job["src"]).read_bytes()))
            if saved:
                Path(job["out"]).write_bytes(payload)
            entries.append({"src": job["src"], "pdf": job["out"], "opened": True, "saved": saved,
                            "error": None, "registered": False})
        result = entries[0] if len(entries) == 1 else entries
        Path(cmd[cmd.index("-ResultPath") + 1]).write_text(json.dumps(result), encoding="utf-8-sig")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return run


@pytest.fixture
def document(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "문서.hwpx"
    path.parent.mkdir()
    path.write_bytes(_ORIGINAL)
    return path


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WindowsComOracle, "available", lambda self: True)


@pytest.mark.usefixtures("windows")
def test_hancoms_save_replaces_the_document(
    monkeypatch: pytest.MonkeyPatch, document: Path, tmp_path: Path
) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _fake_powershell(seen))

    assert WindowsComOracle().refresh_document(str(document)) is True
    assert document.read_bytes() == _SAVED

    [job] = seen
    assert job["format"] == "HWPX"
    assert job["staged_bytes"] == _ORIGINAL
    for key in ("src", "out"):
        staged = Path(job[key])
        assert staged.name == document.name
        assert staged.is_relative_to(Path(tempfile.gettempdir()))
        assert not staged.is_relative_to(tmp_path)
    assert Path(job["src"]).parent != Path(job["out"]).parent


@pytest.mark.usefixtures("windows")
def test_a_failed_save_leaves_the_document_alone(
    monkeypatch: pytest.MonkeyPatch, document: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_powershell([], saved=False))

    assert WindowsComOracle().refresh_document(str(document)) is False
    assert document.read_bytes() == _ORIGINAL


@pytest.mark.usefixtures("windows")
def test_an_incomplete_package_is_not_promoted(
    monkeypatch: pytest.MonkeyPatch, document: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_powershell([], payload=b"PK\x03\x04 cut short"))

    assert WindowsComOracle().refresh_document(str(document)) is False
    assert document.read_bytes() == _ORIGINAL


def test_no_hancom_or_no_budget_never_starts_the_backend(
    monkeypatch: pytest.MonkeyPatch, document: Path
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))

    monkeypatch.setattr(WindowsComOracle, "available", lambda self: False)
    assert WindowsComOracle().refresh_document(str(document)) is False
    monkeypatch.setattr(WindowsComOracle, "available", lambda self: True)
    assert WindowsComOracle(budget_seconds=0.0).refresh_document(str(document)) is False
    assert WindowsComOracle().refresh_document(str(document.with_name("missing.hwpx"))) is False
    assert calls == []
    assert document.read_bytes() == _ORIGINAL


def test_the_backend_lays_the_document_out_before_a_non_pdf_save() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    loop = script[script.index("foreach ($job in $jobList)"):]
    assert re.search(r"\$format -ne \"PDF\".*?\$hwp\.PageCount.*?SaveAs\(\$pdf, \$format", loop, re.S)
