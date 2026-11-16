#!/usr/bin/env python3
"""Build clean artifacts and exercise canonical/compat install transitions.

This is intentionally an explicit release gate rather than a normal unit test:
it creates isolated virtual environments and may resolve public dependencies.
Pass the clean candidate core wheel produced by the core repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_coordinates import coordinates

_COORDINATES = coordinates()

# Phase-0 floors are frozen history, not train coordinates. They live in
# identity.json so this script states no version of its own.
PHASE0_LEGACY_VERSION = _COORDINATES.legacy_compatibility_version
PHASE0_CORE_VERSION = _COORDINATES.legacy_core_version

#: Token the embedded probe sources use in place of this train's version.
#:
#: The probes are Python source carried as strings, so before this token
#: existed each one restated the train version as a literal. Nine of them did,
#: and a probe left on the previous train produced the preserved failure tags
#: v6.3.0, v6.5.0, and v6.6.2. :func:`_probe` now substitutes the token from
#: identity.json, so a probe cannot fall behind the train.
TRAIN_VERSION_TOKEN = "@@TRAIN_VERSION@@"
TRAIN_VERSION = _COORDINATES.candidate.automation

#: Token for the base public module count the installed wheel must declare.
#:
#: The probe used to assert a literal ``176``. Adding one module moved it to
#: 177 and produced the preserved failure tag v6.3.0. The count is derived from
#: this repository's own manifest, so the probe still compares the *installed*
#: wheel against a source outside itself while nobody has to edit a number.
BASE_MODULE_COUNT_TOKEN = "@@BASE_PUBLIC_MODULE_COUNT@@"
BASE_PUBLIC_MODULE_COUNT = str(
    json.loads(
        (ROOT / "src" / "hwpx_automation" / "public-modules.json").read_text(
            encoding="utf-8"
        )
    )["basePublicModuleCount"]
)

_PROBE_SUBSTITUTIONS = {
    TRAIN_VERSION_TOKEN: TRAIN_VERSION,
    BASE_MODULE_COUNT_TOKEN: BASE_PUBLIC_MODULE_COUNT,
}
_SOURCE_AFFECTING_ENV = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
)


def _isolated_env(
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment that cannot resolve either source checkout."""

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
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_isolated_env(env),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({completed.returncode}): {rendered}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed


def _clean_copy(destination: Path) -> Path:
    return Path(
        shutil.copytree(
            ROOT,
            destination,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv*",
                ".clean-*",
                "__pycache__",
                "*.egg-info",
                "build",
                "dist",
            ),
        )
    )


def _venv_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv is not None:
        _run(
            [
                uv,
                "venv",
                "--seed",
                "--python",
                sys.executable,
                str(path),
            ],
            cwd=path.parent,
        )
    else:
        _run(
            [sys.executable, "-m", "venv", str(path)],
            cwd=path.parent,
        )
    return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _pip(python: Path, *arguments: str) -> None:
    _run(
        [str(python), "-m", "pip", *arguments],
        cwd=python.parent.parent,
    )


def _install_phase0_legacy(
    python: Path,
    *,
    legacy_version: str,
    core_version: str,
) -> None:
    """Install the rollback leg without allowing pip to choose a future core."""

    _pip(
        python,
        "install",
        f"python-hwpx=={core_version}",
        f"hwpx-mcp-server=={legacy_version}",
    )
    _pip(python, "check")


def _resolve_probe(script: str) -> str:
    """Substitute every declared token, failing closed on an unknown one."""

    resolved = script
    for token, value in _PROBE_SUBSTITUTIONS.items():
        resolved = resolved.replace(token, value)
    if "@@" in resolved:
        raise RuntimeError(
            "probe source carries an unsubstituted @@token@@; every derived "
            "value must be declared in _PROBE_SUBSTITUTIONS"
        )
    return resolved


def _probe(python: Path, script: str, *, cwd: Path) -> None:
    _run([str(python), "-c", _resolve_probe(script)], cwd=cwd)


def _console_path(python: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return python.parent / f"{name}{suffix}"


def _run_mcp_console(python: Path, name: str, *, cwd: Path) -> None:
    completed = subprocess.run(
        [str(_console_path(python, name))],
        cwd=cwd,
        env=_isolated_env(),
        input="",
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{name} failed to launch and exit on stdin EOF\n"
            f"{completed.stdout}\n{completed.stderr}"
        )


def _artifact(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {pattern!r} in {directory}, got {[p.name for p in matches]}"
        )
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_python_modules(path: Path) -> list[str]:
    modules: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            pure = PurePosixPath(member)
            if (
                pure.suffix != ".py"
                or not pure.parts
                or pure.parts[0] != "hwpx_mcp_server"
            ):
                continue
            parts = list(pure.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            if parts:
                modules.add(".".join(parts))
    return sorted(modules)


def _validate_phase0_legacy_wheel(
    path: Path,
    *,
    expected_version: str,
    expected_modules: list[str],
) -> dict[str, Any]:
    """Prove the public maintenance wheel is a cap-only legacy repair."""

    with zipfile.ZipFile(path) as archive:
        metadata_members = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_members) != 1:
            raise RuntimeError(
                "public legacy wheel must contain exactly one METADATA member"
            )
        metadata = BytesParser().parsebytes(archive.read(metadata_members[0]))

    if metadata.get("Name") != "hwpx-mcp-server":
        raise RuntimeError("public legacy wheel distribution identity drifted")
    if metadata.get("Version") != expected_version:
        raise RuntimeError(
            "public legacy wheel version does not match the Phase-0 pin"
        )

    requirements = metadata.get_all("Requires-Dist") or []
    parsed = [Requirement(item) for item in requirements]
    core_requirements = [
        item
        for item in parsed
        if canonicalize_name(item.name) == "python-hwpx"
    ]
    base_core_requirements = [
        item for item in core_requirements if item.marker is None
    ]
    if len(base_core_requirements) != 1:
        raise RuntimeError(
            "public legacy wheel must declare one unconditional python-hwpx bound"
        )
    expected_core_specifiers = frozenset(_COORDINATES.legacy_core_specifiers)
    unsafe_core_requirements = [
        item
        for item in core_requirements
        if frozenset(str(specifier) for specifier in item.specifier)
        != expected_core_specifiers
    ]
    if unsafe_core_requirements:
        # Declared order, not sorted: the message reads as the requirement is
        # written in identity.json.
        rendered = ",".join(_COORDINATES.legacy_core_specifiers)
        raise RuntimeError(
            "every public legacy python-hwpx requirement, including extras, "
            f"must require python-hwpx{rendered}"
        )

    modules = _wheel_python_modules(path)
    if modules != expected_modules:
        raise RuntimeError(
            "public Phase-0 wheel changed the frozen 5.1 module surface"
        )
    return {
        "filename": path.name,
        "sha256": _sha256(path),
        "coreRequirement": str(base_core_requirements[0]),
        "coreRequirements": [str(item) for item in core_requirements],
        "moduleCount": len(modules),
    }


def _build_artifacts(clean_source: Path, output: Path) -> dict[str, Path]:
    canonical_dir = output / "canonical"
    compat_dir = output / "compat"
    rebuilt_dir = output / "rebuilt"
    canonical_dir.mkdir(parents=True)
    compat_dir.mkdir(parents=True)
    rebuilt_dir.mkdir(parents=True)
    _run(
        [sys.executable, "-m", "build", "--outdir", str(canonical_dir)],
        cwd=clean_source,
    )
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(compat_dir),
            str(clean_source / "compat" / "hwpx-mcp-server"),
        ],
        cwd=clean_source,
    )
    canonical_sdist = _artifact(canonical_dir, "python_hwpx_automation-*.tar.gz")
    extracted_root = output / "sdist-source"
    shutil.unpack_archive(canonical_sdist, extracted_root)
    extracted_sources = [path for path in extracted_root.iterdir() if path.is_dir()]
    if len(extracted_sources) != 1:
        raise RuntimeError(
            f"expected one source directory in sdist, got {extracted_sources!r}"
        )
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(rebuilt_dir),
            str(extracted_sources[0]),
        ],
        cwd=output,
    )
    return {
        "canonical_wheel": _artifact(
            canonical_dir, "python_hwpx_automation-*.whl"
        ),
        "canonical_sdist": canonical_sdist,
        "rebuilt_wheel": _artifact(
            rebuilt_dir, "python_hwpx_automation-*.whl"
        ),
        "compat_wheel": _artifact(compat_dir, "hwpx_mcp_server-*.whl"),
        "compat_sdist": _artifact(compat_dir, "hwpx_mcp_server-*.tar.gz"),
    }


def _install_local(
    python: Path,
    *,
    core_wheel: Path,
    canonical_wheel: Path,
    compat_wheel: Path | None = None,
    mcp: bool,
) -> None:
    wheelhouse = canonical_wheel.parent.parent
    canonical_requirement = (
        f"{canonical_wheel}[mcp]" if mcp else str(canonical_wheel)
    )
    requirements = [str(core_wheel), canonical_requirement]
    if compat_wheel is not None:
        requirements = [str(core_wheel), str(compat_wheel)]
    _pip(
        python,
        "install",
        "--find-links",
        str(wheelhouse / "canonical"),
        *requirements,
    )
    _pip(python, "check")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-wheel", type=Path, required=True)
    parser.add_argument("--legacy-version", default=PHASE0_LEGACY_VERSION)
    parser.add_argument("--legacy-core-version", default=PHASE0_CORE_VERSION)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-public-upgrade",
        action="store_true",
        help=(
            "Skip the public legacy-to-current upgrade and full-stack "
            "rollback probes."
        ),
    )
    args = parser.parse_args(argv)
    core_wheel = args.core_wheel.expanduser().resolve()
    if not core_wheel.is_file():
        parser.error(f"core wheel does not exist: {core_wheel}")

    inventory = json.loads(
        (
            ROOT
            / "compat"
            / "hwpx-mcp-server"
            / "legacy-modules-5.1.0.json"
        ).read_text(encoding="utf-8")
    )
    if (
        args.legacy_version != PHASE0_LEGACY_VERSION
        or args.legacy_core_version != PHASE0_CORE_VERSION
    ):
        parser.error(
            "the release gate requires the exact Phase-0 pair "
            f"hwpx-mcp-server=={PHASE0_LEGACY_VERSION} and "
            f"python-hwpx=={PHASE0_CORE_VERSION}"
        )
    legacy_modules = inventory["modules"]
    inventory_digest = hashlib.sha256(
        ("\n".join(sorted(legacy_modules)) + "\n").encode()
    ).hexdigest()
    if (
        inventory["moduleCount"] != len(legacy_modules)
        or inventory["deepModuleCount"] != len(legacy_modules) - 1
        or inventory["sha256"] != inventory_digest
        or len(inventory.get("sourceWheelSha256", "")) != 64
        or legacy_modules != sorted(set(legacy_modules))
    ):
        raise RuntimeError("public 5.1 compatibility module inventory drifted")
    legacy_deep_modules = [
        name for name in legacy_modules if name != inventory["rootShim"]
    ]
    public_modules = json.loads(
        (
            ROOT
            / "src"
            / "hwpx_automation"
            / "public-modules.json"
        ).read_text(encoding="utf-8")
    )
    base_modules = public_modules["basePublicModules"]
    adapter_modules = [
        item["module"] for item in public_modules["mcpAdapterModules"]
    ]
    # LangChain/LlamaIndex adapters import only with their framework extra, so
    # the base probe below never imports them; they still count in the total.
    framework_modules = [
        item["module"] for item in public_modules["frameworkAdapterModules"]
    ]
    all_modules = sorted((*base_modules, *adapter_modules, *framework_modules))
    if (
        public_modules["basePublicModuleCount"] != len(base_modules)
        or public_modules["mcpAdapterModuleCount"] != len(adapter_modules)
        or public_modules["frameworkAdapterModuleCount"] != len(framework_modules)
        or public_modules["frameworkAdapterModuleSha256"]
        != hashlib.sha256(
            ("\n".join(sorted(framework_modules)) + "\n").encode()
        ).hexdigest()
        or public_modules["moduleCount"] != len(all_modules)
        or public_modules["basePublicModuleSha256"]
        != hashlib.sha256(
            ("\n".join(sorted(base_modules)) + "\n").encode()
        ).hexdigest()
        or public_modules["mcpAdapterModuleSha256"]
        != hashlib.sha256(
            ("\n".join(sorted(adapter_modules)) + "\n").encode()
        ).hexdigest()
        or public_modules["moduleSha256"]
        != hashlib.sha256(
            ("\n".join(all_modules) + "\n").encode()
        ).hexdigest()
    ):
        raise RuntimeError("canonical public-module manifest drifted")
    ambient_source_environment = [
        name for name in _SOURCE_AFFECTING_ENV if os.environ.get(name)
    ]

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="hwpx-automation-compat-") as raw:
        work = Path(raw)
        clean_source = _clean_copy(work / "source")
        artifacts = _build_artifacts(clean_source, work / "artifacts")
        probe_cwd = work / "installed-probes"
        probe_cwd.mkdir()

        base_python = _venv_python(work / "base")
        _install_local(
            base_python,
            core_wheel=core_wheel,
            canonical_wheel=artifacts["canonical_wheel"],
            mcp=False,
        )
        _probe(
            base_python,
            """
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import sys
from importlib.metadata import distribution, entry_points, metadata
from importlib.resources import files
from pathlib import Path
assert importlib.util.find_spec("mcp") is None
import hwpx_automation
import hwpx_automation.api
assert callable(hwpx_automation.create_document_from_plan)
assert files("hwpx_automation").joinpath("py.typed").is_file()
assert not any(name in os.environ for name in (
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"
))
identity = json.loads(
    files("hwpx_automation").joinpath("identity.json").read_text(encoding="utf-8")
)
assert identity["product"] == "python-hwpx-automation"
public_modules = json.loads(
    files("hwpx_automation").joinpath("public-modules.json").read_text(
        encoding="utf-8"
    )
)
base_modules = public_modules["basePublicModules"]
assert len(base_modules) == public_modules["basePublicModuleCount"] == @@BASE_PUBLIC_MODULE_COUNT@@
assert hashlib.sha256(
    ("\\n".join(sorted(base_modules)) + "\\n").encode()
).hexdigest() == public_modules["basePublicModuleSha256"]

class BlockMcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("mcp intentionally blocked", name=fullname)
        return None

sys.meta_path.insert(0, BlockMcp())
for module_name in base_modules:
    importlib.import_module(module_name)
assert not any(name == "mcp" or name.startswith("mcp.") for name in sys.modules)

canonical = distribution("python-hwpx-automation")
installed_root = Path(canonical.locate_file("")).resolve()
assert Path(hwpx_automation.__file__).resolve() == Path(
    canonical.locate_file("hwpx_automation/__init__.py")
).resolve()
for module_name in base_modules:
    module = sys.modules[module_name]
    module_file = getattr(module, "__file__", None)
    assert module_file is not None, module_name
    assert Path(module_file).resolve().is_relative_to(installed_root), (
        module_name,
        module_file,
        installed_root,
    )
requirements = metadata("python-hwpx-automation").get_all("Requires-Dist") or []
assert all(
    "extra ==" in requirement and "mcp" in requirement.split(";", 1)[-1]
    for requirement in requirements
    if requirement.casefold().startswith("mcp")
)
scripts = {
    item.name: item.value
    for item in entry_points(group="console_scripts")
    if item.name in {"hwpx", "hwpx-automation-mcp", "hwpx-mcp-server"}
}
assert scripts == {
    "hwpx": "hwpx_automation.office.agent.cli:main",
    "hwpx-automation-mcp": "hwpx_automation.mcp_cli:main",
}
""",
            cwd=probe_cwd,
        )
        missing_mcp = subprocess.run(
            [str(base_python), "-m", "hwpx_automation.mcp_cli", "--help"],
            cwd=probe_cwd,
            env=_isolated_env(),
            text=True,
            capture_output=True,
            check=False,
        )
        if missing_mcp.returncode != 2 or "python-hwpx-automation[mcp]" not in missing_mcp.stderr:
            raise RuntimeError("base MCP console did not fail with the install hint")
        results.append({"shape": "canonical-base", "status": "pass"})

        mcp_python = _venv_python(work / "mcp")
        _install_local(
            mcp_python,
            core_wheel=core_wheel,
            canonical_wheel=artifacts["canonical_wheel"],
            mcp=True,
        )
        _probe(
            mcp_python,
            """
import os
from importlib.metadata import distribution, version
from pathlib import Path
assert version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
import hwpx_automation.server
assert hwpx_automation.server.mcp.name == "python-hwpx-automation"
assert not any(name in os.environ for name in (
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"
))
canonical = distribution("python-hwpx-automation")
assert Path(hwpx_automation.server.__file__).resolve() == Path(
    canonical.locate_file("hwpx_automation/server.py")
).resolve()
""",
            cwd=probe_cwd,
        )
        _run_mcp_console(
            mcp_python,
            "hwpx-automation-mcp",
            cwd=probe_cwd,
        )
        results.append({"shape": "canonical-mcp", "status": "pass"})

        compat_python = _venv_python(work / "compat")
        _install_local(
            compat_python,
            core_wheel=core_wheel,
            canonical_wheel=artifacts["canonical_wheel"],
            compat_wheel=artifacts["compat_wheel"],
            mcp=True,
        )
        _probe(
            compat_python,
            """
import importlib
import os
import pickle
from importlib.metadata import distribution, version
from pathlib import Path
assert version("hwpx-mcp-server") == version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
import hwpx_automation
import hwpx_mcp_server.office.exam as old
import hwpx_automation.office.exam as new
assert old is new
assert old.ComposeResult is new.ComposeResult
import hwpx_mcp_server
assert hwpx_mcp_server.__version__ == version("hwpx-mcp-server") == "@@TRAIN_VERSION@@"
namespace = {}
exec("from hwpx_mcp_server import *", namespace)
assert namespace["__version__"] == "@@TRAIN_VERSION@@"
from importlib.metadata import entry_points
owners = {
    item.name: item.dist.name
    for item in entry_points(group="console_scripts")
    if item.name in {"hwpx", "hwpx-automation-mcp", "hwpx-mcp-server"}
}
assert owners == {
    "hwpx": "python-hwpx-automation",
    "hwpx-automation-mcp": "python-hwpx-automation",
    "hwpx-mcp-server": "hwpx-mcp-server",
}
assert not any(name in os.environ for name in (
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"
))
canonical = distribution("python-hwpx-automation")
compat = distribution("hwpx-mcp-server")
assert Path(hwpx_automation.__file__).resolve() == Path(
    canonical.locate_file("hwpx_automation/__init__.py")
).resolve()
assert Path(hwpx_mcp_server.__file__).resolve() == Path(
    compat.locate_file("hwpx_mcp_server/__init__.py")
).resolve()
value = old.ComposeResult("out.hwpx", False, None, None, True, 0, True, ())
assert isinstance(pickle.loads(pickle.dumps(value)), new.ComposeResult)
legacy_class = pickle.loads(
    b"chwpx_mcp_server.office.exam\\nComposeResult\\n."
)
legacy_error = pickle.loads(
    b"chwpx_mcp_server.office.exam\\nExamParseError\\n."
)
assert legacy_class is new.ComposeResult
assert legacy_error is new.ExamParseError
try:
    raise legacy_error(7, "legacy input", "persisted exception")
except new.ExamParseError:
    pass
legacy_modules = __LEGACY_DEEP_MODULES__
for old_name in legacy_modules:
    new_name = old_name.replace("hwpx_mcp_server", "hwpx_automation", 1)
    old_module = importlib.import_module(old_name)
    new_module = importlib.import_module(new_name)
    assert old_module is new_module, (old_name, new_name)
    assert Path(new_module.__file__).resolve().is_relative_to(
        Path(canonical.locate_file("")).resolve()
    ), (new_name, new_module.__file__)
""".replace("__LEGACY_DEEP_MODULES__", repr(legacy_deep_modules)),
            cwd=probe_cwd,
        )
        _run_mcp_console(
            compat_python,
            "hwpx-automation-mcp",
            cwd=probe_cwd,
        )
        _run_mcp_console(
            compat_python,
            "hwpx-mcp-server",
            cwd=probe_cwd,
        )
        _pip(compat_python, "uninstall", "-y", "hwpx-mcp-server")
        _probe(
            compat_python,
            """
from importlib.metadata import PackageNotFoundError, version
try:
    version("hwpx-mcp-server")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("compat metadata survived uninstall")
assert version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
import hwpx_automation
from pathlib import Path
import sys
scripts = Path(sys.executable).parent
suffix = ".exe" if sys.platform == "win32" else ""
assert (scripts / f"hwpx-automation-mcp{suffix}").is_file()
assert not (scripts / f"hwpx-mcp-server{suffix}").exists()
""",
            cwd=probe_cwd,
        )
        _run_mcp_console(
            compat_python,
            "hwpx-automation-mcp",
            cwd=probe_cwd,
        )
        results.append(
            {
                "shape": "coexist-and-compat-uninstall",
                "status": "pass",
            }
        )
        _pip(
            compat_python,
            "install",
            "--find-links",
            str(artifacts["canonical_wheel"].parent),
            str(artifacts["compat_wheel"]),
        )
        _pip(compat_python, "check")
        _probe(
            compat_python,
            """
from importlib.metadata import version
assert version("hwpx-mcp-server") == version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
import hwpx_mcp_server.office.exam as old
import hwpx_automation.office.exam as new
assert old is new
""",
            cwd=probe_cwd,
        )
        _run_mcp_console(
            compat_python,
            "hwpx-mcp-server",
            cwd=probe_cwd,
        )
        results.append(
            {
                "shape": "compat-remove-reinstall",
                "status": "pass",
            }
        )

        if not args.skip_public_upgrade:
            upgrade_python = _venv_python(work / "upgrade")
            public_wheelhouse = work / "public-legacy-wheel"
            public_wheelhouse.mkdir()
            _pip(
                upgrade_python,
                "download",
                "--no-deps",
                "--only-binary=:all:",
                "--dest",
                str(public_wheelhouse),
                f"hwpx-mcp-server=={args.legacy_version}",
            )
            public_legacy_wheel = _artifact(
                public_wheelhouse,
                "hwpx_mcp_server-*.whl",
            )
            public_legacy_receipt = _validate_phase0_legacy_wheel(
                public_legacy_wheel,
                expected_version=args.legacy_version,
                expected_modules=legacy_modules,
            )
            _install_phase0_legacy(
                upgrade_python,
                core_version=args.legacy_core_version,
                legacy_version=args.legacy_version,
            )
            _probe(
                upgrade_python,
                f"""
from importlib.metadata import version
assert version("python-hwpx") == "{args.legacy_core_version}"
assert version("hwpx-mcp-server") == "{args.legacy_version}"
import hwpx_mcp_server
""",
                cwd=probe_cwd,
            )
            _pip(
                upgrade_python,
                "install",
                "--upgrade",
                "--find-links",
                str(core_wheel.parent),
                "--find-links",
                str(artifacts["canonical_wheel"].parent),
                str(artifacts["compat_wheel"]),
            )
            _pip(upgrade_python, "check")
            _probe(
                upgrade_python,
                """
import importlib
import os
from importlib.metadata import distribution, entry_points, version
from pathlib import Path
import hwpx_automation
assert version("hwpx-mcp-server") == version("python-hwpx-automation") == "@@TRAIN_VERSION@@"
import hwpx_mcp_server.office.exam
canonical = distribution("python-hwpx-automation")
compat = distribution("hwpx-mcp-server")
canonical_files = {str(item) for item in canonical.files or ()}
compat_files = {str(item) for item in compat.files or ()}
assert any(item.startswith("hwpx_automation/") for item in canonical_files)
assert not any(item.startswith("hwpx_automation/") for item in compat_files)
assert any(item.startswith("hwpx_mcp_server/") for item in compat_files)
package_root = Path(hwpx_automation.__file__).resolve().parent
assert package_root.name == "hwpx_automation"
assert not any(name in os.environ for name in (
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"
))
assert Path(hwpx_automation.__file__).resolve() == Path(
    canonical.locate_file("hwpx_automation/__init__.py")
).resolve()
assert Path(__import__("hwpx_mcp_server").__file__).resolve() == Path(
    compat.locate_file("hwpx_mcp_server/__init__.py")
).resolve()
assert all((package_root / item.removeprefix("hwpx_automation/")).exists()
           for item in canonical_files if item.startswith("hwpx_automation/"))
owners = {
    item.name: item.dist.name
    for item in entry_points(group="console_scripts")
    if item.name in {"hwpx", "hwpx-automation-mcp", "hwpx-mcp-server"}
}
assert owners == {
    "hwpx": "python-hwpx-automation",
    "hwpx-automation-mcp": "python-hwpx-automation",
    "hwpx-mcp-server": "hwpx-mcp-server",
}
legacy_modules = __LEGACY_DEEP_MODULES__
for old_name in legacy_modules:
    new_name = old_name.replace("hwpx_mcp_server", "hwpx_automation", 1)
    old = importlib.import_module(old_name)
    new = importlib.import_module(new_name)
    assert old is new, (old_name, new_name)
import hwpx_mcp_server
assert hwpx_mcp_server.__version__ == version("hwpx-mcp-server") == "@@TRAIN_VERSION@@"
namespace = {}
exec("from hwpx_mcp_server import *", namespace)
assert namespace["__version__"] == "@@TRAIN_VERSION@@"
""".replace("__LEGACY_DEEP_MODULES__", repr(legacy_deep_modules)),
                cwd=probe_cwd,
            )
            task_help = _run(
                [str(_console_path(upgrade_python, "hwpx")), "--help"],
                cwd=probe_cwd,
            )
            if "usage:" not in task_help.stdout.casefold():
                raise RuntimeError("upgraded hwpx task console did not render help")
            _run_mcp_console(
                upgrade_python,
                "hwpx-automation-mcp",
                cwd=probe_cwd,
            )
            _run_mcp_console(
                upgrade_python,
                "hwpx-mcp-server",
                cwd=probe_cwd,
            )
            _pip(
                upgrade_python,
                "uninstall",
                "-y",
                "hwpx-mcp-server",
                "python-hwpx-automation",
                "python-hwpx",
            )
            _install_phase0_legacy(
                upgrade_python,
                core_version=args.legacy_core_version,
                legacy_version=args.legacy_version,
            )
            _probe(
                upgrade_python,
                f"""
from importlib.metadata import version
assert version("python-hwpx") == "{args.legacy_core_version}"
assert version("hwpx-mcp-server") == "{args.legacy_version}"
import hwpx_mcp_server
""",
                cwd=probe_cwd,
            )
            _run_mcp_console(
                upgrade_python,
                "hwpx-mcp-server",
                cwd=probe_cwd,
            )
            results.append(
                {
                    "shape": "ordinary-legacy-upgrade-and-full-stack-rollback",
                    "status": "pass",
                    "legacyVersion": args.legacy_version,
                    "legacyCoreVersion": args.legacy_core_version,
                    "legacyPublicWheel": public_legacy_receipt,
                    "moduleInventoryBaselineVersion": inventory["sourceVersion"],
                    "moduleInventorySourceWheelSha256": inventory[
                        "sourceWheelSha256"
                    ],
                    "legacyModuleCount": len(legacy_modules),
                    "legacyModuleInventorySha256": inventory_digest,
                }
            )

        receipt = {
            "schemaVersion": "python-hwpx-automation.compat-matrix/v1",
            "artifacts": {
                key: {
                    "filename": value.name,
                    "sha256": _sha256(value),
                }
                for key, value in artifacts.items()
            },
            "publicModuleBoundary": {
                "moduleCount": public_modules["moduleCount"],
                "moduleSha256": public_modules["moduleSha256"],
                "basePublicModuleCount": public_modules[
                    "basePublicModuleCount"
                ],
                "basePublicModuleSha256": public_modules[
                    "basePublicModuleSha256"
                ],
                "mcpAdapterModuleCount": public_modules[
                    "mcpAdapterModuleCount"
                ],
            },
            "sourceIsolation": {
                "removedEnvironmentVariables": list(_SOURCE_AFFECTING_ENV),
                "ambientVariablesDetected": ambient_source_environment,
                "installedProbeWorkingDirectory": "temporary-non-source",
                "distributionOriginAssertions": True,
            },
            "results": results,
        }
        if args.output is not None:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
