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
SKIPPED_METADATA = {"RECORD", "WHEEL", "entry_points.txt", "top_level.txt"}
# Type-checker markers: nothing reads them at run time, and every file counts
# against the plugin directory's file limit.
SKIPPED_TYPING_MARKERS = ("py.typed",)
SKIPPED_TYPING_SUFFIXES = (".pyi",)
# Claude plugin directory limits: larger files are not inspected.
MAX_FILE_BYTES = 256 * 1024
MAX_PLUGIN_FILES = 512
# The engine serves only the chat path (chat-engine.md: ``import hwpx``,
# ``hwpx_automation.api``). The MCP server never reads it: Claude starts the
# server from ``server/uv.lock`` with ``uv run --frozen``. So the MCP server
# layer, command-line entry points, the Hancom render worker and third-party
# framework adapters are left out of the vendored copy. Core 7.0 + automation
# 8.0 would otherwise need 517 files (> 512). Every entry is a wheel member path
# prefix; check() fails when anything kept imports a module left out here.
EXCLUDED_ENGINE_MEMBERS = (
    # MCP server layer (tools, handlers, runtime, stdio entry points)
    "hwpx_automation/handlers/",
    "hwpx_automation/ops_services/",
    "hwpx_automation/server.py",
    "hwpx_automation/runtime.py",
    "hwpx_automation/runtime_services.py",
    "hwpx_automation/tool_bindings.py",
    "hwpx_automation/hwpx_ops.py",
    "hwpx_automation/mcp_cli.py",
    "hwpx_automation/__main__.py",
    # MCP workflow engine (durable workflows, render queue transport)
    "hwpx_automation/workflow/service.py",
    "hwpx_automation/workflow/adapters.py",
    "hwpx_automation/workflow/render_transport.py",
    "hwpx_automation/workflow/render_metrics.py",
    "hwpx_automation/workflow/evidence_lineage.py",
    # Hancom render worker and its command line (needs a desktop Hancom)
    "hwpx_automation/office/rendering/__main__.py",
    "hwpx_automation/office/rendering/cli.py",
    "hwpx_automation/office/rendering/worker.py",
    # (fixture_corpus, page_qa, qa_metrics stay: visual_qa imports them.)
    "hwpx_automation/office/agent/cli.py",
    # LangChain / LlamaIndex adapters (8.0; need those frameworks installed)
    "hwpx_automation/integrations/",
    # core command-line entry point
    "hwpx/tools/text_extract_cli.py",
)
# Modules the chat path imports (chat-engine.md start block and W1-W5).
CHAT_ROOTS = ("hwpx", "hwpx_automation", "hwpx_automation.api")


def is_excluded(member: str) -> bool:
    return member.startswith(EXCLUDED_ENGINE_MEMBERS)


def static_closure(source_root: Path | list[Path], roots: tuple[str, ...] | None = CHAT_ROOTS) -> dict[str, set[str]]:
    """Every engine module reachable from ``roots`` by any import statement.

    Follows function-level (lazy) imports and ``import_module("literal")`` too,
    so it over-approximates what the chat path can load. Returns
    {module: names it imports that resolve to an hwpx/hwpx_automation module or
    to an excluded member} for the reached modules.
    """
    import ast

    modules: dict[str, Path] = {}
    source_roots = source_root if isinstance(source_root, list) else [source_root]
    for base, top in ((base, top) for base in source_roots for top in ("hwpx", "hwpx_automation")):
        for path in (base / top).rglob("*.py"):
            if is_excluded(path.relative_to(base).as_posix()):
                continue  # forecast mode reads full sources; left-out modules are not engine modules
            parts = list(path.relative_to(base).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules[".".join(parts)] = path
    excluded = set()
    for member in EXCLUDED_ENGINE_MEMBERS:
        name = member.removesuffix("/").removesuffix(".py").replace("/", ".")
        excluded.add(name.removesuffix(".__init__"))

    def known(name: str) -> bool:
        return name in modules or any(name == e or name.startswith(e + ".") for e in excluded)

    def imports(module: str) -> set[str]:
        path = modules[module]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    stem = package[: len(package) - (node.level - 1)]
                    base = ".".join(stem + ([base] if base else []))
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
            elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)
                  and getattr(node.func, "attr", getattr(node.func, "id", "")) == "import_module"):
                names.add(node.args[0].value)
        found: set[str] = set()
        for name in names:
            parts = name.split(".")
            for index in range(1, len(parts) + 1):
                prefix = ".".join(parts[:index])
                if known(prefix):
                    found.add(prefix)
        return found

    reached: dict[str, set[str]] = {}
    stack = [root for root in (modules if roots is None else roots) if root in modules]
    while stack:
        module = stack.pop()
        if module in reached:
            continue
        reached[module] = imports(module)
        stack.extend(name for name in reached[module] if name in modules and name not in reached)
    return reached


def excluded_imports(source_root: Path | list[Path]) -> list[str]:
    """``module -> excluded`` edges from any module the engine keeps.

    Every kept module is a root, not only the chat entry points: a kept module
    that imports a left-out one would fail at import time (found that way for
    the render-QA modules), so the build refuses it.
    """
    problems = []
    for module, names in sorted(static_closure(source_root, roots=None).items()):
        for name in sorted(names):
            member_py = name.replace(".", "/") + ".py"
            member_pkg = name.replace(".", "/") + "/"
            if is_excluded(member_py) or is_excluded(member_pkg):
                problems.append(f"{module} imports {name}, which the engine leaves out")
    return problems
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
            if parts[-1] in SKIPPED_TYPING_MARKERS or parts[-1].endswith(SKIPPED_TYPING_SUFFIXES):
                continue
            if is_excluded(name):
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
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
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
    present = sorted(rel for rel in actual if is_excluded(rel))
    if present:
        problems.append(f"engine carries members it must leave out: {present[:5]}")
    problems.extend(excluded_imports(ENGINE))
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
