# SPDX-License-Identifier: Apache-2.0
"""Helper programs are never taken from the working directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from hwpx_automation import configuration
from hwpx_automation.ops_services import preview_export


def _plant(directory: Path, stem: str) -> Path:
    name = f"{stem}.cmd" if sys.platform == "win32" else stem
    target = directory / name
    target.write_text("@echo off\r\n" if sys.platform == "win32" else "#!/bin/sh\n")
    target.chmod(0o755)
    return target


@pytest.fixture
def workspace_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("HWPX_AUTOMATION_CHROME_PATH", raising=False)
    monkeypatch.delenv("HWPX_MCP_CHROME_PATH", raising=False)
    return workspace


def test_chrome_lookup_ignores_working_directory(
    workspace_cwd: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for stem in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        _plant(workspace_cwd, stem)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    # Relative, "." and cwd-equal PATH entries must all be skipped.
    monkeypatch.setenv(
        "PATH", os.pathsep.join([".", "", str(workspace_cwd), "relative-bin", str(empty)])
    )

    assert preview_export._chrome_executable() is None


def test_chrome_lookup_rejects_relative_override(
    workspace_cwd: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = _plant(workspace_cwd, "chromium")
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("HWPX_AUTOMATION_CHROME_PATH", planted.name)

    assert preview_export._chrome_executable() is None

    monkeypatch.setenv("HWPX_AUTOMATION_CHROME_PATH", str(planted))
    assert preview_export._chrome_executable() == str(planted)


def test_chrome_lookup_still_finds_absolute_path_entry(
    workspace_cwd: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    installed = _plant(bin_dir, "chromium")
    monkeypatch.setenv("PATH", str(bin_dir))

    found = preview_export._chrome_executable()

    assert found is not None
    assert Path(found).is_absolute()
    assert os.path.normcase(found) == os.path.normcase(str(installed))


def test_find_executable_rejects_names_with_directories(workspace_cwd: Path) -> None:
    _plant(workspace_cwd, "tool")
    assert configuration.find_executable(os.path.join(".", "tool")) is None
    assert configuration.find_executable("") is None


def test_powershell_default_is_not_a_bare_name_on_windows(workspace_cwd: Path) -> None:
    from hwpx_automation.office.rendering.oracle import WindowsComOracle
    from hwpx_automation.office.rendering.worker import PowerShellHancomSession

    _plant(workspace_cwd, "powershell")
    oracle_program = WindowsComOracle()._powershell
    worker_program = PowerShellHancomSession(hancom_build="test-build").powershell
    explicit = configuration.windows_powershell("powershell")

    for program in (oracle_program, worker_program, explicit):
        assert Path(program).resolve().parent != workspace_cwd.resolve()
        if sys.platform == "win32":
            assert Path(program).is_absolute()


def test_powershell_explicit_path_is_preserved(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "pwsh.exe"
    assert configuration.windows_powershell(str(custom)) == str(custom)
