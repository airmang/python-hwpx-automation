# Codex handoff prompt — HWPX multi-host packaging

Copy everything in the fenced block below into Codex (running in the `hwpx-skill` working
directory, branch `feat/multihost-packaging`).

```text
You are implementing the HWPX multi-host packaging work in this repository.

Working directory: this repo (local folder name `hwpx-skill`; the GitHub remote is
`airmang/hwpx-plugins` — the folder is intentionally NOT renamed).
Branch: work on `feat/multihost-packaging`. Run `git branch --show-current` first and
switch to it if needed. Do not create other branches. Do not push; leave pushing to me.

Read these two documents fully before writing any code, and treat them as authoritative:
- Plan:  docs/superpowers/plans/2026-06-01-hwpx-multihost-packaging.md
- Spec:  docs/superpowers/specs/2026-06-01-hwpx-multihost-packaging-design.md

Goal: build one plugin bundle per agent host (Claude Code, Codex, OpenClaw, Hermes Agent)
from the single canonical skill source at the repo root, via a per-host builder. Bundles are
committed and guarded by sha256 drift records plus a reproducible-build check.

How to execute:
1. Implement the plan task by task, in order (Task 1 → Task 8). Do not skip ahead.
2. Each task lists files and numbered steps with exact file contents and exact commands.
   Use the file contents verbatim — they are the spec, not suggestions.
3. After each step that has an "Expected:" block, run the command and confirm the output
   matches before moving on. If it does not match, STOP and diagnose; do not paper over a
   failing check.
4. Commit at each task's commit step using the exact commit message given in the plan. Make
   the commits real (the plan's messages already omit attribution trailers; keep them as written).
5. The test gate for this work is `scripts/validate_hwpx_plugin.py` + the MCP discovery smoke
   + `scripts/quickcheck.py`. There is no pytest suite; that is expected.

Hard constraints:
- Python: standard library only. Add no third-party dependencies.
- Scope: this is packaging only (Sub-project A). Do NOT edit the canonical SKILL.md body,
  the example/script behavior, or the `hwpx-mcp-server==2.2.6` pin beyond what the plan
  specifies. Feature work is a separate later project.
- Do not rename the local directory. Do not touch the `.omx/` directory.
- Cross-repo: only Task 7 Step 8 commits in the sibling repos `../hwpx-mcp-server` and
  `../python-hwpx`, and only their `README.md` via explicit-path commits. Those repos have
  unrelated pending changes — do not stage or commit anything else there.

Environment notes:
- `uv` and `uvx` are available. Sibling checkouts exist at `../hwpx-mcp-server` and
  `../python-hwpx`, so the launcher's local-stack path and the MCP smoke should work.
- The reproducible-build gate is `python3 scripts/build_hwpx_plugins.py` followed by
  `git diff --exit-code -- plugins .claude-plugin`. A non-empty diff means committed bundles
  are stale — rebuild and recommit, never hand-edit a generated bundle.

Definition of done:
- All 8 tasks committed on `feat/multihost-packaging`.
- `python3 scripts/build_hwpx_plugins.py` prints `[OK] built 4 host bundles`.
- `git diff --exit-code -- plugins .claude-plugin` is clean.
- `python3 scripts/validate_hwpx_plugin.py` prints `[OK] validated 4 host bundles`.
- The MCP discovery smoke prints `[OK] plugin MCP server exposes core HWPX tools`.
- `quickcheck.py` prints all four `[OK] ... passed` lines.
- Sibling-repo README commits made in their own repos (Task 7 Step 8).

When finished, report: the commit list (`git log --oneline` for the new commits), the final
output of the validator and the reproducible-build check, and anything in the plan you could
not complete and why. Do not push.
```
