#!/usr/bin/env python3
"""Build the ChatGPT skill and skills-only plugin ZIPs from pinned public artifacts.

The ChatGPT code sandbox cannot launch the local MCP server, so this host
channel ships the released engine wheels inside the skill and routes work
through the public Python API instead.  Every external file (wheels and the
core documentation copied from a release tag) is pinned by URL and sha256 in
``packaging/chatgpt/lock.json``.

Usage::

    python3 scripts/build_chatgpt_skill.py                 # dist/<plugin>-skill-<ver>.zip + dist/<plugin>-plugin-<ver>.zip
    python3 scripts/build_chatgpt_skill.py --check         # lock matches product identity (offline)
    python3 scripts/build_chatgpt_skill.py --refresh-lock  # re-pin from PyPI / GitHub (network)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packaging" / "chatgpt"
IDENTITY = ROOT / "packaging" / "product-identity.json"
SOURCES = SOURCE / "sources.json"
LOCK = SOURCE / "lock.json"
DIST = ROOT / "dist"
CACHE = ROOT / ".cache" / "chatgpt-skill"
LOCK_SCHEMA = "hwpx.chatgpt-skill-lock.v1"
# 1980-01-01 is the earliest ZIP timestamp; a fixed value keeps builds byte-identical.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
# Build tokens are upper-case; document-plan computed fields ({{ sum(...) }}) are left alone.
BUILD_TOKEN = re.compile(r"\{\{[A-Z_]+\}\}")
TEMPLATE_SUFFIXES = {".md", ".py", ".json", ".txt", ".yaml"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hwpx-chatgpt-skill-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def identity_versions() -> dict[str, str]:
    components = load_json(IDENTITY)["components"]
    return {
        "core": components["core"]["currentVersion"],
        "automation": components["automation"]["currentVersion"],
        "plugin": components["plugin"]["currentVersion"],
    }


def pypi_wheel(name: str, version: str | None) -> dict:
    """Return the ``py3-none-any`` wheel record for a PyPI release."""
    url = f"https://pypi.org/pypi/{name}/{version}/json" if version else f"https://pypi.org/pypi/{name}/json"
    release = json.loads(fetch(url))
    for item in release["urls"]:
        if item["packagetype"] == "bdist_wheel" and item["filename"].endswith("-py3-none-any.whl"):
            return {
                "distribution": name,
                "version": release["info"]["version"],
                "filename": item["filename"],
                "url": item["url"],
                "sha256": item["digests"]["sha256"],
            }
    raise SystemExit(f"{name} {version or 'latest'} has no py3-none-any wheel on PyPI")


def refresh_lock() -> dict:
    versions = identity_versions()
    sources = load_json(SOURCES)
    wheels = [
        pypi_wheel("python-hwpx", versions["core"]),
        pypi_wheel("python-hwpx-automation", versions["automation"]),
    ]
    wheels += [pypi_wheel(*spec.split("==")) for spec in sources["runtimeDependencies"]]

    tag = f"v{versions['core']}"
    docs = []
    for doc in sources["coreDocs"]:
        url = f"https://raw.githubusercontent.com/{sources['coreRepository']}/{tag}/{doc['path']}"
        docs.append({**doc, "tag": tag, "url": url, "sha256": sha256_bytes(fetch(url))})

    lock = {
        "schemaVersion": LOCK_SCHEMA,
        "skillName": sources["skillName"],
        "versions": versions,
        "wheels": wheels,
        "coreDocs": docs,
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] refreshed {LOCK.relative_to(ROOT)}")
    return lock


def check_lock(lock: dict) -> None:
    if lock.get("schemaVersion") != LOCK_SCHEMA:
        raise SystemExit(f"unexpected lock schema: {lock.get('schemaVersion')}")
    expected = identity_versions()
    if lock["versions"] != expected:
        raise SystemExit(
            f"lock versions {lock['versions']} != product identity {expected}; "
            "run scripts/build_chatgpt_skill.py --refresh-lock"
        )
    pinned = {w["distribution"]: w["version"] for w in lock["wheels"]}
    if pinned.get("python-hwpx") != expected["core"] or pinned.get("python-hwpx-automation") != expected["automation"]:
        raise SystemExit(f"lock wheels {pinned} do not pin the current public engine")
    if any(doc["tag"] != f"v{expected['core']}" for doc in lock["coreDocs"]):
        raise SystemExit("core documentation is not pinned to the current core tag")


def cached(url: str, digest: str) -> bytes:
    path = CACHE / digest
    if path.is_file() and sha256_bytes(path.read_bytes()) == digest:
        return path.read_bytes()
    data = fetch(url)
    actual = sha256_bytes(data)
    if actual != digest:
        raise SystemExit(f"sha256 mismatch for {url}: expected {digest}, got {actual}")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def web_version() -> str:
    return load_json(SOURCES)["version"]


def render_template(text: str, lock: dict) -> str:
    wheels = {w["distribution"]: w for w in lock["wheels"]}
    values = {
        "{{WEB_VERSION}}": web_version(),
        "{{CORE_VERSION}}": lock["versions"]["core"],
        "{{AUTOMATION_VERSION}}": lock["versions"]["automation"],
        "{{CORE_WHEEL}}": wheels["python-hwpx"]["filename"],
        "{{AUTOMATION_WHEEL}}": wheels["python-hwpx-automation"]["filename"],
    }
    for key, value in values.items():
        text = text.replace(key, value)
    leftover = BUILD_TOKEN.search(text)
    if leftover:
        raise SystemExit(f"unrendered template token: {leftover.group(0)}")
    return text


def copy_source_tree(src_root: Path, out: Path, lock: dict) -> None:
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        rel = src.relative_to(src_root)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue  # editor/OS droppings and bytecode must never reach the published bundle
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEMPLATE_SUFFIXES:
            dest.write_text(render_template(src.read_text(encoding="utf-8"), lock), encoding="utf-8")
        else:
            shutil.copyfile(src, dest)


def wheel_license(data: bytes) -> tuple[str, str]:
    """(license expression, project URL) from a wheel's METADATA."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(name).decode("utf-8")
    license_expr = re.search(r"^License-Expression: (.+)$", metadata, re.MULTILINE)
    urls = dict(re.findall(r"^Project-URL: ([^,]+), (https://\S+)$", metadata, re.MULTILINE))
    if not license_expr:
        raise SystemExit(f"{name}: no License-Expression; add it to the notice by hand")
    preferred = ("Source", "Source code", "Repository", "Homepage")
    url = next((urls[label] for label in preferred if label in urls), next(iter(urls.values()), ""))
    return license_expr.group(1).strip(), url


def assemble(lock: dict) -> Path:
    """Build the standalone skill tree ``dist/<skillName>/``."""
    name = lock["skillName"]
    out = DIST / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copy_source_tree(SOURCE / "skill", out, lock)
    shutil.copyfile(ROOT / "LICENSE", out / "LICENSE")

    wheel_dir = out / "wheels"
    wheel_dir.mkdir()
    sums, notices = [], []
    for wheel in lock["wheels"]:
        data = cached(wheel["url"], wheel["sha256"])
        (wheel_dir / wheel["filename"]).write_bytes(data)
        sums.append(f"{wheel['sha256']}  {wheel['filename']}")
        license_expr, url = wheel_license(data)
        notices.append(f"| {wheel['distribution']} | {wheel['version']} | {license_expr} | {url} |")
    (wheel_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (out / "THIRD_PARTY_NOTICES.md").write_text(
        "# Bundled software\n\n"
        "The wheels in `wheels/` are unmodified releases downloaded from PyPI and verified by sha256.\n"
        "Each wheel carries its full license text under `*.dist-info/licenses/`.\n\n"
        "| Distribution | Version | License | Source |\n|---|---|---|---|\n" + "\n".join(notices) + "\n",
        encoding="utf-8",
    )

    for doc in lock["coreDocs"]:
        dest = out / doc["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(cached(doc["url"], doc["sha256"]))

    manifest = {
        "skill": name,
        "version": web_version(),
        "core": lock["versions"]["core"],
        "automation": lock["versions"]["automation"],
        "wheels": [{"filename": w["filename"], "sha256": w["sha256"]} for w in lock["wheels"]],
    }
    (out / "skill-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def assemble_plugin(skill_tree: Path, lock: dict) -> Path:
    """Wrap the skill as a skills-only plugin: ``plugin.json`` + ``assets/`` + ``skills/<skill>/``."""
    out = DIST / f"{load_json(SOURCES)['pluginName']}-plugin"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copy_source_tree(SOURCE / "plugin", out, lock)
    shutil.copyfile(ROOT / "LICENSE", out / "LICENSE")
    shutil.copytree(skill_tree, out / "skills" / skill_tree.name)
    return out


def write_zip(tree: Path, target: Path, *, top_folder: bool) -> Path:
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(tree.rglob("*")):
            rel = path.relative_to(tree)
            arcname = (Path(tree.name) / rel if top_folder else rel).as_posix()
            if path.is_dir():
                info = zipfile.ZipInfo(arcname + "/", ZIP_EPOCH)
                info.external_attr = (0o40755 << 16) | 0x10
                archive.writestr(info, b"")
                continue
            info = zipfile.ZipInfo(arcname, ZIP_EPOCH)
            mode = 0o755 if path.suffix == ".py" and path.parent.name == "scripts" else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return target


def build(lock: dict) -> tuple[Path, Path]:
    version = web_version()
    skill_tree = assemble(lock)
    skill_zip = write_zip(skill_tree, DIST / f"{load_json(SOURCES)['pluginName']}-skill-{version}.zip", top_folder=True)
    plugin_tree = assemble_plugin(skill_tree, lock)
    plugin_zip = write_zip(plugin_tree, DIST / f"{plugin_tree.name}-{version}.zip", top_folder=False)
    return skill_zip, plugin_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the lock against product identity without network")
    mode.add_argument("--refresh-lock", action="store_true", help="re-pin wheels and docs from PyPI/GitHub")
    args = parser.parse_args(argv)

    if args.refresh_lock:
        lock = refresh_lock()
    else:
        if not LOCK.is_file():
            raise SystemExit(f"missing {LOCK.relative_to(ROOT)}; run --refresh-lock")
        lock = load_json(LOCK)
    check_lock(lock)
    if args.check:
        print(f"[OK] {LOCK.relative_to(ROOT)} pins {lock['versions']}")
        return 0

    for target in build(lock):
        digest = sha256_bytes(target.read_bytes())
        print(f"[OK] {target.relative_to(ROOT)} ({target.stat().st_size} bytes) sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
