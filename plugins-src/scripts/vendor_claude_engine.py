#!/usr/bin/env python3
"""Unpack the locked engine into the Claude bundle's skill for hosts without MCP.

claude.ai chat loads the plugin's skill but cannot start the local MCP server,
and its code sandbox cannot reach PyPI.  The skill therefore carries the
released engine as readable source under ``skills/hwpx/engine/`` and imports it
from there.  Nothing is edited by hand: this script takes the exact
``py3-none-any`` wheels that ``server/uv.lock`` pins (sha256-checked), unpacks
their packages and metadata, adds the core API documents from the same core
tag, and records every file's sha256 in ``engine/VENDOR.json``.  The Claude
runtime refresh bot runs it after every re-lock, so the MCP server and the
vendored engine always move together.

Usage::

    python3 scripts/vendor_claude_engine.py           # (re)write the engine from the lock (network or cache)
    python3 scripts/vendor_claude_engine.py --check   # verify the committed engine offline
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "templates" / "claude-runtime" / "uv.lock"
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
ENGINE = BUNDLE / "skills" / "hwpx" / "engine"
MANIFEST = ENGINE / "VENDOR.json"
CACHE = ROOT / ".cache" / "claude-engine"
SCHEMA = "hwpx.claude-engine.v1"
# tomli: python-hwpx-automation needs it below Python 3.11 (locked in the chat-engine group).
DISTRIBUTIONS = ("python-hwpx", "python-hwpx-automation", "tomli")
CORE_REPOSITORY = "airmang/python-hwpx"
# API name list and stable surface from the core release tag; the wheel already
# carries mutation semantics, traversal recipes and the support matrix.
CORE_DOCS = {"docs/_extra/llms.txt": "docs/llms.txt", "docs/stable-api.md": "docs/stable-api.md"}
# Installer bookkeeping that importlib.metadata does not need.
SKIPPED_METADATA = {"RECORD", "WHEEL", "entry_points.txt"}
# Claude plugin directory limits: larger files are not inspected.
MAX_FILE_BYTES = 256 * 1024
MAX_PLUGIN_FILES = 512
# Windows without long-path support stops at 260 characters; the host's plugin cache
# prefix (user profile, marketplace, plugin, version string) takes about 100 of them.
MAX_RELATIVE_PATH = 140


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hwpx-claude-engine-vendor"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def cached(url: str, digest: str) -> bytes:
    path = CACHE / digest
    if path.is_file() and sha256_bytes(path.read_bytes()) == digest:
        return path.read_bytes()
    data = fetch(url)
    if sha256_bytes(data) != digest:
        raise SystemExit(f"sha256 mismatch for {url}")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def locked_wheels() -> list[dict]:
    """The pure-Python wheel of each engine distribution exactly as uv.lock pins it."""
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    wheels = []
    for name in DISTRIBUTIONS:
        packages = [p for p in lock["package"] if p["name"] == name]
        if len(packages) != 1:
            raise SystemExit(f"uv.lock must lock exactly one {name}")
        pure = [w for w in packages[0].get("wheels", []) if w["url"].endswith("-py3-none-any.whl")]
        if len(pure) != 1 or not pure[0]["hash"].startswith("sha256:"):
            raise SystemExit(f"uv.lock has no single sha256-pinned py3-none-any wheel for {name}")
        wheels.append({
            "distribution": name,
            "version": packages[0]["version"],
            "filename": pure[0]["url"].rsplit("/", 1)[1],
            "url": pure[0]["url"],
            "sha256": pure[0]["hash"].removeprefix("sha256:"),
        })
    return wheels


def wheel_members(data: bytes) -> dict[str, bytes]:
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir():
                continue
            parts = name.split("/")
            if parts[0].endswith(".dist-info") and parts[-1] in SKIPPED_METADATA:
                continue
            if ".." in parts or name.startswith("/"):
                raise SystemExit(f"unsafe wheel member: {name}")
            files[name] = archive.read(info)
    return files


def vendor() -> dict:
    wheels = locked_wheels()
    core = next(w for w in wheels if w["distribution"] == "python-hwpx")
    files: dict[str, bytes] = {}
    for wheel in wheels:
        files.update(wheel_members(cached(wheel["url"], wheel["sha256"])))
    docs = []
    for source, dest in CORE_DOCS.items():
        url = f"https://raw.githubusercontent.com/{CORE_REPOSITORY}/v{core['version']}/{source}"
        data = fetch(url)
        files[dest] = data
        docs.append({"source": source, "tag": f"v{core['version']}", "url": url, "dest": dest, "sha256": sha256_bytes(data)})

    if ENGINE.exists():
        if not MANIFEST.is_file():
            raise SystemExit(f"refusing to replace {ENGINE} without {MANIFEST.name}")
        shutil.rmtree(ENGINE)
    for rel, data in sorted(files.items()):
        path = ENGINE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "schemaVersion": SCHEMA,
        "wheels": wheels,
        "coreDocs": docs,
        "files": {rel: sha256_bytes(data) for rel, data in sorted(files.items())},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def check() -> list[str]:
    """Offline: the committed engine is exactly what VENDOR.json and uv.lock say, within directory limits."""
    problems: list[str] = []
    if not MANIFEST.is_file():
        return [f"{MANIFEST.relative_to(ROOT)} missing; run scripts/vendor_claude_engine.py"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA:
        problems.append(f"engine manifest schema {manifest.get('schemaVersion')!r} != {SCHEMA}")
    if manifest.get("wheels") != locked_wheels():
        problems.append("engine wheels differ from server/uv.lock; run scripts/vendor_claude_engine.py")
    core = next((w for w in manifest.get("wheels", []) if w.get("distribution") == "python-hwpx"), {})
    if any(doc.get("tag") != f"v{core.get('version')}" for doc in manifest.get("coreDocs", [])):
        problems.append("engine core documents are not from the vendored core tag")
    recorded = manifest.get("files", {})
    actual = {
        path.relative_to(ENGINE).as_posix()
        for path in ENGINE.rglob("*")
        if path.is_file() and path != MANIFEST and "__pycache__" not in path.parts
    }
    if actual != set(recorded):
        problems.append(f"engine files differ from VENDOR.json: extra {sorted(actual - set(recorded))[:5]}, "
                        f"missing {sorted(set(recorded) - actual)[:5]}")
    for rel in sorted(actual & set(recorded)):
        data = (ENGINE / rel).read_bytes()
        if sha256_bytes(data) != recorded[rel]:
            problems.append(f"engine file changed: {rel}")
    bundle_files = [p for p in BUNDLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                    and "examples/out" not in p.as_posix()]
    if len(bundle_files) > MAX_PLUGIN_FILES:
        problems.append(f"Claude bundle has {len(bundle_files)} files; the directory reads at most {MAX_PLUGIN_FILES}")
    for path in bundle_files:
        rel = path.relative_to(BUNDLE).as_posix()
        if len(rel) > MAX_RELATIVE_PATH:
            problems.append(f"{rel} is {len(rel)} characters; keep bundle paths within {MAX_RELATIVE_PATH} for Windows")
        if path.stat().st_size > MAX_FILE_BYTES:
            problems.append(f"{path.relative_to(BUNDLE)} is {path.stat().st_size} bytes; the directory reads at most {MAX_FILE_BYTES}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the committed engine offline")
    args = parser.parse_args(argv)
    if not args.check:
        manifest = vendor()
        print(f"[OK] vendored {', '.join(w['distribution'] + ' ' + w['version'] for w in manifest['wheels'])} "
              f"({len(manifest['files'])} files)")
    problems = check()
    for problem in problems:
        print(f"[FAIL] {problem}")
    if not problems:
        print(f"[OK] engine matches the lock ({len(list(BUNDLE.rglob('*')))} bundle entries)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
