# SPDX-License-Identifier: Apache-2.0
"""The light conversion layer stays light.

python-hwpx 7.0 moves its conversion and guessing features (Markdown in and
out, ingest, loaders, label-addressed cells, choice fields, mail merge,
preview, format rules) into this package. People who only want "Markdown from
Python" will then install it, so the receiving modules must import without
the heavy or adapter-only parts of the package:

* ``pydantic`` and ``cryptography`` (install weight and import time),
* ``mcp`` (optional adapter),
* ``hwpx_automation.errors`` and ``hwpx_automation.office`` (the task/MCP
  service layer, which itself pulls pydantic).

The modules do not exist yet. Each listed module is checked as soon as it
appears in ``src``; until then it is skipped, so the rule is in place before the
move lands. Packages are checked with every submodule that imports; a
submodule that needs an optional third-party library (langchain, markitdown…)
that is not installed is reported as skipped, not as a pass.

They must also not be reached through the top-level ``hwpx_automation``
``__getattr__`` facade, which loads ``hwpx_automation.api`` (pydantic).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "hwpx_automation"

LIGHT_LAYER_MODULES = (
    "hwpx_automation.markdown",
    "hwpx_automation.ingest",
    "hwpx_automation.integrations",
    "hwpx_automation.forms",
    "hwpx_automation.mail_merge",
    "hwpx_automation.preview",
    "hwpx_automation.format_rules",
)

# Third-party distributions (top-level import names) and package-internal
# prefixes a light module must not load.
FORBIDDEN_TOP_LEVEL = ("pydantic", "pydantic_core", "cryptography", "mcp")
FORBIDDEN_INTERNAL = ("hwpx_automation.errors", "hwpx_automation.office")

_PROBE = textwrap.dedent(
    """
    import importlib
    import json
    import pkgutil
    import sys

    target = sys.argv[1]
    forbidden_top = tuple(json.loads(sys.argv[2]))
    forbidden_internal = tuple(json.loads(sys.argv[3]))
    walk = sys.argv[4] == "walk"

    def offenders():
        found = []
        for name in sys.modules:
            if name.split(".")[0] in forbidden_top:
                found.append(name.split(".")[0])
            elif any(name == p or name.startswith(p + ".") for p in forbidden_internal):
                found.append(name)
        return sorted(set(found))

    report = {"checked": [], "skipped": {}, "offenders": {}}
    module = importlib.import_module(target)
    report["checked"].append(target)
    bad = offenders()
    if bad:
        report["offenders"][target] = bad
    if walk and hasattr(module, "__path__"):
        for info in pkgutil.walk_packages(module.__path__, target + "."):
            before = set(sys.modules)
            try:
                importlib.import_module(info.name)
            except ModuleNotFoundError as exc:
                missing = (exc.name or "").split(".")[0]
                if missing in ("hwpx", "hwpx_automation", ""):
                    raise
                report["skipped"][info.name] = missing
                continue
            report["checked"].append(info.name)
            bad = [b for b in offenders() if b not in report["offenders"].get(target, [])]
            if bad:
                report["offenders"][info.name] = bad
    print(json.dumps(report))
    """
)


def _exists(module: str) -> bool:
    relative = Path(*module.split(".")[1:])
    return (PACKAGE / relative).is_dir() or (PACKAGE / relative).with_suffix(".py").is_file()


def _probe(module: str, *, walk: bool = True) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE,
            module,
            json.dumps(FORBIDDEN_TOP_LEVEL),
            json.dumps(FORBIDDEN_INTERNAL),
            "walk" if walk else "root",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("module", LIGHT_LAYER_MODULES)
def test_light_layer_module_does_not_load_heavy_or_adapter_layers(module: str) -> None:
    if not _exists(module):
        pytest.skip(f"{module} has not been created yet; the rule applies once it exists")
    report = _probe(module)
    assert report["checked"], report
    assert not report["offenders"], (
        f"{module} pulled heavy/adapter modules on import: {report['offenders']}; "
        "keep pydantic/cryptography/mcp/errors/office behind a lazy import"
    )


def test_the_guard_detects_a_heavy_import() -> None:
    """The probe is not vacuous: the task facade does load pydantic."""

    report = _probe("hwpx_automation.api", walk=False)
    assert "pydantic" in report["offenders"]["hwpx_automation.api"]


def test_package_root_import_stays_light() -> None:
    """Every light module imports the package root first, so it must be light."""

    report = _probe("hwpx_automation", walk=False)
    assert report["checked"] == ["hwpx_automation"]
    assert not report["offenders"], report["offenders"]


def test_light_layer_is_not_routed_through_the_root_facade() -> None:
    import hwpx_automation

    exported = set(getattr(hwpx_automation, "_API_EXPORTS", ()))
    short_names = {module.rsplit(".", 1)[-1] for module in LIGHT_LAYER_MODULES}
    assert not exported & short_names, (
        "light-layer modules must be imported by their own path, not through "
        "hwpx_automation.__getattr__ (which loads hwpx_automation.api)"
    )
