# HWPX Plugin Distribution Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repo-local `hwpx-plugin` Codex plugin that bundles the HWPX skill surface and an MCP launcher so a user can install one plugin for HWPX document workflows.

**Architecture:** Keep `hwpx-skill` as the plugin source repository and create `plugins/hwpx-plugin` inside it. The plugin copies the existing `SKILL.md`, `references`, `examples`, and `scripts` into `plugins/hwpx-plugin/skills/hwpx/`, while a generated sync manifest and test prevent drift. The plugin MCP launcher runs `hwpx-mcp-server` from local sibling checkouts during development and falls back to pinned package execution for installed use.

**Tech Stack:** Codex plugin manifest, `.mcp.json`, Python 3.10+, `uv`, shell launcher, pytest-free Python smoke scripts, `python-hwpx`, `hwpx-mcp-server`.

---

## File Structure

- Create: `plugins/hwpx-plugin/.codex-plugin/plugin.json`
  - Codex plugin manifest, no placeholder fields, references `./skills/` and `./.mcp.json`.
- Create: `plugins/hwpx-plugin/.mcp.json`
  - Companion MCP config pointing at `./scripts/hwpx-mcp-server`.
- Create: `plugins/hwpx-plugin/scripts/hwpx-mcp-server`
  - Fixed launcher that prefers local sibling repos and otherwise runs pinned packages.
- Create: `plugins/hwpx-plugin/skills/hwpx/SKILL.md`
  - Copied plugin-facing HWPX skill body.
- Create directories/files under `plugins/hwpx-plugin/skills/hwpx/references`, `examples`, and `scripts`
  - Synced copies of current HWPX skill assets.
- Create: `scripts/sync_hwpx_plugin.py`
  - Deterministic sync script from repo root skill assets into plugin skill assets.
- Create: `scripts/validate_hwpx_plugin.py`
  - Local validation for manifest, MCP launcher, copied skill assets, and sync manifest.
- Create: `plugins/hwpx-plugin/plugin-sync.json`
  - Machine-readable source-to-plugin file mapping and checksum record.
- Modify: `README.md`
  - Add install/update/smoke instructions for `hwpx-plugin`.
- Modify: `references/api.md`
  - Add plugin-specific handoff note and MCP launcher dependency behavior.
- Modify: `../hwpx-mcp-server/README.md`
  - Document that `hwpx-plugin` can launch this server as companion MCP.
- Modify: `../python-hwpx/README.md`
  - Document that plugin users consume `python-hwpx` through `hwpx-mcp-server` and local quickcheck paths.

## Task 1: Scaffold Plugin Manifest And MCP Launcher

**Files:**
- Create: `plugins/hwpx-plugin/.codex-plugin/plugin.json`
- Create: `plugins/hwpx-plugin/.mcp.json`
- Create: `plugins/hwpx-plugin/scripts/hwpx-mcp-server`
- Test: `scripts/validate_hwpx_plugin.py`

- [ ] **Step 1: Create the plugin directories**

Run:

```bash
mkdir -p plugins/hwpx-plugin/.codex-plugin plugins/hwpx-plugin/scripts plugins/hwpx-plugin/skills/hwpx
```

Expected: directories exist and `git status --short plugins/hwpx-plugin` shows only untracked plugin paths.

- [ ] **Step 2: Add the plugin manifest**

Write `plugins/hwpx-plugin/.codex-plugin/plugin.json`:

```json
{
  "name": "hwpx-plugin",
  "version": "0.1.0",
  "description": "HWPX document generation, validation, visual-review handoff, and MCP tooling for Codex.",
  "author": {
    "name": "Kohkyuhyun",
    "email": "kokyuhyun@hotmail.com",
    "url": "https://github.com/airmang"
  },
  "homepage": "https://github.com/airmang/hwpx-skill",
  "repository": "https://github.com/airmang/hwpx-skill",
  "license": "Apache-2.0",
  "keywords": [
    "codex",
    "hwpx",
    "mcp",
    "document-automation",
    "korean-documents"
  ],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "HWPX Plugin",
    "shortDescription": "Create and validate HWPX documents from Codex.",
    "longDescription": "HWPX Plugin bundles the HWPX authoring skill, local examples, visual-review handoff scripts, and a companion MCP launcher for HWPX generation and validation workflows.",
    "developerName": "Kohkyuhyun",
    "category": "Productivity",
    "capabilities": [
      "Interactive",
      "Write"
    ],
    "defaultPrompt": [
      "$hwpx create operating plan",
      "$hwpx inspect file quality",
      "$hwpx record visual review"
    ],
    "brandColor": "#2563EB"
  }
}
```

- [ ] **Step 3: Add the MCP config**

Write `plugins/hwpx-plugin/.mcp.json`:

```json
{
  "mcpServers": {
    "hwpx-mcp-server": {
      "command": "./scripts/hwpx-mcp-server",
      "args": [],
      "cwd": ".",
      "env": {
        "HWPX_MCP_ADVANCED": "0",
        "HWPX_MCP_AUTOBACKUP": "1"
      }
    }
  }
}
```

- [ ] **Step 4: Add the launcher**

Write `plugins/hwpx-plugin/scripts/hwpx-mcp-server` and make it executable:

```bash
#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_REPO="$(cd "$PLUGIN_DIR/../.." && pwd)"
DEFAULT_STACK_ROOT="$(cd "$SKILL_REPO/.." && pwd)"

MCP_REPO="${HWPX_MCP_SERVER_REPO:-$DEFAULT_STACK_ROOT/hwpx-mcp-server}"
PYTHON_HWPX_REPO="${PYTHON_HWPX_REPO:-$DEFAULT_STACK_ROOT/python-hwpx}"

if command -v uv >/dev/null 2>&1 && [ -f "$MCP_REPO/pyproject.toml" ] && [ -f "$PYTHON_HWPX_REPO/pyproject.toml" ]; then
  exec uv run --project "$MCP_REPO" --with-editable "$PYTHON_HWPX_REPO" --with-editable "$MCP_REPO" hwpx-mcp-server
fi

if command -v uvx >/dev/null 2>&1; then
  exec uvx --from "hwpx-mcp-server==2.2.6" hwpx-mcp-server
fi

echo "hwpx-plugin requires uv or uvx. Install uv, or set HWPX_MCP_SERVER_REPO and PYTHON_HWPX_REPO to local checkouts." >&2
exit 127
```

Run:

```bash
chmod +x plugins/hwpx-plugin/scripts/hwpx-mcp-server
```

Expected: `test -x plugins/hwpx-plugin/scripts/hwpx-mcp-server` exits 0.

- [ ] **Step 5: Add a first manifest validator**

Write `scripts/validate_hwpx_plugin.py`:

```python
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
```

- [ ] **Step 6: Run validation**

Run:

```bash
python3 scripts/validate_hwpx_plugin.py
```

Expected:

```text
[OK] hwpx-plugin manifest and MCP launcher are valid
```

- [ ] **Step 7: Commit**

Run:

```bash
git add plugins/hwpx-plugin/.codex-plugin/plugin.json plugins/hwpx-plugin/.mcp.json plugins/hwpx-plugin/scripts/hwpx-mcp-server scripts/validate_hwpx_plugin.py
git commit -m "feat: scaffold hwpx codex plugin"
```

## Task 2: Sync The Existing Skill Surface Into The Plugin

**Files:**
- Create: `scripts/sync_hwpx_plugin.py`
- Create: `plugins/hwpx-plugin/plugin-sync.json`
- Create/Update: `plugins/hwpx-plugin/skills/hwpx/**`
- Modify: `scripts/validate_hwpx_plugin.py`

- [ ] **Step 1: Add the sync script**

Write `scripts/sync_hwpx_plugin.py`:

```python
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SKILL = ROOT / "plugins" / "hwpx-plugin" / "skills" / "hwpx"
SYNC_MANIFEST = ROOT / "plugins" / "hwpx-plugin" / "plugin-sync.json"

SOURCES = [
    Path("SKILL.md"),
    Path("README.md"),
    Path("references/api.md"),
    Path("examples/01_create_and_save.py"),
    Path("examples/02_extract_and_inspect.py"),
    Path("examples/03_template_replace.py"),
    Path("examples/04_create_proposal.py"),
    Path("examples/05_mcp_quality_pipeline.md"),
    Path("examples/06_create_from_document_plan.py"),
    Path("examples/06_mcp_document_plan.md"),
    Path("examples/07_create_operating_plan.py"),
    Path("examples/07_mcp_operating_plan.md"),
    Path("examples/08_template_formfit.py"),
    Path("examples/08_mcp_template_formfit.md"),
    Path("examples/09_visual_review_loop.md"),
    Path("scripts/fix_namespaces.py"),
    Path("scripts/quickcheck.py"),
    Path("scripts/text_extract.py"),
    Path("scripts/visual_review.py"),
    Path("scripts/zip_replace_all.py"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def destination_for(source: Path) -> Path:
    if source.name == "SKILL.md":
        return PLUGIN_SKILL / "SKILL.md"
    return PLUGIN_SKILL / source


def main() -> int:
    records = []
    for relative in SOURCES:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"missing source: {relative}")
        destination = destination_for(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append(
            {
                "source": relative.as_posix(),
                "destination": destination.relative_to(ROOT).as_posix(),
                "sha256": sha256(source),
            }
        )

    SYNC_MANIFEST.write_text(
        json.dumps(
            {
                "schemaVersion": "hwpx.plugin-sync.v1",
                "plugin": "hwpx-plugin",
                "sourceRoot": ".",
                "files": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[OK] synced {len(records)} files into plugins/hwpx-plugin/skills/hwpx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the sync**

Run:

```bash
python3 scripts/sync_hwpx_plugin.py
```

Expected:

```text
[OK] synced 19 files into plugins/hwpx-plugin/skills/hwpx
```

- [ ] **Step 3: Extend validation to detect drift**

Append this code above `main()` in `scripts/validate_hwpx_plugin.py`:

```python
import hashlib


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sync_manifest() -> None:
    sync_path = PLUGIN / "plugin-sync.json"
    assert_file(sync_path)
    sync = load_json(sync_path)
    assert sync["schemaVersion"] == "hwpx.plugin-sync.v1"
    assert sync["plugin"] == "hwpx-plugin"
    for record in sync["files"]:
        source = ROOT / record["source"]
        destination = ROOT / record["destination"]
        assert_file(source)
        assert_file(destination)
        if sha256(source) != record["sha256"]:
            raise AssertionError(f"source changed without sync: {record['source']}")
        if sha256(destination) != record["sha256"]:
            raise AssertionError(f"plugin copy drifted: {record['destination']}")
```

Then add this line inside `main()` before the final print:

```python
    validate_sync_manifest()
```

- [ ] **Step 4: Run validation**

Run:

```bash
python3 scripts/validate_hwpx_plugin.py
```

Expected:

```text
[OK] hwpx-plugin manifest and MCP launcher are valid
```

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/sync_hwpx_plugin.py scripts/validate_hwpx_plugin.py plugins/hwpx-plugin/plugin-sync.json plugins/hwpx-plugin/skills/hwpx
git commit -m "feat: sync hwpx skill into plugin"
```

## Task 3: Add Plugin Install And Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `references/api.md`
- Modify: `../hwpx-mcp-server/README.md`
- Modify: `../python-hwpx/README.md`

- [ ] **Step 1: Update `README.md`**

Add this section after the quickcheck section:

```markdown
## Codex plugin bundle

This repository ships a local Codex plugin at `plugins/hwpx-plugin`.
The plugin exposes the same HWPX skill surface plus a companion MCP launcher.

Development smoke:

```bash
python3 scripts/sync_hwpx_plugin.py
python3 scripts/validate_hwpx_plugin.py
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

The plugin MCP launcher prefers sibling local checkouts:

- `../hwpx-mcp-server`
- `../python-hwpx`

Override them with `HWPX_MCP_SERVER_REPO` and `PYTHON_HWPX_REPO` when the checkout layout differs.
If local checkouts are unavailable, the launcher falls back to `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server`.

After changing plugin files, update the manifest cachebuster with the Codex plugin creator helper and reinstall from the selected local marketplace. Start a new Codex thread before testing newly installed skills or MCP tools.
```

- [ ] **Step 2: Update `references/api.md`**

Add this section near the MCP workflow section:

```markdown
### Codex plugin bundle

`plugins/hwpx-plugin` is the single-plugin distribution surface for this skill stack.
It contains the `hwpx` skill assets and an MCP config for `hwpx-mcp-server`.

For development checkouts, the launcher resolves:

1. `HWPX_MCP_SERVER_REPO` or `../hwpx-mcp-server`
2. `PYTHON_HWPX_REPO` or `../python-hwpx`
3. `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server` fallback

Run `python3 scripts/sync_hwpx_plugin.py` before plugin validation whenever `SKILL.md`, `references`, `examples`, or skill scripts change.
```

- [ ] **Step 3: Update `../hwpx-mcp-server/README.md`**

Add this paragraph under the MCP setup section:

```markdown
### Codex plugin companion launcher

The `hwpx-skill` repository includes `plugins/hwpx-plugin`, which can launch this MCP server as a companion server. In local development, set `HWPX_MCP_SERVER_REPO=/absolute/path/to/hwpx-mcp-server` and `PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx` when the three repositories are not sibling directories. The plugin launcher uses `uv run --project "$HWPX_MCP_SERVER_REPO" --with-editable "$PYTHON_HWPX_REPO" --with-editable "$HWPX_MCP_SERVER_REPO" hwpx-mcp-server`.
```

- [ ] **Step 4: Update `../python-hwpx/README.md`**

Add this paragraph near the MCP or usage section:

```markdown
### Codex plugin usage

The `hwpx-plugin` bundle in the `hwpx-skill` repository consumes `python-hwpx` through `hwpx-mcp-server` and local quickcheck scripts. During local development, set `PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx` so the plugin launcher uses this checkout as an editable dependency.
```

- [ ] **Step 5: Run documentation grep checks**

Run:

```bash
rg -n "hwpx-plugin|HWPX_MCP_SERVER_REPO|PYTHON_HWPX_REPO" README.md references/api.md ../hwpx-mcp-server/README.md ../python-hwpx/README.md
```

Expected: matches appear in all four files.

- [ ] **Step 6: Commit**

Run:

```bash
git add README.md references/api.md ../hwpx-mcp-server/README.md ../python-hwpx/README.md
git commit -m "docs: document hwpx plugin bundle"
```

## Task 4: Validate Plugin And MCP Startup

**Files:**
- Modify: `scripts/validate_hwpx_plugin.py`
- Test: `plugins/hwpx-plugin/scripts/hwpx-mcp-server`

- [ ] **Step 1: Add launcher smoke validation**

Append this function to `scripts/validate_hwpx_plugin.py`:

```python
def validate_launcher_content() -> None:
    launcher = PLUGIN / "scripts" / "hwpx-mcp-server"
    text = launcher.read_text(encoding="utf-8")
    required = [
        "HWPX_MCP_SERVER_REPO",
        "PYTHON_HWPX_REPO",
        "uv run --project",
        "uvx --from \"hwpx-mcp-server==2.2.6\"",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(f"launcher missing expected fragments: {missing}")
```

Then add this line inside `main()` before the final print:

```python
    validate_launcher_content()
```

- [ ] **Step 2: Run plugin validation**

Run:

```bash
python3 scripts/validate_hwpx_plugin.py
```

Expected:

```text
[OK] hwpx-plugin manifest and MCP launcher are valid
```

- [ ] **Step 3: Run MCP tool discovery smoke**

Run from `hwpx-skill`:

```bash
python3 - <<'PY'
import json
import subprocess
import sys

proc = subprocess.Popen(
    ["plugins/hwpx-plugin/scripts/hwpx-mcp-server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "hwpx-plugin-smoke", "version": "0.1.0"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]
for payload in requests:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()

seen = []
while len(seen) < 2:
    line = proc.stdout.readline()
    if not line:
        break
    seen.append(json.loads(line))

proc.terminate()
stderr = proc.stderr.read()
if len(seen) < 2:
    raise SystemExit(f"expected two MCP responses, got {seen!r}, stderr={stderr}")
tools = seen[1]["result"]["tools"]
names = {tool["name"] for tool in tools}
required = {"validate_document_plan", "create_document_from_plan", "inspect_operating_plan_quality"}
missing = required - names
if missing:
    raise SystemExit(f"missing tools: {sorted(missing)}")
print("[OK] plugin MCP server exposes core HWPX tools")
PY
```

Expected:

```text
[OK] plugin MCP server exposes core HWPX tools
```

- [ ] **Step 4: Run full skill quickcheck**

Run:

```bash
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

Expected: output contains all of:

```text
[OK] document-plan generation workflow passed
[OK] operating-plan document-plan workflow passed
[OK] template form-fit workflow passed
[OK] visual-review fallback evidence workflow passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/validate_hwpx_plugin.py
git commit -m "test: validate hwpx plugin launcher"
```

## Task 5: Release Handoff And Wily Evidence

**Files:**
- Create: `docs/release-handoff-2026-05-30-hwpx-plugin.md`

- [ ] **Step 1: Create release handoff**

Write `docs/release-handoff-2026-05-30-hwpx-plugin.md`:

```markdown
# HWPX Plugin Release Handoff - 2026-05-30

Stage: hwpx display S-004 / server S-045

## Bundle

- Plugin path: `plugins/hwpx-plugin`
- Skill path: `plugins/hwpx-plugin/skills/hwpx`
- MCP config: `plugins/hwpx-plugin/.mcp.json`
- MCP launcher: `plugins/hwpx-plugin/scripts/hwpx-mcp-server`

## Verification

- `python3 scripts/sync_hwpx_plugin.py`
- `python3 scripts/validate_hwpx_plugin.py`
- MCP tool discovery smoke for `validate_document_plan`, `create_document_from_plan`, and `inspect_operating_plan_quality`
- `uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review`

## Residual Notes

- `visual_review_required=true` remains a final submission gate.
- Local development expects sibling checkouts or `HWPX_MCP_SERVER_REPO` and `PYTHON_HWPX_REPO`.
- Start a new Codex thread after installing or reinstalling the plugin so new skills and MCP tools load.
```

- [ ] **Step 2: Commit release handoff**

Run:

```bash
git add docs/release-handoff-2026-05-30-hwpx-plugin.md
git commit -m "docs: record hwpx plugin release handoff"
```

- [ ] **Step 3: Run final verification**

Run:

```bash
python3 scripts/validate_hwpx_plugin.py
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

Expected: both commands exit 0.

- [ ] **Step 4: Record Wily evidence**

Use `add_stage_note(stage_id="S-045", ...)` with:

```json
{
  "verification": [
    "python3 scripts/validate_hwpx_plugin.py passed",
    "MCP tool discovery smoke passed",
    "uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review passed"
  ],
  "changed_files": [
    "plugins/hwpx-plugin/.codex-plugin/plugin.json",
    "plugins/hwpx-plugin/.mcp.json",
    "plugins/hwpx-plugin/scripts/hwpx-mcp-server",
    "plugins/hwpx-plugin/skills/hwpx/**",
    "plugins/hwpx-plugin/plugin-sync.json",
    "scripts/sync_hwpx_plugin.py",
    "scripts/validate_hwpx_plugin.py",
    "README.md",
    "references/api.md",
    "../hwpx-mcp-server/README.md",
    "../python-hwpx/README.md",
    "docs/release-handoff-2026-05-30-hwpx-plugin.md"
  ],
  "residual_risks": [
    "Installed plugin testing requires reinstall and a new Codex thread.",
    "Final document submission claims still require observed visual review evidence."
  ]
}
```

## Self-Review

- Spec coverage: The plan covers bundle shape, manifest, skill sync, MCP launcher, local dependency behavior, update/install docs, validation, smoke, and release handoff.
- Placeholder scan: The plan contains no blocked placeholder instructions.
- Type consistency: Plugin name is consistently `hwpx-plugin`; skill namespace path is consistently `plugins/hwpx-plugin/skills/hwpx`; MCP server id is consistently `hwpx-mcp-server`.
