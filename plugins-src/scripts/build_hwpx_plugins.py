#!/usr/bin/env python3
"""Build per-host HWPX plugin bundles from the canonical skill source."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
CONFIG = PACKAGING / "hosts.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_skill_md(canonical_text: str, extra_frontmatter: str) -> str:
    if not canonical_text.startswith("---\n"):
        raise SystemExit("canonical SKILL.md is missing YAML frontmatter")
    fence = canonical_text.index("\n---\n", 4)
    frontmatter = canonical_text[4:fence]
    body = canonical_text[fence + len("\n---\n"):]
    if extra_frontmatter.strip():
        frontmatter = frontmatter.rstrip("\n") + "\n" + extra_frontmatter.rstrip("\n")
    return "---\n" + frontmatter + "\n---\n" + body


def copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def record(source_rel: str, source_path: Path, dest_path: Path, transformed: bool) -> dict:
    return {
        "source": source_rel,
        "sourceSha256": sha256(source_path),
        "dest": dest_path.relative_to(ROOT).as_posix(),
        "destSha256": sha256(dest_path),
        "transformed": transformed,
    }


def skill_dir_for(host: dict) -> Path:
    out = ROOT / host["outputDir"]
    return out if host["skillSubdir"] == "." else out / host["skillSubdir"]


def load_identity(config: dict) -> dict:
    identity_path = PACKAGING / config["identityFile"]
    if not identity_path.is_file():
        raise SystemExit(f"missing product identity: {identity_path}")
    return json.loads(identity_path.read_text(encoding="utf-8"))


def host_frontmatter(host: dict, identity: dict) -> str:
    extra = host.get("frontmatterExtra", "").strip()
    if host.get("includeVersionFrontmatter"):
        version = identity["components"]["plugin"]["currentVersion"]
        extra = f"version: {version}" + (f"\n{extra}" if extra else "")
    return extra


def remove_previous_generated_files(out: Path) -> None:
    """Remove only files recorded by the previous build.

    Host skill directories are also legitimate runtime workspaces.  In
    particular, examples write user-owned artifacts below ``examples/out``.
    A blanket ``rmtree(out)`` destroyed those artifacts during a rebuild.
    """
    if not out.exists():
        return
    sync_path = out / "plugin-sync.json"
    if not sync_path.is_file():
        raise SystemExit(
            f"refusing to replace existing bundle without plugin-sync.json: {out}"
        )
    try:
        sync = json.loads(sync_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid previous sync manifest: {sync_path}: {exc}") from exc
    records = sync.get("files")
    if not isinstance(records, list):
        raise SystemExit(f"invalid previous sync records: {sync_path}")

    resolved_out = out.resolve()
    for index, rec in enumerate(records):
        if not isinstance(rec, dict) or not isinstance(rec.get("dest"), str):
            raise SystemExit(f"invalid previous sync record {index}: {sync_path}")
        target = (ROOT / rec["dest"]).resolve()
        try:
            target.relative_to(resolved_out)
        except ValueError:
            raise SystemExit(
                f"previous sync destination escapes bundle {out}: {rec['dest']}"
            ) from None
        if target.is_file() or target.is_symlink():
            target.unlink()
    sync_path.unlink()

    # Prune directories made empty by generated-file removal.  Non-empty
    # runtime/output directories remain untouched.
    directories = sorted(
        (path for path in out.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass


def build_host(host: dict, config: dict, identity: dict) -> None:
    out = ROOT / host["outputDir"]
    remove_previous_generated_files(out)
    skill_dir = skill_dir_for(host)
    skill_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    canonical = ROOT / config["canonicalSkill"]
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        render_skill_md(
            canonical.read_text(encoding="utf-8"),
            host_frontmatter(host, identity),
        ),
        encoding="utf-8",
    )
    records.append(record(config["canonicalSkill"], canonical, skill_md, transformed=True))

    for rel in config["sharedAssets"]:
        src = ROOT / rel
        if not src.is_file():
            raise SystemExit(f"missing shared asset: {rel}")
        dest = skill_dir / rel
        copy_file(src, dest)
        records.append(record(rel, src, dest, transformed=False))

    for tree_rel in config.get("sharedAssetTrees", []):
        tree = ROOT / tree_rel
        if not tree.is_dir():
            raise SystemExit(f"missing shared asset tree: {tree_rel}")
        for src in sorted(path for path in tree.rglob("*") if path.is_file()):
            rel = src.relative_to(ROOT).as_posix()
            dest = skill_dir / rel
            copy_file(src, dest)
            records.append(record(rel, src, dest, transformed=False))

    for manifest in host.get("manifests", []):
        src = PACKAGING / manifest["template"]
        if not src.is_file():
            raise SystemExit(f"missing template: {manifest['template']}")
        dest = out / manifest["dest"]
        copy_file(src, dest)
        records.append(record(f"packaging/{manifest['template']}", src, dest, transformed=False))

    mcp = host["mcp"]
    mcp_src = PACKAGING / mcp["template"]
    if not mcp_src.is_file():
        raise SystemExit(f"missing template: {mcp['template']}")
    mcp_dest = out / mcp["dest"]
    copy_file(mcp_src, mcp_dest)
    records.append(record(f"packaging/{mcp['template']}", mcp_src, mcp_dest, transformed=False))

    if host.get("bundleLauncher"):
        launcher_src = PACKAGING / config["launcherTemplate"]
        launcher_dest = out / "scripts" / config["launcherName"]
        copy_file(launcher_src, launcher_dest)
        launcher_dest.chmod(0o755)
        records.append(record(f"packaging/{config['launcherTemplate']}", launcher_src, launcher_dest, transformed=False))
        compatibility_src = PACKAGING / config["compatibilityLauncherTemplate"]
        compatibility_dest = out / "scripts" / config["compatibilityLauncherName"]
        copy_file(compatibility_src, compatibility_dest)
        compatibility_dest.chmod(0o755)
        records.append(
            record(
                f"packaging/{config['compatibilityLauncherTemplate']}",
                compatibility_src,
                compatibility_dest,
                transformed=False,
            )
        )

    for rec in records:
        text = (ROOT / rec["dest"]).read_text(encoding="utf-8", errors="ignore")
        if "[PLACEHOLDER:" in text:
            raise SystemExit(f"generated file contains a placeholder: {rec['dest']}")

    sync = out / "plugin-sync.json"
    sync.write_text(
        json.dumps(
            {
                "schemaVersion": "hwpx.plugin-sync.v2",
                "plugin": identity["components"]["plugin"]["installedPluginId"],
                "host": host["id"],
                "files": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_repo_root_artifacts(config: dict) -> None:
    for artifact in config.get("repoRootArtifacts", []):
        src = PACKAGING / artifact["template"]
        if not src.is_file():
            raise SystemExit(f"missing template: {artifact['template']}")
        copy_file(src, ROOT / artifact["dest"])


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    identity = load_identity(config)
    for host in config["hosts"]:
        build_host(host, config, identity)
    build_repo_root_artifacts(config)
    print(f"[OK] built {len(config['hosts'])} host bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
