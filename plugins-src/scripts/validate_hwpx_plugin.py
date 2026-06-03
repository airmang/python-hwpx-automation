#!/usr/bin/env python3
"""Validate every generated HWPX host bundle against packaging/hosts.json."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
CONFIG = PACKAGING / "hosts.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")


def require_safe_relative(raw_path: str, label: str) -> Path:
    posix_path = PurePosixPath(raw_path)
    windows_path = PureWindowsPath(raw_path)
    require(not posix_path.is_absolute(), f"{label} must be relative: {raw_path}")
    require(not windows_path.is_absolute(), f"{label} must be relative: {raw_path}")
    require(".." not in posix_path.parts, f"{label} must not traverse upward: {raw_path}")
    require(".." not in windows_path.parts, f"{label} must not traverse upward: {raw_path}")
    return ROOT / raw_path


def frontmatter_of(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"SKILL.md missing frontmatter: {skill_md}")
    return text.split("\n---\n", 1)[0]


def validate_sync(host: dict, out: Path, skill_dir: Path) -> set[Path]:
    sync_path = out / "plugin-sync.json"
    require_file(sync_path)
    sync = load_json(sync_path)
    require(sync.get("schemaVersion") == "hwpx.plugin-sync.v2", f"{host['id']}: bad sync schemaVersion")
    require(sync.get("host") == host["id"], f"{host['id']}: sync host mismatch")

    files = sync.get("files")
    require(isinstance(files, list) and files, f"{host['id']}: sync files must be a non-empty list")
    skill_dests: set[Path] = set()
    for index, rec in enumerate(files):
        require(isinstance(rec, dict), f"{host['id']}: sync record {index} invalid")
        source = rec.get("source")
        dest = rec.get("dest")
        source_sha = rec.get("sourceSha256")
        dest_sha = rec.get("destSha256")
        for value, name in ((source, "source"), (dest, "dest"), (source_sha, "sourceSha256"), (dest_sha, "destSha256")):
            require(isinstance(value, str) and value, f"{host['id']}: sync record {index} {name} invalid")

        source_path = require_safe_relative(source, f"{host['id']} record {index} source")
        dest_path = require_safe_relative(dest, f"{host['id']} record {index} dest")
        require_file(source_path)
        require_file(dest_path)
        require(sha256(source_path) == source_sha, f"{host['id']}: source drifted (rebuild needed): {source}")
        require(sha256(dest_path) == dest_sha, f"{host['id']}: bundle file tampered: {dest}")
        try:
            dest_path.resolve().relative_to(skill_dir.resolve())
            skill_dests.add(dest_path.resolve())
        except ValueError:
            pass
    return skill_dests


def validate_skill_files_match(host: dict, skill_dir: Path, recorded: set[Path]) -> None:
    # When skillSubdir == "." the bundle root is the skill dir, so the bundle's own
    # plugin-sync.json and INSTALL-mcp.md live alongside skill files. plugin-sync.json
    # is never self-recorded; exclude it. Everything else under skill_dir must be recorded.
    actual = {
        p.resolve()
        for p in skill_dir.rglob("*")
        if p.is_file() and p.name != "plugin-sync.json"
    }
    require(actual == recorded, f"{host['id']}: skill files do not match sync manifest")


def validate_no_placeholder(path: Path, host_id: str) -> None:
    require("[PLACEHOLDER:" not in path.read_text(encoding="utf-8"), f"{host_id}: placeholder in {path}")


def validate_launcher(out: Path, host_id: str) -> None:
    launcher = out / "scripts" / "hwpx-mcp-server"
    require_file(launcher)
    require(os.access(launcher, os.X_OK), f"{host_id}: launcher not executable")
    text = launcher.read_text(encoding="utf-8")
    fragments = [
        "find_stack_root",
        "HWPX_MCP_SERVER_REPO",
        "PYTHON_HWPX_REPO",
        "uv run --project",
        'SERVER_PACKAGE="hwpx-mcp-server==2.3.2"',
        ".hwpx-mcp-server-venv",
        "uv pip install",
        'uvx --from "${SERVER_PACKAGE}"',
    ]
    missing = [fragment for fragment in fragments if fragment not in text]
    require(not missing, f"{host_id}: launcher missing fragments: {missing}")


def validate_host(host: dict, config: dict) -> None:
    out = ROOT / host["outputDir"]
    require(out.is_dir(), f"{host['id']}: missing output dir {host['outputDir']}")
    skill_dir = out if host["skillSubdir"] == "." else out / host["skillSubdir"]

    skill_md = skill_dir / "SKILL.md"
    require_file(skill_md)
    validate_no_placeholder(skill_md, host["id"])
    fm = frontmatter_of(skill_md)
    require("name: hwpx" in fm, f"{host['id']}: SKILL.md missing name")
    require("description:" in fm, f"{host['id']}: SKILL.md missing description")
    if host.get("frontmatterExtra", "").strip():
        require("version:" in fm, f"{host['id']}: SKILL.md missing required version")
        require("hermes:" in fm and "tags:" in fm, f"{host['id']}: SKILL.md missing metadata.hermes.tags")
    else:
        require("\nversion:" not in fm, f"{host['id']}: SKILL.md must not declare version")

    for rel in config["sharedAssets"]:
        require_file(skill_dir / rel)

    for manifest in host.get("manifests", []):
        manifest_path = out / manifest["dest"]
        require_file(manifest_path)
        validate_no_placeholder(manifest_path, host["id"])
        data = load_json(manifest_path)
        if host["id"] == "claude":
            require(data.get("name") == "hwpx-plugin", "claude: manifest name invalid")
            require(data.get("skills") == "./skills/", "claude: manifest skills invalid")
            require(data.get("mcpServers") == "./.mcp.json", "claude: manifest mcpServers invalid")
        elif host["id"] == "codex":
            require(data.get("name") == "hwpx-plugin", "codex: manifest name invalid")
            require(data.get("skills") == "./skills/", "codex: manifest skills invalid")
            require(data.get("mcpServers") == "./.mcp.json", "codex: manifest mcpServers invalid")
        elif host["id"] == "openclaw":
            require(data.get("id") == "hwpx-plugin", "openclaw: manifest id invalid")
            require(data.get("skills") == ["./skills"], "openclaw: manifest skills invalid")
            schema = data.get("configSchema")
            require(isinstance(schema, dict) and schema.get("type") == "object", "openclaw: configSchema invalid")
            require(schema.get("additionalProperties") is False, "openclaw: configSchema must set additionalProperties false")

    mcp = host["mcp"]
    mcp_path = out / mcp["dest"]
    require_file(mcp_path)
    if mcp["strategy"] == "bundled":
        mcp_data = load_json(mcp_path)
        server = mcp_data.get("mcpServers", {}).get("hwpx-mcp-server")
        require(isinstance(server, dict), f"{host['id']}: .mcp.json missing hwpx-mcp-server")
        command = server.get("command", "")
        require("hwpx-mcp-server" in command, f"{host['id']}: .mcp.json command invalid")
        if host["id"] == "claude":
            require("${CLAUDE_PLUGIN_ROOT}" in command, "claude: .mcp.json must use ${CLAUDE_PLUGIN_ROOT}")
        if host["id"] == "codex":
            require(command == "./scripts/hwpx-mcp-server", "codex: .mcp.json command must be relative")
            require(server.get("cwd") == ".", "codex: .mcp.json cwd must be '.'")
    else:
        text = mcp_path.read_text(encoding="utf-8")
        require("mcp_servers" in text or "hwpx-mcp-server" in text, f"{host['id']}: INSTALL-mcp.md missing MCP guidance")

    if host.get("bundleLauncher"):
        validate_launcher(out, host["id"])

    recorded = validate_sync(host, out, skill_dir)
    validate_skill_files_match(host, skill_dir, recorded)


def validate_marketplace(config: dict) -> None:
    for artifact in config.get("repoRootArtifacts", []):
        path = ROOT / artifact["dest"]
        require_file(path)
        if path.name == "marketplace.json":
            data = load_json(path)
            require(isinstance(data.get("name"), str) and data["name"], "marketplace: name invalid")
            plugins = data.get("plugins")
            require(isinstance(plugins, list) and plugins, "marketplace: plugins invalid")
            entry = plugins[0]
            require(entry.get("name") == "hwpx-plugin", "marketplace: plugin name invalid")
            if artifact["dest"].startswith(".claude-plugin/"):
                require(isinstance(data.get("owner"), dict), "claude marketplace: owner invalid")
                require(entry.get("source") == "./plugins/claude/hwpx-plugin", "claude marketplace: plugin source invalid")
            elif artifact["dest"].startswith(".agents/plugins/"):
                source = entry.get("source")
                require(isinstance(source, dict), "codex marketplace: source invalid")
                require(source.get("source") == "local", "codex marketplace: source type invalid")
                require(source.get("path") == "./plugins/codex/hwpx-plugin", "codex marketplace: plugin path invalid")
                policy = entry.get("policy")
                require(isinstance(policy, dict), "codex marketplace: policy invalid")
                require(policy.get("installation") == "AVAILABLE", "codex marketplace: installation policy invalid")
                require(policy.get("authentication") == "ON_INSTALL", "codex marketplace: authentication policy invalid")
                require(entry.get("category") == "Productivity", "codex marketplace: category invalid")


def main() -> int:
    config = load_json(CONFIG)
    for host in config["hosts"]:
        validate_host(host, config)
    validate_marketplace(config)
    print(f"[OK] validated {len(config['hosts'])} host bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
