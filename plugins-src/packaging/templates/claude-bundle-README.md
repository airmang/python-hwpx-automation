# hwpx-plugin

Claude Code plugin for Korean Hangul documents. It reads `.hwpx` (OWPML) and `.hwp` (HWP 5.0) files, edits, fills and
creates `.hwpx` documents, and checks what it wrote by opening the saved file again. `.hwp` files are read only: an
edited `.hwp` comes back as a new `.hwpx` file and the original is left as it was. It is built by the python-hwpx
project and is not affiliated with Hancom Inc.

## What the plugin contains

- `skills/hwpx/` — the `hwpx` skill: instructions (`SKILL.md`, `references/`), example scripts and small helper
  scripts. `skills/hwpx/engine/` holds an unmodified copy of the published `python-hwpx` and `python-hwpx-automation`
  wheels (versions and per-file SHA-256 in `engine/VENDOR.json`) for chats where the MCP server cannot run.
- `server/` — a `pyproject.toml` and `uv.lock` that pin the MCP server's Python packages to exact versions with
  hashes.
- `.mcp.json` — starts one local MCP server named `hwpx` over stdio.

## What it runs

The MCP server is started with `uv run --frozen --project <plugin>/server hwpx-automation-mcp`. It runs on your
computer only, with your user's permissions, and reads and writes the files you ask it to work on; when a tool
changes an existing file it first keeps a backup copy next to it. `uv` must already be installed. The plugin changes no Claude Code settings and installs no hooks.

In chats without the MCP server, the skill runs the bundled engine with the Python of the chat's code environment. It
does not install the engine; if `lxml` (and, for creating documents, `pydantic` and `cryptography`) is missing, it
asks before installing only those packages with `pip`.

## What it downloads

- On the first start, `uv` downloads the packages pinned in `server/uv.lock`, each checked against its hash, from the
  Python Package Index (pypi.org / files.pythonhosted.org). If no Python 3.12 is installed, `uv` also downloads its
  managed Python 3.12 build (from GitHub, where uv publishes them). Later starts use the installed environment and do
  not need the network.
- Nothing else is downloaded unless you ask for it: the read tools `hwpx_to_markdown`, `hwpx_to_html` and
  `hwpx_extract_json` accept a `url` and fetch that one `.hwpx` file (public addresses only by default).

## What it sends

Documents are processed locally and are not sent anywhere. The plugin has no telemetry. The only exception is the
optional Hancom render check: if you configure a render queue yourself (its address and credentials in environment
variables), the document you ask to render is sent to that queue. It is off unless configured.

## Updating

```bash
claude plugin marketplace update hwpx
claude plugin update hwpx-plugin@hwpx
```

Start a new session afterwards. Auto-update is off by default for this marketplace; turn it on under `/plugin` →
Marketplaces → `hwpx`.

Source, issues and the full documentation: https://github.com/airmang/hwpx-plugins
