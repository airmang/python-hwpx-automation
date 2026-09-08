from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "hwpx_automation" / "public-modules.json"


def _digest(modules: list[str]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(modules)) + "\n").encode()
    ).hexdigest()


def _source_modules() -> list[str]:
    package = ROOT / "src" / "hwpx_automation"
    modules: list[str] = []
    for path in package.rglob("*.py"):
        relative = path.relative_to(ROOT / "src").with_suffix("")
        parts = relative.parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return sorted(modules)


def test_public_module_manifest_freezes_the_complete_shipped_source_surface() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    base_modules = manifest["basePublicModules"]
    adapter_modules = [
        item["module"] for item in manifest["mcpAdapterModules"]
    ]
    all_modules = sorted((*base_modules, *adapter_modules))

    assert base_modules == sorted(set(base_modules))
    assert adapter_modules == sorted(set(adapter_modules))
    assert set(base_modules).isdisjoint(adapter_modules)
    assert manifest["basePublicModuleCount"] == len(base_modules) == 177
    assert manifest["mcpAdapterModuleCount"] == len(adapter_modules) == 5
    assert manifest["moduleCount"] == len(all_modules) == 182
    assert manifest["basePublicModuleSha256"] == _digest(base_modules)
    assert manifest["mcpAdapterModuleSha256"] == _digest(adapter_modules)
    assert manifest["moduleSha256"] == _digest(all_modules)
    assert all_modules == _source_modules()
    assert adapter_modules == [
        "hwpx_automation.fastmcp_adapter",
        "hwpx_automation.handlers.quality_render",
        "hwpx_automation.runtime",
        "hwpx_automation.server",
        "hwpx_automation.tool_bindings",
    ]


def test_base_automation_import_graph_does_not_load_mcp() -> None:
    script = r"""
import hashlib
import importlib
import importlib.abc
import json
import sys
from importlib.resources import files

class BlockMcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("mcp intentionally blocked", name=fullname)
        return None

sys.meta_path.insert(0, BlockMcp())
manifest = json.loads(
    files("hwpx_automation").joinpath("public-modules.json").read_text(
        encoding="utf-8"
    )
)
modules = manifest["basePublicModules"]
digest = hashlib.sha256(
    ("\n".join(sorted(modules)) + "\n").encode()
).hexdigest()
assert len(modules) == manifest["basePublicModuleCount"] == 177
assert digest == manifest["basePublicModuleSha256"]
for module in modules:
    importlib.import_module(module)
loaded = sorted(
    name for name in sys.modules if name == "mcp" or name.startswith("mcp.")
)
assert not loaded, loaded
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_optional_mcp_console_fails_with_install_hint_when_sdk_is_blocked() -> None:
    script = r"""
import importlib.abc
import sys

class BlockMcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("mcp intentionally blocked", name=fullname)
        return None

sys.meta_path.insert(0, BlockMcp())
from hwpx_automation.mcp_cli import main
main(["--help"])
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), env.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "python-hwpx-automation[mcp]" in completed.stderr
    assert "Traceback" not in completed.stderr
