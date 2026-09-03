# tests/launcher_harness/fake_uv.py
# SPDX-License-Identifier: Apache-2.0
"""Offline stand-in for the uv subset that packaging/templates/hwpx-automation-mcp calls.

Never used in production. Driven by FAKE_UV_* environment variables (see
tests/test_launcher_harness.py). Resolution is a tiny PEP 440-ish subset:
``name[extras]==X``, ``name[extras]>=A,<B`` and bare names, over the version
lists in FAKE_UV_INDEX. Installs write stub ``hwpx`` / ``hwpx_automation``
packages with dist-info metadata and a fake ``hwpx-automation-mcp`` console.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import venv
from pathlib import Path

SPEC_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]*\])?(?P<ops>.*)$")
MODULE_FOR = {"python-hwpx": "hwpx", "python-hwpx-automation": "hwpx_automation"}
DIST_FOR = {"python-hwpx": "python_hwpx", "python-hwpx-automation": "python_hwpx_automation"}
FAKE_VENV_MARKER = ".fake-uv-venv"


def _record(argv: list[str]) -> None:
    path = os.environ.get("FAKE_UV_CALLS")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")


def _vt(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _satisfies(version: str, ops: str) -> bool:
    for clause in filter(None, (c.strip() for c in ops.split(","))):
        match = re.match(r"^(==|>=|<=|<|>|!=)\s*([0-9.]+)$", clause)
        if not match:
            raise SystemExit(f"fake uv: unsupported clause {clause!r}")
        op, target = match.group(1), _vt(match.group(2))
        actual = _vt(version)
        ok = {"==": actual == target, ">=": actual >= target, "<=": actual <= target, "<": actual < target, ">": actual > target, "!=": actual != target}[op]
        if not ok:
            return False
    return True


def _resolve(spec: str) -> tuple[str, str]:
    match = SPEC_RE.match(spec)
    if not match:
        raise SystemExit(f"fake uv: cannot parse {spec!r}")
    name, ops = match.group("name"), match.group("ops").strip()
    index = json.loads(os.environ.get("FAKE_UV_INDEX", "{}"))
    candidates = [v for v in index.get(name, []) if _satisfies(v, ops)]
    if not candidates:
        sys.stderr.write(f"error: No solution found when resolving dependencies: {spec}\n")
        raise SystemExit(1)
    return name, max(candidates, key=_vt)


def _site_packages(python: Path) -> Path:
    # Resolve the venv directory, never the interpreter: `bin/python` is a
    # symlink to the base interpreter, and following it once wrote stubs into
    # the real system site-packages. Then require the fake's own stamp: a real
    # venv (the developer venv running pytest, for one) must never be written
    # to, whatever interpreter the tests happen to run under (Task 1, 2026-09-03).
    prefix = python.parent.parent.resolve()
    if not (prefix / "pyvenv.cfg").is_file() or not (prefix / FAKE_VENV_MARKER).is_file():
        sys.stderr.write(
            f"fake uv: refusing to install into an interpreter prefix the fake did not create: {prefix}\n"
        )
        raise SystemExit(64)
    lib = prefix / "lib"
    versions = sorted(lib.glob("python3*"))
    if not versions:
        raise SystemExit(f"fake uv: no site-packages under {prefix}")
    return versions[0] / "site-packages"


def _installed(python: Path) -> dict[str, str]:
    marker = _site_packages(python) / "fake-installed.json"
    return json.loads(marker.read_text()) if marker.exists() else {}


def _write_stub(python: Path, name: str, version: str) -> None:
    site = _site_packages(python)
    site.mkdir(parents=True, exist_ok=True)
    module = site / MODULE_FOR[name]
    module.mkdir(exist_ok=True)
    if name == "python-hwpx" and os.environ.get("FAKE_UV_BROKEN_VERSION") == version:
        (module / "__init__.py").write_text('raise ImportError("fake broken python-hwpx build")\n')
    else:
        (module / "__init__.py").write_text(f'__version__ = "{version}"\n')
    if name == "python-hwpx-automation":
        ok = os.environ.get("FAKE_UV_CAPABILITY_OK", "1") == "1"
        (module / "quality.py").write_text(
            "def capability_state():\n"
            f"    return {{'ok': {ok}, 'skew': {[] if ok else ['stub skew']!r}}}\n"
        )
    for stale in site.glob(f"{DIST_FOR[name]}-*.dist-info"):
        for child in stale.iterdir():
            child.unlink()
        stale.rmdir()
    dist = site / f"{DIST_FOR[name]}-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    installed = _installed(python)
    installed[name] = version
    (site / "fake-installed.json").write_text(json.dumps(installed))
    console = python.parent / "hwpx-automation-mcp"
    console.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "--help" ]; then echo "usage: hwpx-automation-mcp [-h] [--transport {stdio,streamable-http,http}]"; exit 0; fi\n'
        f'PY="$(cd "$(dirname "$0")" && pwd)/python"\n'
        'echo "FAKE-SERVER core=$("$PY" -c "from importlib.metadata import version; print(version(\'python-hwpx\'))") '
        'automation=$("$PY" -c "from importlib.metadata import version; print(version(\'python-hwpx-automation\'))") '
        'state=${HWPX_STACK_UPDATE_STATE:-} args=$*"\n'
    )
    console.chmod(0o755)


def cmd_python_find(_: list[str]) -> int:
    print(sys.executable)
    return 0


def cmd_venv(args: list[str]) -> int:
    target = [a for a in args if not a.startswith("--")]
    if len(target) != 1:
        raise SystemExit("fake uv venv: exactly one directory expected")
    venv.EnvBuilder(with_pip=False, symlinks=True).create(target[0])
    # Stamp the venv so installs can prove the fake created it (see _site_packages).
    (Path(target[0]) / FAKE_VENV_MARKER).write_text("created by tests/launcher_harness/fake_uv.py\n")
    return 0


def cmd_pip_install(args: list[str]) -> int:
    dry_run = "--dry-run" in args
    python: Path | None = None
    specs: list[str] = []
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg == "--python":
            python = Path(args[index + 1])
            skip = True
        elif arg == "--refresh-package":
            skip = True
        elif arg.startswith("--"):
            continue
        else:
            specs.append(arg)
    if python is None:
        raise SystemExit("fake uv pip install: --python is required by the launcher contract")
    if os.environ.get("FAKE_UV_OFFLINE") == "1":
        sys.stderr.write("error: Failed to fetch: `https://pypi.org/simple/python-hwpx/`\n  Caused by: Network is unreachable\n")
        return 2
    sleep = float(os.environ.get("FAKE_UV_SLEEP", "0") or 0)
    if sleep:
        time.sleep(sleep)
    resolved = dict(_resolve(spec) for spec in specs)
    installed = _installed(python)
    changes = [(name, installed.get(name), version) for name, version in resolved.items() if installed.get(name) != version]
    if dry_run:
        print(f"Resolved {len(resolved)} packages in 1ms")
        if not changes:
            print("Would make no changes")
            return 0
        print(f"Would install {len(changes)} package{'s' if len(changes) != 1 else ''}")
        for name, old, new in changes:
            if old:
                print(f" - {name}=={old}")
            print(f" + {name}=={new}")
        return 0
    for name, version in resolved.items():
        _write_stub(python, name, version)
    return 0


def main(argv: list[str]) -> int:
    _record(argv)
    if argv[:2] == ["python", "find"]:
        return cmd_python_find(argv[2:])
    if argv[:1] == ["venv"]:
        return cmd_venv(argv[1:])
    if argv[:2] == ["pip", "install"]:
        return cmd_pip_install(argv[2:])
    sys.stderr.write(f"fake uv: unsupported invocation {argv!r}\n")
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
