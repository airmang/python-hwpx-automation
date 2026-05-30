from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "hwpx-plugin"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_file(path: Path) -> None:
    if not path.is_file():
        raise AssertionError(f"missing file: {path.relative_to(ROOT)}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_sync_manifest() -> None:
    sync_manifest_path = PLUGIN / "plugin-sync.json"
    assert_file(sync_manifest_path)

    sync_manifest = load_json(sync_manifest_path)
    require(
        sync_manifest.get("schemaVersion") == "hwpx.plugin-sync.v1",
        "sync manifest schemaVersion is invalid",
    )
    require(sync_manifest.get("plugin") == "hwpx-plugin", "sync manifest plugin is invalid")

    files = sync_manifest.get("files")
    require(isinstance(files, list), "sync manifest files must be a list")
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

        source_path = ROOT / source
        destination_path = ROOT / destination
        assert_file(source_path)
        assert_file(destination_path)
        require(
            sha256(source_path) == recorded_sha256,
            f"sync manifest source drifted: {source}",
        )
        require(
            sha256(destination_path) == recorded_sha256,
            f"sync manifest destination drifted: {destination}",
        )


def main() -> int:
    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    mcp_path = PLUGIN / ".mcp.json"
    launcher = PLUGIN / "scripts" / "hwpx-mcp-server"
    assert_file(manifest_path)
    assert_file(mcp_path)
    assert_file(launcher)

    manifest = load_json(manifest_path)
    require(manifest["name"] == "hwpx-plugin", "manifest name is invalid")
    require(manifest["version"] == "0.1.0", "manifest version is invalid")
    require(manifest["skills"] == "./skills/", "manifest skills path is invalid")
    require(manifest["mcpServers"] == "./.mcp.json", "manifest mcpServers path is invalid")
    require("[PLACEHOLDER:" not in json.dumps(manifest), "manifest contains a placeholder")

    mcp = load_json(mcp_path)
    server = mcp["mcpServers"]["hwpx-mcp-server"]
    require(server["command"] == "./scripts/hwpx-mcp-server", "MCP launcher command is invalid")
    require(server["cwd"] == ".", "MCP server cwd is invalid")
    require(os.access(launcher, os.X_OK), "launcher is not executable")
    validate_sync_manifest()
    print("[OK] hwpx-plugin manifest and MCP launcher are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
