#!/usr/bin/env python3
"""Exercise the minimum-Python clean-wheel boundary on a native OS runner.

This gate is intentionally smaller than the Linux test matrix.  It builds the
candidate wheels, installs only the canonical ``[oracle]`` runtime into a fresh
virtual environment, and proves two fail-closed optional boundaries:

* structural-only oracle mode returns a labelled, unverified ``VisualReport``;
* the MCP console exits with an actionable extra-install hint when ``mcp`` is
  absent.

The script never launches Hancom or any other GUI application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = (3, 10)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_coordinates import coordinates as _release_coordinates

# Train coordinates are derived from identity.json, never restated here. A
# stale wheel-filename pin in this very file produced the preserved failure
# tag v6.6.3; the probe version pins were the same disease one train wide.
_COORDINATES = _release_coordinates()
_CORE_VERSION = _COORDINATES.candidate.core
_PROBE_SUBSTITUTIONS = {
    "@@CANDIDATE_CORE@@": _CORE_VERSION,
    "@@TRAIN_VERSION@@": _COORDINATES.candidate.automation,
}
_SOURCE_AFFECTING_ENV = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
)
_PROBE_RECEIPT_PREFIX = "HWPX_PLATFORM_SMOKE_RECEIPT="


def _isolated_env(
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment that cannot import either source checkout."""

    env = os.environ.copy()
    if overrides is not None:
        env.update(overrides)
    for name in _SOURCE_AFFECTING_ENV:
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_isolated_env(env),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed


def _clean_copy(source: Path, destination: Path) -> Path:
    """Copy a worktree without VCS/build residue before wheel construction."""

    return Path(
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".tox",
                ".nox",
                ".venv*",
                ".clean-*",
                ".compat-*",
                ".minimum-*",
                "__pycache__",
                "*.egg-info",
                "build",
                "dist",
            ),
        )
    )


def _artifact(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {pattern!r} in {directory}, got "
            f"{[path.name for path in matches]}"
        )
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_wheel(source: Path, output: Path, pattern: str) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(output),
            str(source),
        ],
        cwd=source,
    )
    return _artifact(output, pattern)


def _venv_python(path: Path, *, cwd: Path) -> Path:
    _run([sys.executable, "-m", "venv", str(path)], cwd=cwd)
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return path / suffix


def _resolve_probe(script: str) -> str:
    """Substitute every declared token, failing closed on an unknown one."""

    resolved = script
    for token, value in _PROBE_SUBSTITUTIONS.items():
        resolved = resolved.replace(token, value)
    if "@@" in resolved:
        raise SystemExit(
            "probe source carries an unsubstituted @@token@@; declare it in "
            "_PROBE_SUBSTITUTIONS"
        )
    return resolved


def _parse_probe_receipt(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    """Extract the probe receipt without trusting third-party stdout silence."""

    receipts = [
        line.removeprefix(_PROBE_RECEIPT_PREFIX)
        for line in completed.stdout.splitlines()
        if line.startswith(_PROBE_RECEIPT_PREFIX)
    ]
    if len(receipts) != 1:
        raise RuntimeError(
            "probe must emit exactly one prefixed receipt; "
            f"got {len(receipts)}\n"
            f"stdout={completed.stdout!r}\n"
            f"stderr={completed.stderr!r}"
        )
    try:
        receipt = json.loads(receipts[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "probe emitted a malformed receipt\n"
            f"stdout={completed.stdout!r}\n"
            f"stderr={completed.stderr!r}"
        ) from exc
    if not isinstance(receipt, dict):
        raise TypeError(
            "probe receipt must be a JSON object\n"
            f"stdout={completed.stdout!r}\n"
            f"stderr={completed.stderr!r}"
        )
    return receipt


def _probe_script() -> str:
    return r"""
import importlib.util
import json
import os
import platform
import sys
import tempfile
from importlib.metadata import distribution, version
from pathlib import Path

assert sys.version_info[:2] == (3, 10), sys.version
assert version("python-hwpx") == "@@CANDIDATE_CORE@@"
assert version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
assert importlib.util.find_spec("mcp") is None
assert importlib.util.find_spec("fitz") is not None
assert importlib.util.find_spec("PIL") is not None
assert importlib.util.find_spec("numpy") is not None

import hwpx_automation
import hwpx_automation.api
import fitz
import numpy as np
from hwpx_automation.office.form_fill.fit.wordbox import extract_word_boxes
from hwpx_automation.office.rendering.diff import render_pdf_to_images
import hwpx_automation.ops_services.preview_export
from hwpx.quality.rendering import VisualReport
from hwpx_automation.office.rendering.oracle import (
    NullOracle,
    resolve_oracle,
    structural_only,
    visual_check,
)

prefix = Path(sys.prefix).resolve()
module_origin = Path(hwpx_automation.__file__).resolve()
distribution_root = Path(
    distribution("python-hwpx-automation").locate_file("")
).resolve()
assert module_origin.is_relative_to(prefix), (module_origin, prefix)
assert distribution_root.is_relative_to(prefix), (distribution_root, prefix)
assert structural_only() is True

with tempfile.TemporaryDirectory(prefix="hwpx-native-imaging-") as temporary:
    pdf_path = Path(temporary) / "probe.pdf"
    document = fitz.open()
    page = document.new_page(width=240, height=160)
    page.insert_text((24, 72), "automation smoke")
    document.save(pdf_path)
    document.close()
    boxes = extract_word_boxes(str(pdf_path))
    assert any(box.text == "automation" for box in boxes), boxes
    images = render_pdf_to_images(pdf_path, dpi=72)
    assert len(images) == 1 and images[0].mode == "RGB"
    pixels = np.asarray(images[0])
    assert pixels.ndim == 3 and pixels.shape[2] == 3

oracle = resolve_oracle()
assert type(oracle) is NullOracle
assert oracle.available() is False
report = visual_check(
    "missing-before.hwpx",
    "missing-after.hwpx",
    oracle=oracle,
)
assert isinstance(report, VisualReport)
assert report.ok is True
assert report.render_checked is False
assert report.errors == []
assert report.warnings
assert "RENDER_ORACLE_UNAVAILABLE" in report.warnings[0]
assert "unverified" in report.warnings[0]

print("HWPX_PLATFORM_SMOKE_RECEIPT=" + json.dumps(
    {
        "python": platform.python_version(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "moduleOriginInsideVenv": True,
        "mcpInstalled": False,
        "nativeImagingSmoke": "fitz-pillow-numpy-passed",
        "oracleBackend": type(oracle).__name__,
        "oracleAvailable": oracle.available(),
        "renderChecked": report.render_checked,
        "renderWarning": report.warnings[0],
    },
    sort_keys=True,
), flush=True)
"""


def _expected_failure(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected_code: int,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_isolated_env(env),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != expected_code:
        raise RuntimeError(
            f"expected exit {expected_code}, got {completed.returncode}: "
            f"{' '.join(command)}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    core = parser.add_mutually_exclusive_group(required=True)
    core.add_argument(
        "--core-repo",
        type=Path,
        help="python-hwpx 5.0 source checkout to copy and build",
    )
    core.add_argument(
        "--core-wheel",
        type=Path,
        help="prebuilt python-hwpx 5.0 wheel",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON receipt path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if sys.version_info[:2] != MINIMUM_PYTHON:
        raise SystemExit(
            "platform optional smoke must run on the minimum supported "
            f"Python 3.10, got {platform.python_version()}"
        )
    detected_source_environment = sorted(
        name for name in _SOURCE_AFFECTING_ENV if name in os.environ
    )

    with tempfile.TemporaryDirectory(prefix="hwpx-platform-smoke-") as temporary:
        work = Path(temporary)
        wheelhouse = work / "wheelhouse"
        clean_automation = _clean_copy(ROOT, work / "automation-source")
        automation_wheel = _build_wheel(
            clean_automation,
            wheelhouse / "automation",
            "python_hwpx_automation-*.whl",
        )

        if args.core_repo is not None:
            core_repo = args.core_repo.expanduser().resolve()
            if not (core_repo / "pyproject.toml").is_file():
                raise SystemExit(f"invalid python-hwpx checkout: {core_repo}")
            clean_core = _clean_copy(core_repo, work / "core-source")
            core_wheel = _build_wheel(
                clean_core,
                wheelhouse / "core",
                f"python_hwpx-{_CORE_VERSION}-*.whl",
            )
        else:
            assert args.core_wheel is not None
            core_wheel = args.core_wheel.expanduser().resolve()
            if (
                not core_wheel.is_file()
                or not core_wheel.name.startswith(f"python_hwpx-{_CORE_VERSION}-")
                or core_wheel.suffix != ".whl"
            ):
                raise SystemExit(f"invalid python-hwpx {_CORE_VERSION} wheel: {core_wheel}")

        venv_python = _venv_python(work / "venv", cwd=work)
        _run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                str(core_wheel),
                f"{automation_wheel}[oracle]",
            ],
            cwd=work,
            timeout=600,
        )
        _run(
            [str(venv_python), "-m", "pip", "check"],
            cwd=work,
        )

        probe_cwd = work / "outside-source"
        probe_cwd.mkdir()
        probe_env = {"HWPX_ORACLE_STRUCTURAL_ONLY": "1"}
        probe = _run(
            [str(venv_python), "-c", _resolve_probe(_probe_script())],
            cwd=probe_cwd,
            env=probe_env,
        )
        probe_receipt = _parse_probe_receipt(probe)

        task_cli = _run(
            [str(venv_python), "-m", "hwpx_automation", "--help"],
            cwd=probe_cwd,
            env=probe_env,
        )
        if "usage:" not in (task_cli.stdout + task_cli.stderr).casefold():
            raise RuntimeError("task CLI --help did not emit usage text")

        mcp_cli = _expected_failure(
            [str(venv_python), "-m", "hwpx_automation.mcp_cli", "--help"],
            cwd=probe_cwd,
            env=probe_env,
            expected_code=2,
        )
        mcp_output = mcp_cli.stdout + mcp_cli.stderr
        if "python-hwpx-automation[mcp]" not in mcp_output:
            raise RuntimeError("MCP failure omitted the canonical install hint")
        if "Traceback" in mcp_output:
            raise RuntimeError("MCP optional-dependency failure leaked a traceback")

        receipt: dict[str, Any] = {
            "schemaVersion": "python-hwpx-automation-platform-smoke.v1",
            "status": "passed",
            "runner": {
                "platform": sys.platform,
                "platformDescription": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "artifacts": {
                "python-hwpx": {
                    "filename": core_wheel.name,
                    "sha256": _sha256(core_wheel),
                },
                "python-hwpx-automation": {
                    "filename": automation_wheel.name,
                    "sha256": _sha256(automation_wheel),
                },
            },
            "checks": {
                **probe_receipt,
                "taskCliHelp": "passed",
                "mcpWithoutExtra": "exit-2-actionable-no-traceback",
                "sourceEnvironmentDetected": detected_source_environment,
                "sourceEnvironmentSanitized": list(_SOURCE_AFFECTING_ENV),
            },
        }
        rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        if args.output is not None:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
