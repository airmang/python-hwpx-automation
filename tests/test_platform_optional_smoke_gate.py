from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_platform_optional_smoke.py"
SPEC = importlib.util.spec_from_file_location("platform_optional_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_platform_optional_smoke_help_is_dependency_free() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--core-repo" in completed.stdout
    assert "--core-wheel" in completed.stdout


def test_native_probe_executes_owned_imaging_stack_without_gui() -> None:
    probe = smoke._probe_script()
    assert "extract_word_boxes" in probe
    assert "render_pdf_to_images" in probe
    assert "np.asarray" in probe
    assert "fitz-pillow-numpy-passed" in probe
    assert "MacHancomOracle" not in probe
    assert smoke._PROBE_RECEIPT_PREFIX in probe


def test_probe_receipt_parser_ignores_unowned_stdout() -> None:
    receipt = {"oracleBackend": "NullOracle", "renderChecked": False}
    completed = subprocess.CompletedProcess(
        args=["python", "-c", "probe"],
        returncode=0,
        stdout=(
            "optional dependency diagnostic\n"
            f"{smoke._PROBE_RECEIPT_PREFIX}{json.dumps(receipt)}\n"
        ),
        stderr="native library diagnostic\n",
    )

    assert smoke._parse_probe_receipt(completed) == receipt


@pytest.mark.parametrize(
    "stdout, message",
    [
        ("", "got 0"),
        (
            f"{smoke._PROBE_RECEIPT_PREFIX}not-json\n",
            "malformed receipt",
        ),
        (
            "".join(
                [
                    f"{smoke._PROBE_RECEIPT_PREFIX}{{}}\n",
                    f"{smoke._PROBE_RECEIPT_PREFIX}{{}}\n",
                ]
            ),
            "got 2",
        ),
    ],
)
def test_probe_receipt_parser_fails_closed(
    stdout: str,
    message: str,
) -> None:
    completed = subprocess.CompletedProcess(
        args=["python", "-c", "probe"],
        returncode=0,
        stdout=stdout,
        stderr="captured probe stderr",
    )

    with pytest.raises(RuntimeError, match=message) as caught:
        smoke._parse_probe_receipt(completed)
    assert "captured probe stderr" in str(caught.value)


def test_platform_optional_smoke_sanitizes_source_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in smoke._SOURCE_AFFECTING_ENV:
        monkeypatch.setenv(name, f"poison-{name}")
    isolated = smoke._isolated_env()
    assert all(name not in isolated for name in smoke._SOURCE_AFFECTING_ENV)
    assert isolated["PYTHONNOUSERSITE"] == "1"
    assert smoke.MINIMUM_PYTHON == (3, 10)
    assert "VIRTUAL_ENV" in smoke._SOURCE_AFFECTING_ENV


def test_mypy_310_target_does_not_parse_optional_dependency_stubs() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]
    assert mypy["python_version"] == "3.10"
    assert mypy["no_site_packages"] is True
    assert mypy["follow_imports"] == "skip"
    assert mypy["ignore_missing_imports"] is True


def test_windows_workflow_uses_platform_neutral_commands() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "tests.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["platform-oracle-smoke"]
    assert job["strategy"]["matrix"]["os"] == [
        "macos-latest",
        "windows-latest",
    ]
    smoke_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build and smoke clean canonical oracle wheel"
    )
    commands = [
        line.strip()
        for line in smoke_step["run"].splitlines()
        if line.strip()
    ]
    assert commands == [
        'python -m pip install "build>=1.2"',
        (
            "python scripts/check_platform_optional_smoke.py "
            "--core-repo ../python-hwpx"
        ),
    ]
    assert all(not command.endswith("\\") for command in commands)
