from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_readme_host_config_is_parseable_and_resolves_distribution_explicitly() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", readme, flags=re.DOTALL)
    configs = [json.loads(block) for block in blocks]
    host = next(config for config in configs if "mcpServers" in config)
    server = host["mcpServers"]["hwpx"]

    # The quickstart pin must track the checkout's own version: a frozen
    # literal here kept the README example fossilized at 6.1.3 for two
    # major trains.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        f"python-hwpx-automation[mcp]=={version}",
        "hwpx-automation-mcp",
    ]
    assert "HWPX_AUTOMATION_WORKSPACE_ROOTS" in server["env"]
