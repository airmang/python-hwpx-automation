#!/usr/bin/env python3
"""Install the bundled python-hwpx stack into this chat's Python environment.

Run once per conversation from the Python tool, with the kernel's own interpreter::

    subprocess.run([sys.executable, "<skill>/scripts/bootstrap.py"], ...)

Only the wheels shipped in ``wheels/`` are installed and the package index is
never contacted (``--no-index``).  python-hwpx needs only lxml; the automation
layer also needs pydantic, cryptography and anyio.  If the sandbox cannot
satisfy the automation layer offline, the core is still installed and the
status says so.  The last line of output is always one JSON status record.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
WHEELS = SKILL / "wheels"
MANIFEST = json.loads((SKILL / "skill-manifest.json").read_text(encoding="utf-8"))
PACKAGES = {
    "core": ("python-hwpx", "hwpx", MANIFEST["core"]),
    "automation": ("python-hwpx-automation", "hwpx_automation", MANIFEST["automation"]),
}
PREINSTALLED = ("lxml", "pydantic", "pydantic-core", "cryptography", "anyio", "typing_extensions")
PIP_TIMEOUT = 180


def importable_version(module: str) -> str | None:
    """Version importable from a fresh interpreter (user site included), or None."""
    code = f"import {module}; print({module}.__version__)"
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout.strip().splitlines()[-1] if proc.returncode == 0 and proc.stdout.strip() else None


def verify_wheels() -> list[str]:
    bad = []
    for wheel in MANIFEST["wheels"]:
        path = WHEELS / wheel["filename"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != wheel["sha256"]:
            bad.append(wheel["filename"])
    return bad


def install(distribution: str, module: str, expected: str) -> dict:
    """Try system then --user site, offline only; stop at the first mode that imports the expected version."""
    if importable_version(module) == expected:
        return {"ok": True, "mode": "already-installed"}
    attempts = []
    for mode, extra in (("offline", []), ("offline-user", ["--user"])):
        command = [
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-index",
            "--find-links", str(WHEELS), *extra, f"{distribution}=={expected}",
        ]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=PIP_TIMEOUT)
            log, returncode = (proc.stdout + proc.stderr)[-500:], proc.returncode
        except subprocess.TimeoutExpired:
            log, returncode = f"pip timed out after {PIP_TIMEOUT}s", None
        found = importable_version(module)
        attempts.append({"mode": mode, "returncode": returncode, "importable": found})
        if found == expected:
            return {"ok": True, "mode": mode}
        attempts[-1]["log"] = log
    return {"ok": False, "attempts": attempts}


def main() -> int:
    status: dict = {
        "ok": False,
        "skill": MANIFEST["skill"],
        "skillVersion": MANIFEST["version"],
        "python": sys.version.split()[0],
        "expected": {key: spec[2] for key, spec in PACKAGES.items()},
    }
    preinstalled = {}
    for name in PREINSTALLED:
        try:
            preinstalled[name] = version(name)
        except PackageNotFoundError:
            preinstalled[name] = None
    status["preinstalled"] = preinstalled

    bad = verify_wheels()
    if bad:
        status["error"] = f"bundled wheel checksum mismatch: {bad}"
        print(json.dumps(status, ensure_ascii=False))
        return 1

    core = install(*PACKAGES["core"])
    status["core"] = core
    if not core["ok"]:
        status["error"] = "python-hwpx could not be installed offline (lxml missing or incompatible?)"
        print(json.dumps(status, ensure_ascii=False))
        return 1
    status["ok"] = True

    automation = install(*PACKAGES["automation"])
    status["automation"] = automation
    if not automation["ok"]:
        status["note"] = (
            "python-hwpx-automation is unavailable offline in this sandbox "
            "(pydantic>=2.11, cryptography or anyio missing); reading and editing work, "
            "creating a new document from a plan (W5) does not"
        )
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
