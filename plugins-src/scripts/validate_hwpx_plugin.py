from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "hwpx-plugin"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_file(path: Path) -> None:
    if not path.is_file():
        raise AssertionError(f"missing file: {path.relative_to(ROOT)}")


def main() -> int:
    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    mcp_path = PLUGIN / ".mcp.json"
    launcher = PLUGIN / "scripts" / "hwpx-mcp-server"
    assert_file(manifest_path)
    assert_file(mcp_path)
    assert_file(launcher)

    manifest = load_json(manifest_path)
    assert manifest["name"] == "hwpx-plugin"
    assert manifest["version"] == "0.1.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert "[PLACEHOLDER:" not in json.dumps(manifest)

    mcp = load_json(mcp_path)
    server = mcp["mcpServers"]["hwpx-mcp-server"]
    assert server["command"] == "./scripts/hwpx-mcp-server"
    assert server["cwd"] == "."
    assert os.access(launcher, os.X_OK), "launcher is not executable"
    print("[OK] hwpx-plugin manifest and MCP launcher are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
