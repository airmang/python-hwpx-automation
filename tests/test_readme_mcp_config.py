from __future__ import annotations

import json
import re
from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]


def test_readme_host_config_is_parseable_and_resolves_distribution_explicitly() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", readme, flags=re.DOTALL)
    configs = [json.loads(block) for block in blocks]
    host = next(config for config in configs if "mcpServers" in config)
    server = host["mcpServers"]["hwpx"]

    # The installable quickstart follows observed public truth while a new
    # candidate is being prepared; publication promotion advances it.
    identity = json.loads(
        (ROOT / "src/hwpx_automation/identity.json").read_text(encoding="utf-8")
    )
    version = identity["releaseState"]["currentPublic"]["primaryApplication"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        f"python-hwpx-automation[mcp]=={version}",
        "hwpx-automation-mcp",
    ]
    assert "HWPX_AUTOMATION_WORKSPACE_ROOTS" in server["env"]
