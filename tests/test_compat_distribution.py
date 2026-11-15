from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
COMPAT_ROOT = ROOT / "compat" / "hwpx-mcp-server"
LEGACY_INVENTORY = COMPAT_ROOT / "legacy-modules-5.1.0.json"


@pytest.fixture(scope="module")
def compat_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path]:
    output = tmp_path_factory.mktemp("compat-artifacts")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(output),
            str(COMPAT_ROOT),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return next(output.glob("*.whl")), next(output.glob("*.tar.gz"))


def _compat_subprocess(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(COMPAT_ROOT / "src"), str(ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _compat_module(
    module: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(COMPAT_ROOT / "src"), str(ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_compat_metadata_exactly_delegates_to_canonical_distribution() -> None:
    data = tomllib.loads((COMPAT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    # The delegation target is whatever version the canonical package IS - a
    # literal here would freeze the shell one train behind the canonical
    # pyproject, which is the exact skew this test exists to rule out.
    canonical = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    canonical_version = canonical["project"]["version"]
    assert project["version"] == canonical_version
    assert project["name"] == "hwpx-mcp-server"
    assert project["dependencies"] == [
        f"python-hwpx-automation[mcp]=={canonical_version}"
    ]
    assert project["scripts"] == {
        "hwpx-mcp-server": "hwpx_automation.mcp_cli:main"
    }
    for extra in ("mcp", "workflow", "hwp", "http", "ingest", "oracle", "vision"):
        assert project["optional-dependencies"][extra] == [
            f"python-hwpx-automation[{extra}]=={canonical_version}"
        ]


def test_compat_license_and_notice_are_canonical_copies() -> None:
    assert (COMPAT_ROOT / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (COMPAT_ROOT / "NOTICE").read_bytes() == (ROOT / "NOTICE").read_bytes()


def test_public_5_1_module_inventory_is_frozen_and_complete() -> None:
    inventory = json.loads(LEGACY_INVENTORY.read_text(encoding="utf-8"))
    modules = inventory["modules"]
    digest = hashlib.sha256(
        ("\n".join(sorted(modules)) + "\n").encode()
    ).hexdigest()
    assert inventory["sourceVersion"] == "5.1.0"
    assert inventory["sourceWheelSha256"] == (
        "d5338e6cb666cfa6cbecf713a7ac6cfd7fc0375e0d358af0d564be5dd4eb367c"
    )
    assert inventory["moduleCount"] == len(modules) == 89
    assert inventory["deepModuleCount"] == len(modules) - 1 == 88
    assert modules == sorted(set(modules))
    assert digest == inventory["sha256"]


def test_compat_artifacts_ship_legal_files_and_only_the_import_shim(
    compat_artifacts: tuple[Path, Path],
) -> None:
    wheel, sdist = compat_artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        python_members = [name for name in names if name.endswith(".py")]
        assert python_members == ["hwpx_mcp_server/__init__.py"]
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        assert any(name.endswith(".dist-info/licenses/NOTICE") for name in names)

    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        assert any(name.endswith("/LICENSE") for name in names)
        assert any(name.endswith("/NOTICE") for name in names)


def test_legacy_deep_import_preserves_module_and_class_identity() -> None:
    completed = _compat_subprocess(
        r"""
import importlib
import pickle
import warnings
warnings.simplefilter("always", DeprecationWarning)
old = importlib.import_module("hwpx_mcp_server.office.exam")
new = importlib.import_module("hwpx_automation.office.exam")
assert old is new
assert old.ComposeResult is new.ComposeResult
assert old.ExamParseError is new.ExamParseError
import hwpx_mcp_server
assert hwpx_mcp_server.__version__ == __import__("hwpx_automation").__version__
namespace = {}
exec("from hwpx_mcp_server import *", namespace)
assert namespace["__version__"] == hwpx_mcp_server.__version__
value = old.ComposeResult("out.hwpx", False, None, None, True, 0, True, ())
round_tripped = pickle.loads(pickle.dumps(value))
assert isinstance(round_tripped, new.ComposeResult)
legacy_class = pickle.loads(
    b"chwpx_mcp_server.office.exam\nComposeResult\n."
)
legacy_error = pickle.loads(
    b"chwpx_mcp_server.office.exam\nExamParseError\n."
)
assert legacy_class is new.ComposeResult
assert legacy_error is new.ExamParseError
try:
    raise legacy_error(7, "legacy input", "persisted exception")
except new.ExamParseError:
    pass
from importlib.resources import files
assert files("hwpx_automation").joinpath("identity.json").is_file()
assert not files("hwpx_mcp_server").joinpath("identity.json").is_file()
"""
    )
    assert completed.returncode == 0, completed.stderr
    assert "DeprecationWarning" in completed.stderr


def test_legacy_resource_package_preserves_canonical_import_metadata() -> None:
    completed = _compat_subprocess(
        r"""
import importlib
import json
from importlib.resources import files

canonical = importlib.import_module("hwpx_automation.office.house_style")
snapshot = {
    "__name__": canonical.__name__,
    "__spec__": canonical.__spec__,
    "__loader__": canonical.__loader__,
    "__package__": canonical.__package__,
    "__path__": canonical.__path__,
}
legacy = importlib.import_module("hwpx_mcp_server.office.house_style")
assert legacy is canonical
assert canonical.__name__ == snapshot["__name__"]
assert canonical.__spec__ is snapshot["__spec__"]
assert canonical.__loader__ is snapshot["__loader__"]
assert canonical.__package__ == snapshot["__package__"]
assert canonical.__path__ is snapshot["__path__"]
bank = files(legacy).joinpath("data").joinpath("bank.json")
assert bank.is_file()
payload = json.loads(bank.read_text(encoding="utf-8"))
assert payload["schemaVersion"] == canonical.BANK_SCHEMA_VERSION
legacy_bank = (
    files("hwpx_mcp_server.office.house_style")
    .joinpath("data")
    .joinpath("bank.json")
)
assert legacy_bank.read_bytes() == bank.read_bytes()
assert canonical.load_bank().schema_version == canonical.BANK_SCHEMA_VERSION
"""
    )
    assert completed.returncode == 0, completed.stderr


def test_python_m_legacy_package_delegates_to_the_canonical_task_cli() -> None:
    completed = _compat_module("hwpx_mcp_server", "--help")
    assert completed.returncode == 0, completed.stderr
    assert "usage: hwpx" in completed.stdout


def test_python_m_legacy_deep_module_uses_alias_loader_code() -> None:
    completed = _compat_module("hwpx_mcp_server.server", "--help")
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.casefold()
    assert "_AliasLoader" not in completed.stderr


def test_every_public_5_1_deep_module_aliases_the_canonical_object() -> None:
    completed = _compat_subprocess(
        r"""
import importlib
import json
from pathlib import Path
inventory = json.loads(
    Path("compat/hwpx-mcp-server/legacy-modules-5.1.0.json").read_text(
        encoding="utf-8"
    )
)
for old_name in inventory["modules"]:
    if old_name == inventory["rootShim"]:
        continue
    new_name = old_name.replace("hwpx_mcp_server", "hwpx_automation", 1)
    old = importlib.import_module(old_name)
    new = importlib.import_module(new_name)
    assert old is new, (old_name, new_name)
"""
    )
    assert completed.returncode == 0, completed.stderr


def test_compat_finder_does_not_swallow_internal_import_error() -> None:
    completed = _compat_subprocess(
        r"""
import hwpx_mcp_server
finder = next(
    item for item in __import__("sys").meta_path
    if item.__class__.__name__ == "_AliasFinder"
)
original = hwpx_mcp_server.importlib.import_module
def broken(name):
    if name == "hwpx_automation.synthetic":
        raise ModuleNotFoundError("missing runtime dependency", name="internal_dependency")
    return original(name)
hwpx_mcp_server.importlib.import_module = broken
try:
    finder.find_spec("hwpx_mcp_server.synthetic")
except ModuleNotFoundError as exc:
    assert exc.name == "internal_dependency"
else:
    raise AssertionError("internal ModuleNotFoundError was swallowed")
"""
    )
    assert completed.returncode == 0, completed.stderr


def test_missing_legacy_target_remains_a_normal_module_not_found() -> None:
    completed = _compat_subprocess(
        r"""
import importlib
import hwpx_mcp_server
try:
    importlib.import_module("hwpx_mcp_server.module_that_does_not_exist")
except ModuleNotFoundError as exc:
    assert exc.name == "hwpx_mcp_server.module_that_does_not_exist"
else:
    raise AssertionError("missing compatibility target unexpectedly imported")
"""
    )
    assert completed.returncode == 0, completed.stderr
