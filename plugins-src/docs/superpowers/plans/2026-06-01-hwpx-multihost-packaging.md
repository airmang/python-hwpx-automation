# HWPX Multi-Host Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate per-host plugin bundles for Claude Code, Codex, OpenClaw, and Hermes Agent from a single canonical HWPX skill source, with committed bundles guarded by sha256 drift records and a reproducible-build check.

**Architecture:** Canonical skill assets stay at the repo root. `packaging/hosts.json` + `packaging/templates/` declare host differences as data. `scripts/build_hwpx_plugins.py` reads the canonical SKILL.md, injects per-host frontmatter, copies shared assets, and renders host manifests + MCP wiring into `plugins/<host>/`. `scripts/validate_hwpx_plugin.py` validates every host target. Drift is caught two ways: per-file sha256 records in each `plugin-sync.json`, and a `build → git diff --exit-code` reproducibility check.

**Tech Stack:** Python 3.10+ (stdlib only), bash launcher, JSON manifests, `uv`/`uvx`, `python-hwpx`, `hwpx-mcp-server`. No new third-party dependencies.

**Design spec:** `docs/superpowers/specs/2026-06-01-hwpx-multihost-packaging-design.md`

---

## File Structure

- Create: `packaging/hosts.json` — host target definitions (output dirs, skill paths, frontmatter overlays, manifest/MCP template refs).
- Create: `packaging/templates/hwpx-mcp-server` — depth-robust MCP launcher (canonical source; copied into bundled hosts).
- Create: `packaging/templates/claude.plugin.json`, `claude.mcp.json`, `claude.marketplace.json`
- Create: `packaging/templates/codex.plugin.json`, `codex.mcp.json`
- Create: `packaging/templates/openclaw.plugin.json`, `openclaw.mcp-install.md`
- Create: `packaging/templates/hermes.mcp-install.md`
- Create: `scripts/build_hwpx_plugins.py` — multi-host builder.
- Rewrite: `scripts/validate_hwpx_plugin.py` — multi-host validator.
- Delete: `scripts/sync_hwpx_plugin.py` — superseded by the builder.
- Generated + committed: `plugins/claude/hwpx-plugin/**`, `plugins/codex/hwpx-plugin/**`, `plugins/openclaw/hwpx-plugin/**`, `plugins/hermes/hwpx/**`, `.claude-plugin/marketplace.json`
- Delete: `plugins/hwpx-plugin/**` — relocated to `plugins/codex/hwpx-plugin/`.
- Modify: `README.md`, `references/api.md`, `../hwpx-mcp-server/README.md`, `../python-hwpx/README.md` — multi-host install docs + repo URL rename to `hwpx-plugins`.
- Create: `docs/release-handoff-2026-06-01-hwpx-multihost.md`

**Testing note:** This pipeline has no pytest suite. The test gate is `scripts/validate_hwpx_plugin.py` plus the MCP discovery smoke and `scripts/quickcheck.py`, exactly as the existing single-host bundle was verified. Each task ends with a concrete runnable check.

---

## Task 1: Depth-Robust MCP Launcher Template

The current launcher resolves the stack root with a fixed `$PLUGIN_DIR/../..`, which assumes the bundle sits at `plugins/hwpx-plugin/`. Bundles now live one level deeper (`plugins/<host>/hwpx-plugin/`), so the launcher must find the stack root by walking upward.

**Files:**
- Create: `packaging/templates/hwpx-mcp-server`

- [ ] **Step 1: Write the launcher**

Write `packaging/templates/hwpx-mcp-server`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_stack_root() {
  local dir="$1"
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/hwpx-mcp-server/pyproject.toml" ] && [ -f "$dir/python-hwpx/pyproject.toml" ]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

STACK_ROOT=""
if ! STACK_ROOT="$(find_stack_root "$SCRIPT_DIR")"; then
  STACK_ROOT=""
fi

MCP_REPO="${HWPX_MCP_SERVER_REPO:-${STACK_ROOT:+$STACK_ROOT/hwpx-mcp-server}}"
PYTHON_HWPX_REPO="${PYTHON_HWPX_REPO:-${STACK_ROOT:+$STACK_ROOT/python-hwpx}}"

if command -v uv >/dev/null 2>&1 \
  && [ -n "${MCP_REPO}" ] && [ -f "${MCP_REPO}/pyproject.toml" ] \
  && [ -n "${PYTHON_HWPX_REPO}" ] && [ -f "${PYTHON_HWPX_REPO}/pyproject.toml" ]; then
  exec uv run --project "${MCP_REPO}" --with-editable "${PYTHON_HWPX_REPO}" --with-editable "${MCP_REPO}" hwpx-mcp-server
fi

if command -v uvx >/dev/null 2>&1; then
  exec uvx --from "hwpx-mcp-server==2.2.6" hwpx-mcp-server
fi

echo "hwpx-plugin requires uv or uvx. Install uv, or set HWPX_MCP_SERVER_REPO and PYTHON_HWPX_REPO to local checkouts." >&2
exit 127
```

- [ ] **Step 2: Make it executable**

Run:

```bash
chmod +x packaging/templates/hwpx-mcp-server
```

Expected: `test -x packaging/templates/hwpx-mcp-server` exits 0.

- [ ] **Step 3: Functional test — fallback path from a deep directory**

This proves the launcher does not crash on path math at the new depth and reaches the `uvx` fallback when there is no local stack and no `uv`. Run:

```bash
python3 - <<'PY'
import os, subprocess, tempfile, textwrap, shutil
from pathlib import Path

launcher = Path("packaging/templates/hwpx-mcp-server").resolve()
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # deep bundle location with NO sibling repos anywhere above it
    deep = tmp / "plugins" / "claude" / "hwpx-plugin" / "scripts"
    deep.mkdir(parents=True)
    shutil.copy2(launcher, deep / "hwpx-mcp-server")
    (deep / "hwpx-mcp-server").chmod(0o755)
    # stub uvx that echoes its args, stub PATH to exclude uv
    binstub = tmp / "bin"
    binstub.mkdir()
    (binstub / "uvx").write_text("#!/usr/bin/env bash\necho UVX_CALLED \"$@\"\n")
    (binstub / "uvx").chmod(0o755)
    env = {"PATH": str(binstub), "HOME": str(tmp)}
    out = subprocess.run([str(deep / "hwpx-mcp-server")], capture_output=True, text=True, env=env)
    assert "UVX_CALLED --from hwpx-mcp-server==2.2.6 hwpx-mcp-server" in out.stdout, (out.stdout, out.stderr)
    print("[OK] launcher reaches uvx fallback from deep bundle path")
PY
```

Expected:

```text
[OK] launcher reaches uvx fallback from deep bundle path
```

- [ ] **Step 4: Functional test — local stack detection by walking up**

Run:

```bash
python3 - <<'PY'
import subprocess, tempfile, shutil
from pathlib import Path

launcher = Path("packaging/templates/hwpx-mcp-server").resolve()
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "hwpx-mcp-server").mkdir()
    (tmp / "hwpx-mcp-server" / "pyproject.toml").write_text("[project]\n")
    (tmp / "python-hwpx").mkdir()
    (tmp / "python-hwpx" / "pyproject.toml").write_text("[project]\n")
    deep = tmp / "hwpx-plugins" / "plugins" / "codex" / "hwpx-plugin" / "scripts"
    deep.mkdir(parents=True)
    shutil.copy2(launcher, deep / "hwpx-mcp-server")
    (deep / "hwpx-mcp-server").chmod(0o755)
    binstub = tmp / "bin"
    binstub.mkdir()
    (binstub / "uv").write_text('#!/usr/bin/env bash\necho UV_CALLED "$@"\n')
    (binstub / "uv").chmod(0o755)
    env = {"PATH": str(binstub), "HOME": str(tmp)}
    out = subprocess.run([str(deep / "hwpx-mcp-server")], capture_output=True, text=True, env=env)
    assert "UV_CALLED run --project" in out.stdout, (out.stdout, out.stderr)
    assert str(tmp / "hwpx-mcp-server") in out.stdout, (out.stdout, out.stderr)
    print("[OK] launcher discovers local stack root by walking up")
PY
```

Expected:

```text
[OK] launcher discovers local stack root by walking up
```

- [ ] **Step 5: Commit**

```bash
git add packaging/templates/hwpx-mcp-server
git commit -m "feat: add depth-robust hwpx mcp launcher template"
```

## Task 2: Packaging Config And Host Templates

**Files:**
- Create: `packaging/hosts.json`
- Create: `packaging/templates/claude.plugin.json`
- Create: `packaging/templates/claude.mcp.json`
- Create: `packaging/templates/claude.marketplace.json`
- Create: `packaging/templates/codex.plugin.json`
- Create: `packaging/templates/codex.mcp.json`
- Create: `packaging/templates/openclaw.plugin.json`
- Create: `packaging/templates/openclaw.mcp-install.md`
- Create: `packaging/templates/hermes.mcp-install.md`

- [ ] **Step 1: Write `packaging/hosts.json`**

```json
{
  "schemaVersion": "hwpx.packaging.v1",
  "pluginName": "hwpx-plugin",
  "skillName": "hwpx",
  "canonicalSkill": "SKILL.md",
  "launcherTemplate": "templates/hwpx-mcp-server",
  "sharedAssets": [
    "README.md",
    "references/api.md",
    "examples/01_create_and_save.py",
    "examples/02_extract_and_inspect.py",
    "examples/03_template_replace.py",
    "examples/04_create_proposal.py",
    "examples/05_mcp_quality_pipeline.md",
    "examples/06_create_from_document_plan.py",
    "examples/06_mcp_document_plan.md",
    "examples/07_create_operating_plan.py",
    "examples/07_mcp_operating_plan.md",
    "examples/08_template_formfit.py",
    "examples/08_mcp_template_formfit.md",
    "examples/09_visual_review_loop.md",
    "scripts/fix_namespaces.py",
    "scripts/quickcheck.py",
    "scripts/text_extract.py",
    "scripts/visual_review.py",
    "scripts/zip_replace_all.py"
  ],
  "repoRootArtifacts": [
    { "template": "templates/claude.marketplace.json", "dest": ".claude-plugin/marketplace.json" }
  ],
  "hosts": [
    {
      "id": "claude",
      "outputDir": "plugins/claude/hwpx-plugin",
      "skillSubdir": "skills/hwpx",
      "frontmatterExtra": "",
      "manifests": [{ "template": "templates/claude.plugin.json", "dest": ".claude-plugin/plugin.json" }],
      "mcp": { "strategy": "bundled", "template": "templates/claude.mcp.json", "dest": ".mcp.json" },
      "bundleLauncher": true
    },
    {
      "id": "codex",
      "outputDir": "plugins/codex/hwpx-plugin",
      "skillSubdir": "skills/hwpx",
      "frontmatterExtra": "",
      "manifests": [{ "template": "templates/codex.plugin.json", "dest": ".codex-plugin/plugin.json" }],
      "mcp": { "strategy": "bundled", "template": "templates/codex.mcp.json", "dest": ".mcp.json" },
      "bundleLauncher": true
    },
    {
      "id": "openclaw",
      "outputDir": "plugins/openclaw/hwpx-plugin",
      "skillSubdir": "skills/hwpx",
      "frontmatterExtra": "",
      "manifests": [{ "template": "templates/openclaw.plugin.json", "dest": "openclaw.plugin.json" }],
      "mcp": { "strategy": "config-doc", "template": "templates/openclaw.mcp-install.md", "dest": "INSTALL-mcp.md" },
      "bundleLauncher": false
    },
    {
      "id": "hermes",
      "outputDir": "plugins/hermes/hwpx",
      "skillSubdir": ".",
      "frontmatterExtra": "version: 0.1.0\nauthor: Kohkyuhyun\nlicense: Apache-2.0\nmetadata:\n  hermes:\n    tags: [productivity, documents, hwpx, korean-documents]\n    category: productivity",
      "manifests": [],
      "mcp": { "strategy": "config-doc", "template": "templates/hermes.mcp-install.md", "dest": "INSTALL-mcp.md" },
      "bundleLauncher": false
    }
  ]
}
```

- [ ] **Step 2: Write `packaging/templates/claude.plugin.json`**

```json
{
  "$schema": "https://json.schemastore.org/claude-code-plugin-manifest.json",
  "name": "hwpx-plugin",
  "version": "0.1.0",
  "description": "HWPX document generation, validation, visual-review handoff, and MCP tooling.",
  "author": { "name": "Kohkyuhyun", "email": "kokyuhyun@hotmail.com", "url": "https://github.com/airmang" },
  "homepage": "https://github.com/airmang/hwpx-plugins",
  "repository": "https://github.com/airmang/hwpx-plugins",
  "license": "Apache-2.0",
  "keywords": ["claude-code", "hwpx", "mcp", "document-automation", "korean-documents"],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json"
}
```

- [ ] **Step 3: Write `packaging/templates/claude.mcp.json`**

```json
{
  "mcpServers": {
    "hwpx-mcp-server": {
      "command": "${CLAUDE_PLUGIN_ROOT}/scripts/hwpx-mcp-server",
      "args": [],
      "env": { "HWPX_MCP_ADVANCED": "0", "HWPX_MCP_AUTOBACKUP": "1" }
    }
  }
}
```

- [ ] **Step 4: Write `packaging/templates/claude.marketplace.json`**

```json
{
  "name": "hwpx",
  "owner": { "name": "Kohkyuhyun", "url": "https://github.com/airmang" },
  "plugins": [
    {
      "name": "hwpx-plugin",
      "source": "./plugins/claude/hwpx-plugin",
      "description": "HWPX document generation, validation, visual-review handoff, and MCP tooling."
    }
  ]
}
```

- [ ] **Step 5: Write `packaging/templates/codex.plugin.json`**

```json
{
  "name": "hwpx-plugin",
  "version": "0.1.0",
  "description": "HWPX document generation, validation, visual-review handoff, and MCP tooling for Codex.",
  "author": { "name": "Kohkyuhyun", "email": "kokyuhyun@hotmail.com", "url": "https://github.com/airmang" },
  "homepage": "https://github.com/airmang/hwpx-plugins",
  "repository": "https://github.com/airmang/hwpx-plugins",
  "license": "Apache-2.0",
  "keywords": ["codex", "hwpx", "mcp", "document-automation", "korean-documents"],
  "skills": "./skills/",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "HWPX Plugin",
    "shortDescription": "Create and validate HWPX documents from Codex.",
    "longDescription": "HWPX Plugin bundles the HWPX authoring skill, local examples, visual-review handoff scripts, and a companion MCP launcher for HWPX generation and validation workflows.",
    "developerName": "Kohkyuhyun",
    "category": "Productivity",
    "capabilities": ["Interactive", "Write"],
    "defaultPrompt": ["$hwpx create operating plan", "$hwpx inspect file quality", "$hwpx record visual review"],
    "brandColor": "#2563EB"
  }
}
```

- [ ] **Step 6: Write `packaging/templates/codex.mcp.json`**

```json
{
  "mcpServers": {
    "hwpx-mcp-server": {
      "command": "./scripts/hwpx-mcp-server",
      "args": [],
      "cwd": ".",
      "env": { "HWPX_MCP_ADVANCED": "0", "HWPX_MCP_AUTOBACKUP": "1" }
    }
  }
}
```

- [ ] **Step 7: Write `packaging/templates/openclaw.plugin.json`**

```json
{
  "id": "hwpx-plugin",
  "name": "HWPX Plugin",
  "description": "HWPX document generation, validation, visual-review handoff, and MCP tooling.",
  "version": "0.1.0",
  "skills": ["./skills"],
  "configSchema": { "type": "object", "additionalProperties": false, "properties": {} }
}
```

- [ ] **Step 8: Write `packaging/templates/openclaw.mcp-install.md`**

```markdown
# HWPX MCP server for OpenClaw

OpenClaw plugins do not bundle MCP servers in `openclaw.plugin.json`; the HWPX MCP
server is registered through your OpenClaw MCP configuration.

## Published package (recommended)

Add an MCP server entry that runs the pinned package with `uvx`:

```json
{
  "hwpx-mcp-server": {
    "command": "uvx",
    "args": ["--from", "hwpx-mcp-server==2.2.6", "hwpx-mcp-server"],
    "env": { "HWPX_MCP_ADVANCED": "0", "HWPX_MCP_AUTOBACKUP": "1" }
  }
}
```

## Local development checkout

If you have local `hwpx-mcp-server` and `python-hwpx` checkouts, point the command at the
bundled launcher and let it resolve them, or set the repo env vars:

```bash
export HWPX_MCP_SERVER_REPO=/absolute/path/to/hwpx-mcp-server
export PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx
```

The skill itself loads from `./skills` as declared in `openclaw.plugin.json`.
```

- [ ] **Step 9: Write `packaging/templates/hermes.mcp-install.md`**

```markdown
# HWPX skill + MCP server for Hermes Agent

This directory is a publishable Hermes skill (`SKILL.md` plus `scripts/` and `references/`).
Hermes loads MCP servers from `config.yaml`, not from the skill, so register the HWPX MCP
server there.

## Publish the skill

```bash
hermes skills publish plugins/hermes/hwpx --to github --repo airmang/hwpx-plugins
```

## Register the MCP server in `config.yaml`

```yaml
mcp_servers:
  hwpx-mcp-server:
    command: uvx
    args: ["--from", "hwpx-mcp-server==2.2.6", "hwpx-mcp-server"]
    env:
      HWPX_MCP_ADVANCED: "0"
      HWPX_MCP_AUTOBACKUP: "1"
```

## Local development checkout

```yaml
mcp_servers:
  hwpx-mcp-server:
    command: /absolute/path/to/hwpx-plugins/packaging/templates/hwpx-mcp-server
    env:
      HWPX_MCP_SERVER_REPO: /absolute/path/to/hwpx-mcp-server
      PYTHON_HWPX_REPO: /absolute/path/to/python-hwpx
```

The launcher discovers sibling `hwpx-mcp-server` and `python-hwpx` checkouts automatically when
the env vars are unset and the repos sit under a common parent.
```

- [ ] **Step 10: Validate JSON parses**

Run:

```bash
python3 - <<'PY'
import json, pathlib
for p in pathlib.Path("packaging").rglob("*.json"):
    json.loads(p.read_text(encoding="utf-8"))
    print("ok", p)
PY
```

Expected: one `ok packaging/...` line per JSON file, no traceback.

- [ ] **Step 11: Commit**

```bash
git add packaging/hosts.json packaging/templates
git commit -m "feat: add multi-host packaging config and templates"
```

## Task 3: Multi-Host Builder

**Files:**
- Create: `scripts/build_hwpx_plugins.py`

- [ ] **Step 1: Write the builder**

Write `scripts/build_hwpx_plugins.py`:

```python
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


def build_host(host: dict, config: dict) -> None:
    out = ROOT / host["outputDir"]
    if out.exists():
        shutil.rmtree(out)
    skill_dir = skill_dir_for(host)
    skill_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    canonical = ROOT / config["canonicalSkill"]
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        render_skill_md(canonical.read_text(encoding="utf-8"), host.get("frontmatterExtra", "")),
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
        launcher_dest = out / "scripts" / "hwpx-mcp-server"
        copy_file(launcher_src, launcher_dest)
        launcher_dest.chmod(0o755)
        records.append(record(f"packaging/{config['launcherTemplate']}", launcher_src, launcher_dest, transformed=False))

    for rec in records:
        text = (ROOT / rec["dest"]).read_text(encoding="utf-8", errors="ignore")
        if "[PLACEHOLDER:" in text:
            raise SystemExit(f"generated file contains a placeholder: {rec['dest']}")

    sync = out / "plugin-sync.json"
    sync.write_text(
        json.dumps(
            {
                "schemaVersion": "hwpx.plugin-sync.v2",
                "plugin": config["pluginName"],
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
    for host in config["hosts"]:
        build_host(host, config)
    build_repo_root_artifacts(config)
    print(f"[OK] built {len(config['hosts'])} host bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/build_hwpx_plugins.py
```

- [ ] **Step 3: Run the builder**

```bash
python3 scripts/build_hwpx_plugins.py
```

Expected:

```text
[OK] built 4 host bundles
```

- [ ] **Step 4: Sanity-check the generated tree**

```bash
test -f plugins/claude/hwpx-plugin/.claude-plugin/plugin.json
test -f plugins/claude/hwpx-plugin/.mcp.json
test -x plugins/claude/hwpx-plugin/scripts/hwpx-mcp-server
test -f plugins/claude/hwpx-plugin/skills/hwpx/SKILL.md
test -f plugins/codex/hwpx-plugin/.codex-plugin/plugin.json
test -x plugins/codex/hwpx-plugin/scripts/hwpx-mcp-server
test -f plugins/openclaw/hwpx-plugin/openclaw.plugin.json
test -f plugins/openclaw/hwpx-plugin/INSTALL-mcp.md
test -f plugins/hermes/hwpx/SKILL.md
test -f plugins/hermes/hwpx/INSTALL-mcp.md
test -f .claude-plugin/marketplace.json
echo "[OK] generated tree present"
```

Expected: `[OK] generated tree present`

- [ ] **Step 5: Verify Hermes frontmatter and Claude frontmatter differ correctly**

```bash
python3 - <<'PY'
import pathlib
claude = pathlib.Path("plugins/claude/hwpx-plugin/skills/hwpx/SKILL.md").read_text(encoding="utf-8")
hermes = pathlib.Path("plugins/hermes/hwpx/SKILL.md").read_text(encoding="utf-8")
claude_fm = claude.split("\n---\n", 1)[0]
hermes_fm = hermes.split("\n---\n", 1)[0]
assert "version:" not in claude_fm, "Claude frontmatter must not declare version"
assert "metadata:" not in claude_fm, "Claude frontmatter must stay name+description"
assert "version: 0.1.0" in hermes_fm, "Hermes frontmatter must declare version"
assert "hermes:" in hermes_fm and "tags:" in hermes_fm, "Hermes frontmatter must carry metadata.hermes.tags"
# canonical body is identical below the frontmatter fence
assert claude.split("\n---\n", 1)[1] == hermes.split("\n---\n", 1)[1], "skill body must be identical across hosts"
print("[OK] per-host frontmatter correct, shared body identical")
PY
```

Expected:

```text
[OK] per-host frontmatter correct, shared body identical
```

- [ ] **Step 6: Commit (builder only; bundles committed in Task 4)**

```bash
git add scripts/build_hwpx_plugins.py
git commit -m "feat: add multi-host plugin builder"
```

## Task 4: Relocate Codex Bundle And Commit Generated Bundles

**Files:**
- Delete: `plugins/hwpx-plugin/**`
- Add (generated): `plugins/claude/**`, `plugins/codex/**`, `plugins/openclaw/**`, `plugins/hermes/**`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Remove the old single-host bundle**

```bash
git rm -r plugins/hwpx-plugin
```

Expected: git stages the deletion of every file under `plugins/hwpx-plugin/`.

- [ ] **Step 2: Confirm the old bundle is gone and generated artifacts are clean**

The repo-root `README.md` and `references/api.md` still reference the old single-host path; they are updated in Task 7. Here, only confirm the directory was removed and the freshly generated artifacts do not reference the old path.

```bash
test ! -e plugins/hwpx-plugin && echo "[OK] old single-host bundle removed"
if git grep -n "plugins/hwpx-plugin" -- packaging plugins/claude plugins/codex plugins/openclaw plugins/hermes .claude-plugin; then
  echo "FOUND stale path in generated artifacts"; exit 1
else
  echo "[OK] generated artifacts clean"
fi
```

Expected: `[OK] old single-host bundle removed` then `[OK] generated artifacts clean`. (`plugins/claude/hwpx-plugin` etc. do not contain the literal substring `plugins/hwpx-plugin`.)

- [ ] **Step 3: Stage the generated bundles**

```bash
git add plugins/claude plugins/codex plugins/openclaw plugins/hermes .claude-plugin/marketplace.json
git status --short
```

Expected: only additions under `plugins/{claude,codex,openclaw,hermes}/` and `.claude-plugin/marketplace.json`, plus the staged deletion of `plugins/hwpx-plugin/`.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: generate committed multi-host plugin bundles"
```

## Task 5: Multi-Host Validator

Replace the single-host validator with one that reads `packaging/hosts.json` and validates every target, preserving the existing path-safety helpers.

**Files:**
- Rewrite: `scripts/validate_hwpx_plugin.py`

- [ ] **Step 1: Rewrite the validator**

Replace the entire contents of `scripts/validate_hwpx_plugin.py` with:

```python
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
        'uvx --from "hwpx-mcp-server==2.2.6"',
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
            require(isinstance(data.get("owner"), dict), "marketplace: owner invalid")
            plugins = data.get("plugins")
            require(isinstance(plugins, list) and plugins, "marketplace: plugins invalid")
            entry = plugins[0]
            require(entry.get("name") == "hwpx-plugin", "marketplace: plugin name invalid")
            require(entry.get("source") == "./plugins/claude/hwpx-plugin", "marketplace: plugin source invalid")


def main() -> int:
    config = load_json(CONFIG)
    for host in config["hosts"]:
        validate_host(host, config)
    validate_marketplace(config)
    print(f"[OK] validated {len(config['hosts'])} host bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the validator**

```bash
python3 scripts/validate_hwpx_plugin.py
```

Expected:

```text
[OK] validated 4 host bundles
```

- [ ] **Step 3: Negative test — drift is detected**

```bash
python3 - <<'PY'
import subprocess, pathlib
target = pathlib.Path("plugins/claude/hwpx-plugin/.mcp.json")
original = target.read_text(encoding="utf-8")
target.write_text(original + "\n", encoding="utf-8")  # tamper
try:
    result = subprocess.run(["python3", "scripts/validate_hwpx_plugin.py"], capture_output=True, text=True)
    assert result.returncode != 0, "validator should fail on tampered bundle"
    assert "tampered" in (result.stdout + result.stderr), (result.stdout, result.stderr)
    print("[OK] validator detects bundle tampering")
finally:
    target.write_text(original, encoding="utf-8")  # restore
PY
```

Expected:

```text
[OK] validator detects bundle tampering
```

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_hwpx_plugin.py
git commit -m "feat: validate all four host bundles"
```

## Task 6: Retire Sync Script And Wire Full Verification

**Files:**
- Delete: `scripts/sync_hwpx_plugin.py`

- [ ] **Step 1: Remove the superseded sync script**

```bash
git rm scripts/sync_hwpx_plugin.py
```

- [ ] **Step 2: Reproducible-build check (the authoritative drift gate)**

```bash
python3 scripts/build_hwpx_plugins.py
git diff --exit-code -- plugins .claude-plugin
echo "[OK] build is reproducible and committed"
```

Expected: no diff output, then `[OK] build is reproducible and committed`. A non-empty diff means the committed bundles are stale — rebuild and recommit before continuing.

- [ ] **Step 3: Validate**

```bash
python3 scripts/validate_hwpx_plugin.py
```

Expected:

```text
[OK] validated 4 host bundles
```

- [ ] **Step 4: MCP discovery smoke (shared launcher)**

```bash
python3 - <<'PY'
import json, subprocess

proc = subprocess.Popen(
    ["plugins/codex/hwpx-plugin/scripts/hwpx-mcp-server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
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
names = {tool["name"] for tool in seen[1]["result"]["tools"]}
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

- [ ] **Step 5: Full skill quickcheck**

```bash
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

Expected output contains all of:

```text
[OK] document-plan generation workflow passed
[OK] operating-plan document-plan workflow passed
[OK] template form-fit workflow passed
[OK] visual-review fallback evidence workflow passed
```

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_hwpx_plugin.py
git commit -m "chore: retire single-host sync script"
```

## Task 7: Documentation And Repo Rename

The GitHub repo is already renamed to `airmang/hwpx-plugins`; update tracked references and document the multi-host bundle. The local directory name is unchanged and does not need editing.

**Files:**
- Modify: `README.md`
- Modify: `references/api.md`
- Modify: `../hwpx-mcp-server/README.md`
- Modify: `../python-hwpx/README.md`

- [ ] **Step 1: Replace the Codex-plugin section in `README.md`**

Find the existing `## Codex plugin bundle` section and replace it with:

```markdown
## Multi-host plugin bundles

This repository is the canonical source for the HWPX skill and builds one bundle per agent host:

| Host | Bundle | Install entry point |
| :--- | :--- | :--- |
| Claude Code | `plugins/claude/hwpx-plugin` | `.claude-plugin/marketplace.json` (repo root) |
| Codex | `plugins/codex/hwpx-plugin` | `.codex-plugin/plugin.json` |
| OpenClaw | `plugins/openclaw/hwpx-plugin` | `openclaw.plugin.json` + `INSTALL-mcp.md` |
| Hermes Agent | `plugins/hermes/hwpx` | `hermes skills publish` + `INSTALL-mcp.md` |

Edit the canonical `SKILL.md`, `references/`, `examples/`, and `scripts/` at the repo root,
then rebuild and validate:

```bash
python3 scripts/build_hwpx_plugins.py
python3 scripts/validate_hwpx_plugin.py
git diff --exit-code -- plugins .claude-plugin   # build must be reproducible and committed
uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review
```

Host differences (frontmatter, manifests, MCP wiring, skill paths) are declared in
`packaging/hosts.json` with templates in `packaging/templates/`. The MCP launcher prefers local
sibling checkouts (`../hwpx-mcp-server`, `../python-hwpx`), honors `HWPX_MCP_SERVER_REPO` /
`PYTHON_HWPX_REPO`, and otherwise falls back to `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server`.

Claude Code installs via `claude plugin marketplace add airmang/hwpx-plugins` then
`claude plugin install hwpx-plugin@hwpx`. Codex installs from the local marketplace as before.
Start a fresh agent session after installing so new skills and MCP tools load.
```

- [ ] **Step 2: Replace the Codex-plugin section in `references/api.md`**

Find the existing `### Codex plugin bundle` section and replace it with:

```markdown
### Multi-host plugin bundles

`plugins/<host>/` holds generated, committed bundles for Claude Code, Codex, OpenClaw, and
Hermes Agent, built from the repo-root skill assets by `scripts/build_hwpx_plugins.py` and
checked by `scripts/validate_hwpx_plugin.py`.

The bundled MCP launcher (`scripts/hwpx-mcp-server` in Claude/Codex bundles) resolves, in order:

1. `HWPX_MCP_SERVER_REPO` / `PYTHON_HWPX_REPO` env overrides
2. a stack root discovered by walking up to sibling `hwpx-mcp-server` and `python-hwpx` checkouts
3. `uvx --from hwpx-mcp-server==2.2.6 hwpx-mcp-server`

Run `python3 scripts/build_hwpx_plugins.py` after changing `SKILL.md`, `references`, `examples`,
or skill scripts, then `python3 scripts/validate_hwpx_plugin.py`.
```

- [ ] **Step 3: Update `../hwpx-mcp-server/README.md`**

Find the `### Codex plugin companion launcher` heading and replace that paragraph with:

```markdown
### HWPX plugin companion launcher

The `hwpx-plugins` repository builds per-host bundles whose MCP launcher
(`plugins/<host>/hwpx-plugin/scripts/hwpx-mcp-server`) can run this server. In local development,
set `HWPX_MCP_SERVER_REPO=/absolute/path/to/hwpx-mcp-server` and
`PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx` when the repositories are not under a common
parent. The launcher otherwise discovers them by walking up from the bundle directory and uses
`uv run --project "$HWPX_MCP_SERVER_REPO" --with-editable "$PYTHON_HWPX_REPO" --with-editable "$HWPX_MCP_SERVER_REPO" hwpx-mcp-server`.
```

- [ ] **Step 4: Update `../python-hwpx/README.md`**

Find the `### Codex plugin usage` heading and replace that paragraph with:

```markdown
### HWPX plugin usage

The per-host bundles in the `hwpx-plugins` repository consume `python-hwpx` through
`hwpx-mcp-server` and the local quickcheck scripts. During local development, set
`PYTHON_HWPX_REPO=/absolute/path/to/python-hwpx` so the plugin launcher uses this checkout as an
editable dependency.
```

- [ ] **Step 5: Rebuild bundles (README.md and references/api.md are shared assets)**

Editing the canonical `README.md` and `references/api.md` changes files that are copied into every bundle, so regenerate and revalidate before committing:

```bash
python3 scripts/build_hwpx_plugins.py
python3 scripts/validate_hwpx_plugin.py
```

Expected: `[OK] built 4 host bundles` then `[OK] validated 4 host bundles`.

- [ ] **Step 6: Confirm no stale repo name or old path remains (this repo)**

`git grep` searches only this repository, so scope it to tracked files here. Sibling-repo READMEs are checked in their own repos at commit time.

```bash
if git grep -n "hwpx-skill" -- README.md references/api.md packaging plugins .claude-plugin; then
  echo "FOUND stale hwpx-skill references"; exit 1
else
  echo "[OK] no stale hwpx-skill references"
fi
if git grep -n "plugins/hwpx-plugin\b" -- README.md references/api.md; then
  echo "FOUND stale single-host path"; exit 1
else
  echo "[OK] no stale single-host path"
fi
```

Expected: `[OK] no stale hwpx-skill references` then `[OK] no stale single-host path`.

- [ ] **Step 7: Commit this repository**

```bash
git add README.md references/api.md plugins .claude-plugin
git commit -m "docs: document multi-host bundles and hwpx-plugins rename"
```

- [ ] **Step 8: Commit the sibling-repo doc edits in their own repos**

These files live in separate git repositories that already have unrelated pending changes. Commit only the README path in each, leaving other changes untouched:

```bash
git -C ../hwpx-mcp-server add README.md
git -C ../hwpx-mcp-server commit -m "docs: point companion launcher note at hwpx-plugins"
git -C ../python-hwpx add README.md
git -C ../python-hwpx commit -m "docs: point plugin usage note at hwpx-plugins"
```

Expected: one commit in each sibling repo touching only `README.md`.

## Task 8: Release Handoff

**Files:**
- Create: `docs/release-handoff-2026-06-01-hwpx-multihost.md`

- [ ] **Step 1: Write the handoff**

Write `docs/release-handoff-2026-06-01-hwpx-multihost.md`:

```markdown
# HWPX Multi-Host Packaging Release Handoff - 2026-06-01

## Bundles

- Claude Code: `plugins/claude/hwpx-plugin` (+ repo-root `.claude-plugin/marketplace.json`)
- Codex: `plugins/codex/hwpx-plugin`
- OpenClaw: `plugins/openclaw/hwpx-plugin`
- Hermes Agent: `plugins/hermes/hwpx`

Source of truth: repo-root `SKILL.md`, `references/`, `examples/`, `scripts/`.
Build: `scripts/build_hwpx_plugins.py`. Config: `packaging/hosts.json` + `packaging/templates/`.

## Verification

- `python3 scripts/build_hwpx_plugins.py` && `git diff --exit-code -- plugins .claude-plugin`
- `python3 scripts/validate_hwpx_plugin.py`
- MCP tool discovery smoke for `validate_document_plan`, `create_document_from_plan`, `inspect_operating_plan_quality`
- `uv run --with lxml --with ../python-hwpx python scripts/quickcheck.py --document-plan --operating-plan --template-formfit --visual-review`

## Residual notes

- End-to-end install in Claude Code / OpenClaw / Hermes is not exercised here; confirm in each host after install.
- `visual_review_required=true` remains a final submission gate.
- The `hwpx-mcp-server==2.2.6` pin is owned by feature work (Sub-project B).
- GitHub repo renamed to `airmang/hwpx-plugins`; local directory name is unchanged.
```

- [ ] **Step 2: Final verification**

```bash
python3 scripts/build_hwpx_plugins.py
git diff --exit-code -- plugins .claude-plugin
python3 scripts/validate_hwpx_plugin.py
```

Expected: no diff, then `[OK] validated 4 host bundles`.

- [ ] **Step 3: Commit**

```bash
git add docs/release-handoff-2026-06-01-hwpx-multihost.md
git commit -m "docs: record multi-host packaging release handoff"
```

---

## Self-Review

**Spec coverage:**
- Canonical source + per-host builder (spec §4, §5.4) → Tasks 2, 3.
- Per-host artifacts: Claude/Codex/OpenClaw/Hermes manifests, frontmatter, MCP wiring (spec §3, §5) → Task 2 templates, Task 3 build, Task 5 validation.
- Committed bundles + sha256 drift (spec §10) → Task 4 commit, Task 5 `validate_sync`, Task 6 reproducible-build gate.
- Codex relocation (spec §4, §10) → Task 4.
- Shared launcher with depth fix (spec §5.3) → Task 1.
- Marketplace / distribution (spec §9) → Task 2 (`claude.marketplace.json`), Task 5 (`validate_marketplace`), Task 7 docs.
- Verification strategy incl. honest "no host runtime here" (spec §8) → Tasks 5/6 + handoff §Residual.
- Repo URL rename to `hwpx-plugins` (post-brainstorm decision) → Task 2 templates, Task 7.
- Out-of-scope B untouched (spec §11) → no skill body or `2.2.6` pin changes.

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every code and config step contains full content. The literal token `[PLACEHOLDER:` appears only as a guard string in the builder/validator, intentionally.

**Type/name consistency:** `build_host`, `render_skill_md`, `record`, `validate_host`, `validate_sync` are defined once and referenced consistently. Sync schema is `hwpx.plugin-sync.v2` in both builder and validator. Plugin name `hwpx-plugin`, skill name `hwpx`, MCP id `hwpx-mcp-server`, marketplace source `./plugins/claude/hwpx-plugin` match across builder, templates, and validator. Frontmatter rule (Hermes requires `version`; others forbid top-level `version`) is enforced identically in Task 3 Step 5 and the Task 5 validator.
```
