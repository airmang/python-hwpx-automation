# SPDX-License-Identifier: Apache-2.0
"""``cryptography`` is optional: only the encrypted workflow store needs it.

The base install no longer pulls ``cryptography`` (and not ``anyio`` either).
Importing the workflow package, its service and the workflow tool handlers
must work without it; constructing the store must say how to install it and
leave the disk untouched; a store written earlier stays readable once the
extra is installed again.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hwpx_automation.document_state import document_revision
from hwpx_automation.workflow import WorkFamily, WorkOrder, WorkflowStore
from hwpx_automation.workflow.store import WorkflowStoreDependencyError


ROOT = Path(__file__).resolve().parents[1]

_BLOCK_CRYPTOGRAPHY = textwrap.dedent(
    """
    import importlib.abc
    import sys

    class BlockCryptography(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "cryptography" or fullname.startswith("cryptography."):
                raise ModuleNotFoundError("cryptography intentionally blocked", name=fullname)
            return None

    sys.meta_path.insert(0, BlockCryptography())
    for name in [m for m in sys.modules if m == "cryptography" or m.startswith("cryptography.")]:
        del sys.modules[name]
    """
)


def _run_without_cryptography(body: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")])
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_CRYPTOGRAPHY + textwrap.dedent(body)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_base_pyproject_does_not_require_cryptography_or_anyio() -> None:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - python < 3.11
        import tomli as tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    base = [item.split(">")[0].split("=")[0].split(";")[0].strip() for item in project["dependencies"]]
    assert "cryptography" not in base
    assert "anyio" not in base
    extras = project["optional-dependencies"]
    assert "cryptography>=42.0" in extras["workflow"]
    assert "cryptography>=42.0" in extras["mcp"]


def test_workflow_modules_import_without_cryptography() -> None:
    completed = _run_without_cryptography(
        """
        import hwpx_automation.workflow
        import hwpx_automation.workflow.store
        import hwpx_automation.workflow.service
        import hwpx_automation.workflow.dispatcher
        import hwpx_automation.handlers.workflow
        loaded = [m for m in sys.modules if m == "cryptography" or m.startswith("cryptography.")]
        assert not loaded, loaded
        print("ok")
        """
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_store_without_cryptography_names_the_extra_and_writes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "state" / "workflow.sqlite3"
    completed = _run_without_cryptography(
        """
        import os
        from hwpx_automation.workflow import WorkflowStore
        from hwpx_automation.workflow.store import WorkflowStoreDependencyError
        try:
            WorkflowStore(os.environ["DB"])
        except WorkflowStoreDependencyError as exc:
            assert isinstance(exc, ImportError)
            print(exc)
        else:
            raise SystemExit("store opened without cryptography")
        """,
        extra_env={"DB": str(database)},
    )
    assert completed.returncode == 0, completed.stderr
    assert "python-hwpx-automation[workflow]" in completed.stdout
    assert "cryptography" in completed.stdout
    assert not database.parent.exists()


def test_previously_encrypted_store_reads_back_after_reopen(tmp_path: Path) -> None:
    source = tmp_path / "source.hwpx"
    source.write_bytes(b"original")
    database = tmp_path / "workflow.sqlite3"
    order = WorkOrder(
        family=WorkFamily.TRANSACTIONAL_EDIT,
        source_path=str(source),
        output_path=str(tmp_path / "copy.hwpx"),
        expected_revision=document_revision(source),
        idempotency_key="optional-crypto-roundtrip",
    )
    record, created = WorkflowStore(database).create(order)
    assert created
    raw = database.read_bytes()
    assert b"optional-crypto-roundtrip" not in raw  # still encrypted at rest

    # A refused open (no cryptography) must not damage the existing rows.
    refused = _run_without_cryptography(
        """
        import os
        from hwpx_automation.workflow import WorkflowStore
        from hwpx_automation.workflow.store import WorkflowStoreDependencyError
        try:
            WorkflowStore(os.environ["DB"])
        except WorkflowStoreDependencyError:
            print("refused")
        """,
        extra_env={"DB": str(database)},
    )
    assert refused.returncode == 0, refused.stderr
    assert refused.stdout.strip() == "refused"

    reopened = WorkflowStore(database).get(record.workflow_id)
    assert reopened.work_order.fingerprint() == order.fingerprint()
    assert reopened.state == record.state


def test_dependency_error_is_importerror() -> None:
    assert issubclass(WorkflowStoreDependencyError, ImportError)


@pytest.mark.parametrize("module", ["hwpx_automation", "hwpx_automation.api"])
def test_public_entry_points_do_not_load_cryptography_or_anyio(module: str) -> None:
    completed = _run_without_cryptography(
        f"""
        import {module}
        heavy = sorted(
            m for m in sys.modules
            if m.split(".")[0] in {{"cryptography", "anyio"}}
        )
        assert not heavy, heavy
        print("ok")
        """
    )
    assert completed.returncode == 0, completed.stderr
