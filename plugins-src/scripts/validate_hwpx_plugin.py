from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "hwpx-plugin"
PLUGIN_SKILL = PLUGIN / "skills" / "hwpx"


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
        raise SystemExit(f"missing file: {path.relative_to(ROOT)}")


def require_safe_relative_path(raw_path: str, label: str) -> Path:
    posix_path = PurePosixPath(raw_path)
    windows_path = PureWindowsPath(raw_path)
    require(not posix_path.is_absolute(), f"{label} must be relative: {raw_path}")
    require(not windows_path.is_absolute(), f"{label} must be relative: {raw_path}")
    require(".." not in posix_path.parts, f"{label} must not traverse upward: {raw_path}")
    require(".." not in windows_path.parts, f"{label} must not traverse upward: {raw_path}")
    return ROOT / raw_path


def require_under(path: Path, parent: Path, label: str) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    try:
        resolved_path.relative_to(resolved_parent)
    except ValueError:
        raise SystemExit(f"{label} must be under {parent.relative_to(ROOT)}: {path.relative_to(ROOT)}")


def validate_sync_manifest() -> None:
    sync_manifest_path = PLUGIN / "plugin-sync.json"
    require_file(sync_manifest_path)

    sync_manifest = load_json(sync_manifest_path)
    require(
        sync_manifest.get("schemaVersion") == "hwpx.plugin-sync.v1",
        "sync manifest schemaVersion is invalid",
    )
    require(sync_manifest.get("plugin") == "hwpx-plugin", "sync manifest plugin is invalid")

    files = sync_manifest.get("files")
    require(isinstance(files, list), "sync manifest files must be a list")
    manifest_destinations: set[Path] = set()
    for index, record in enumerate(files):
        require(isinstance(record, dict), f"sync manifest file record {index} is invalid")
        source = record.get("source")
        destination = record.get("destination")
        recorded_sha256 = record.get("sha256")
        require(isinstance(source, str) and source, f"sync manifest record {index} source is invalid")
        require(
            isinstance(destination, str) and destination,
            f"sync manifest record {index} destination is invalid",
        )
        require(
            isinstance(recorded_sha256, str) and recorded_sha256,
            f"sync manifest record {index} sha256 is invalid",
        )

        source_path = require_safe_relative_path(source, f"sync manifest record {index} source")
        destination_path = require_safe_relative_path(
            destination,
            f"sync manifest record {index} destination",
        )
        require_under(
            destination_path,
            PLUGIN_SKILL,
            f"sync manifest record {index} destination",
        )
        require_file(source_path)
        require_file(destination_path)
        manifest_destinations.add(destination_path.resolve())
        require(
            sha256(source_path) == recorded_sha256,
            f"sync manifest source drifted: {source}",
        )
        require(
            sha256(destination_path) == recorded_sha256,
            f"sync manifest destination drifted: {destination}",
        )

    actual_destinations = {path.resolve() for path in PLUGIN_SKILL.rglob("*") if path.is_file()}
    require(
        actual_destinations == manifest_destinations,
        "plugin skill files do not match sync manifest destinations",
    )


def validate_launcher_content() -> None:
    launcher = PLUGIN / "scripts" / "hwpx-mcp-server"
    text = launcher.read_text(encoding="utf-8")
    required_fragments = [
        "HWPX_MCP_SERVER_REPO",
        "PYTHON_HWPX_REPO",
        "uv run --project",
        'uvx --from "hwpx-mcp-server==2.2.6"',
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    require(not missing, f"launcher missing expected fragments: {missing}")


def main() -> int:
    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    mcp_path = PLUGIN / ".mcp.json"
    launcher = PLUGIN / "scripts" / "hwpx-mcp-server"
    require_file(manifest_path)
    require_file(mcp_path)
    require_file(launcher)

    manifest = load_json(manifest_path)
    require(manifest.get("name") == "hwpx-plugin", "manifest name is invalid")
    require(manifest.get("version") == "0.1.0", "manifest version is invalid")
    require(manifest.get("skills") == "./skills/", "manifest skills path is invalid")
    require(manifest.get("mcpServers") == "./.mcp.json", "manifest mcpServers path is invalid")
    require("[PLACEHOLDER:" not in json.dumps(manifest), "manifest contains a placeholder")

    mcp = load_json(mcp_path)
    mcp_servers = mcp.get("mcpServers")
    require(isinstance(mcp_servers, dict), "MCP servers config is invalid")
    server = mcp_servers.get("hwpx-mcp-server")
    require(isinstance(server, dict), "MCP server entry is invalid")
    require(server.get("command") == "./scripts/hwpx-mcp-server", "MCP launcher command is invalid")
    require(server.get("cwd") == ".", "MCP server cwd is invalid")
    require(os.access(launcher, os.X_OK), "launcher is not executable")
    validate_sync_manifest()
    validate_launcher_content()
    print("[OK] hwpx-plugin manifest and MCP launcher are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
