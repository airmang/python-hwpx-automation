from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from repo_build_lock import repo_build_lock

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FENCE = re.compile(
    r"^```(?:python|py)(?:[ \t]+[^\n]*)?\n(.*?)^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
CANONICAL_STACK_TABLE = """\
| | 저장소 | 역할 |
|---|---|---|
| 📦 | [`python-hwpx`](https://github.com/airmang/python-hwpx) | HWPX 문서를 읽고·고치고·만드는 순수 파이썬 엔진 |
| 🔌 | [`python-hwpx-automation`](https://github.com/airmang/python-hwpx-automation) | 저작·양식 채움 워크플로, `hwpx` CLI, 선택형 MCP 서버 |
| 🎯 | [`hwpx-plugins`](https://github.com/airmang/hwpx-plugins) | 에이전트가 알맞은 도구를 고르도록 돕는 플러그인/스킬 번들 |\
"""


def _readme_python_block() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = PYTHON_FENCE.findall(readme)
    assert len(blocks) == 1, (
        "Every current README Python block must enter this installed-wheel gate"
    )
    return blocks[0]


def _matching_core_repo() -> Path:
    explicit = os.environ.get("PYTHON_HWPX_REPO")
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
    else:
        name = ROOT.name
        candidate = ROOT.parent / f".no-matching-core-for-{name}"
        for prefix in ("python-hwpx-automation", "hwpx-mcp-server"):
            if prefix in name:
                candidate = ROOT.parent / name.replace(prefix, "python-hwpx", 1)
                break
    pyproject = candidate / "pyproject.toml"
    assert pyproject.is_file(), (
        "Set PYTHON_HWPX_REPO to the exact candidate checkout; the owner's "
        "unmatched ../python-hwpx checkout is never a fallback"
    )
    assert 'name = "python-hwpx"' in pyproject.read_text(encoding="utf-8")
    return candidate.resolve()


def _export_git_head(source: Path, destination: Path) -> None:
    archive = destination.parent / f"{destination.name}.tar"
    subprocess.run(
        ["git", "-C", str(source), "archive", "--format=tar", "-o", str(archive), "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            assert target.is_relative_to(destination.resolve()), member.name
        try:
            bundle.extractall(destination, filter="data")
        except TypeError:  # Python 3.10
            bundle.extractall(destination)


def test_readme_uses_the_canonical_three_stack_table() -> None:
    assert CANONICAL_STACK_TABLE in (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_python_example_runs_saves_and_reopens_from_base_wheel(
    tmp_path: Path,
) -> None:
    pytest.importorskip("build")
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for the clean installed-wheel gate"

    clean_core = tmp_path / "clean-core"
    _export_git_head(_matching_core_repo(), clean_core)
    dist = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(dist),
            str(clean_core),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with repo_build_lock():  # one build of the repository root at a time (xdist workers)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(dist),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    core_wheel = next(dist.glob("python_hwpx-*.whl"))
    automation_wheel = next(dist.glob("python_hwpx_automation-*.whl"))
    with zipfile.ZipFile(automation_wheel) as archive:
        names = archive.namelist()
        metadata_name = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        # A wheel built on Windows writes METADATA with CRLF line ends.
        metadata = archive.read(metadata_name).decode("utf-8").replace("\r\n", "\n")
        assert "Name: python-hwpx-automation\n" in metadata
        assert "Provides-Extra: mcp\n" in metadata
        assert not any(name.startswith("mcp/") for name in names)
        assert not any(name.startswith("hwpx_mcp_server/") for name in names)

    bootstrap = tmp_path / "bootstrap"
    subprocess.run(
        [
            uv,
            "venv",
            "--seed",
            "--no-project",
            "--python",
            sys.executable,
            str(bootstrap),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    bootstrap_python = bootstrap / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    core_version = core_wheel.name.split("-")[1]
    automation_version = automation_wheel.name.split("-")[1]
    wheelhouse = tmp_path / "wheelhouse"
    subprocess.run(
        [
            str(bootstrap_python),
            "-m",
            "pip",
            "download",
            "--dest",
            str(wheelhouse),
            # The candidate wheels are not on any index; without this,
            # automation's python-hwpx dependency resolves against PyPI and the
            # gate only passes while the pinned floor happens to be published.
            "--find-links",
            str(dist),
            str(core_wheel),
            str(automation_wheel),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    clean_environment = tmp_path / "clean-environment"
    subprocess.run(
        [
            uv,
            "venv",
            "--no-project",
            "--python",
            sys.executable,
            str(clean_environment),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    clean_python = clean_environment / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    hwpx_console = clean_environment / (
        "Scripts/hwpx.exe" if os.name == "nt" else "bin/hwpx"
    )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(clean_python),
            "--no-index",
            "--find-links",
            str(wheelhouse),
            # Derived from the wheels this test just built - a literal
            # coordinate here is exactly the stale-pin lie the release train
            # exists to prevent.
            f"python-hwpx=={core_version}",
            f"python-hwpx-automation=={automation_version}",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    case_root = tmp_path / "case"
    case_root.mkdir()
    example = _readme_python_block()
    probe = "\n".join(
        (
            "from pathlib import Path",
            "import importlib.util",
            "import sys",
            "from importlib.metadata import PackageNotFoundError, distribution",
            "import hwpx_automation as _automation",
            "import hwpx as _core",
            "from hwpx import HwpxDocument",
            f"_installed = Path({str(clean_environment)!r}).resolve()",
            "_core_origin = Path(_core.__file__).resolve()",
            "_automation_origin = Path(_automation.__file__).resolve()",
            "assert _core_origin.is_relative_to(_installed), (_core_origin, _installed)",
            "assert _automation_origin.is_relative_to(_installed), (_automation_origin, _installed)",
            "assert Path(distribution('python-hwpx').locate_file('')).resolve().is_relative_to(_installed)",
            "assert Path(distribution('python-hwpx-automation').locate_file('')).resolve().is_relative_to(_installed)",
            "assert importlib.util.find_spec('mcp') is None",
            "assert importlib.util.find_spec('hwpx_mcp_server') is None",
            "try:",
            "    distribution('mcp')",
            "except PackageNotFoundError:",
            "    pass",
            "else:",
            "    raise AssertionError('base install unexpectedly contains mcp')",
            f"_code = {example!r}",
            "exec(compile(_code, 'README.md#python-1', 'exec'), {'__name__': '__main__'})",
            "_output = Path('meeting-result.hwpx')",
            "assert _output.is_file()",
            "with HwpxDocument.open(_output) as _reopened:",
            "    assert '결정 사항' in _reopened.text.plain()",
            "assert 'mcp' not in sys.modules",
        )
    )
    environment = os.environ.copy()
    for name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    environment["PATH"] = str(hwpx_console.parent) + os.pathsep + os.defpath
    environment["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [str(clean_python), "-I", "-c", probe],
        cwd=case_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    cli_help = subprocess.run(
        [str(hwpx_console), "--help"],
        cwd=case_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert cli_help.returncode == 0, cli_help.stderr
    assert "Semantic HWPX view/query/atomic-edit interface" in cli_help.stdout
    assert all(
        command in cli_help.stdout
        for command in ("view", "query", "batch", "dump", "replay")
    )
    catalog_help = subprocess.run(
        [str(hwpx_console), "help"],
        cwd=case_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert catalog_help.returncode == 0, catalog_help.stderr
    assert "HWPX agent document interface v1" in catalog_help.stdout
    assert "document" in catalog_help.stdout
    assert "table" in catalog_help.stdout
