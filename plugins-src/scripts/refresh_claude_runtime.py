#!/usr/bin/env python3
"""Move the Claude bundle's locked runtime to the newest engine inside the install window.

The Claude plugin directory requires exact pins, so the Claude bundle cannot
self-update on the user's machine the way the managed launcher does. Instead
this script runs in CI (``claude-runtime-refresh`` workflow): it picks the
newest stable, non-yanked ``python-hwpx`` and ``python-hwpx-automation`` on PyPI
inside the window from ``packaging/product-identity.json`` (>= currentVersion,
< next major), rewrites the pins, re-locks ``uv.lock``, re-vendors the skill's
engine copy from the new lock and changes the Claude plugin's version string so
Claude Code sees an update.

Usage::

    python3 scripts/refresh_claude_runtime.py            # update files if a newer pair exists
    python3 scripts/refresh_claude_runtime.py --dry-run  # only report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "packaging" / "product-identity.json"
RUNTIME = ROOT / "packaging" / "templates" / "claude-runtime"
PYPROJECT = RUNTIME / "pyproject.toml"
MANIFEST = ROOT / "packaging" / "templates" / "claude.plugin.json"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PIN_RE = re.compile(r'"(?P<dist>python-hwpx(?:-automation)?)\[(?P<extras>[^\]]*)\]==(?P<version>[^"]+)"')


def parse(version: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(version)
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def claude_plugin_version(plugin_version: str, core: str, automation: str, identity: dict) -> str:
    """Train version when the runtime is the verified pair, otherwise a runtime-tagged variant.

    Claude Code only compares version strings for equality, so any change here is
    delivered as a plugin update.
    """
    components = identity["components"]
    if core == components["core"]["currentVersion"] and automation == components["automation"]["currentVersion"]:
        return plugin_version
    return f"{plugin_version}+core.{core}.automation.{automation}"


def current_pins() -> dict[str, str]:
    return {m.group("dist"): m.group("version") for m in PIN_RE.finditer(PYPROJECT.read_text(encoding="utf-8"))}


def newest_in_window(distribution: str, floor: str, releases: dict) -> str:
    low = parse(floor)
    if low is None:
        raise SystemExit(f"{distribution}: floor {floor!r} is not a plain X.Y.Z version")
    candidates = []
    for version, files in releases.items():
        parsed = parse(version)
        if parsed is None or parsed < low or parsed[0] != low[0]:
            continue  # pre-release, below the verified floor, or next major
        if not files or all(f.get("yanked") for f in files):
            continue
        candidates.append((parsed, version))
    if not candidates:
        raise SystemExit(f"{distribution}: no published release inside >={floor},<{low[0] + 1}")
    return max(candidates)[1]


def pypi_releases(distribution: str) -> dict:
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{distribution}/json", headers={"User-Agent": "hwpx-claude-runtime-refresh"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["releases"]


def write_outputs(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    components = identity["components"]
    core_dist, automation_dist = components["core"]["distribution"], components["automation"]["distribution"]
    target = {
        core_dist: newest_in_window(core_dist, components["core"]["currentVersion"], pypi_releases(core_dist)),
        automation_dist: newest_in_window(
            automation_dist, components["automation"]["currentVersion"], pypi_releases(automation_dist)
        ),
    }
    before = current_pins()
    version = claude_plugin_version(
        components["plugin"]["currentVersion"], target[core_dist], target[automation_dist], identity
    )
    changed = before != target or json.loads(MANIFEST.read_text(encoding="utf-8"))["version"] != version
    summary = {"changed": str(changed).lower(), "core": target[core_dist], "automation": target[automation_dist], "version": version}
    print(json.dumps({"before": before, **summary}, ensure_ascii=False))
    if not changed or args.dry_run:
        write_outputs(summary)
        return 0

    text = PYPROJECT.read_text(encoding="utf-8")
    text = PIN_RE.sub(lambda m: f'"{m.group("dist")}[{m.group("extras")}]=={target[m.group("dist")]}"', text)
    PYPROJECT.write_text(text, encoding="utf-8")
    lock = subprocess.run(["uv", "lock", "--project", str(RUNTIME)], capture_output=True, text=True)
    if lock.returncode != 0:
        subprocess.run(["git", "checkout", "--", str(PYPROJECT)], cwd=ROOT, check=False)
        raise SystemExit(f"uv lock failed for {target}; pins restored:\n{lock.stderr[-2000:]}")

    # The skill's vendored engine (claude.ai chat, no MCP) must move with the server runtime.
    vendored = subprocess.run([sys.executable, str(ROOT / "scripts" / "vendor_claude_engine.py")],
                              capture_output=True, text=True)
    if vendored.returncode != 0:
        raise SystemExit(f"vendoring the engine for {target} failed:\n{(vendored.stdout + vendored.stderr)[-2000:]}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = version
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_outputs(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
