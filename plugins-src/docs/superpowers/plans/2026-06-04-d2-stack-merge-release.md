# 강화 D2 — 스택 머지·릴리스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** S-013 빌더, A1/A2/C1/C2 충실도·안정성, B1~B4 생성 완성, D1 한컴 수용성 검증 결과를 `python-hwpx -> hwpx-mcp-server -> hwpx-skill` 순서로 main에 통합하고 릴리스한다. base 중복 커밋을 정리해 PR diff를 깨끗하게 만들고, PyPI/플러그인 번들/마켓플레이스 설치 경로가 새 스택을 즉시 사용할 수 있게 한다.

**Architecture:** 릴리스 단위는 3레포 스택이다. `python-hwpx`가 public API와 빌더/government_report 기능의 기준 버전을 먼저 릴리스하고, `hwpx-mcp-server`는 그 버전을 dependency floor로 삼아 MCP 도구 정합을 릴리스한다. 마지막으로 `hwpx-skill`은 새 MCP 서버 버전을 launcher pin/문서/번들/marketplace에 반영하고 Codex Git marketplace 설치를 검증한다.

**Tech Stack:** Python 3.10+, setuptools/build/twine, pytest, uv/uvx, Codex plugin CLI, HWPX MCP server, local editable 3레포 stack.

**개발 환경 (3 레포):**
- python-hwpx: `/Users/wilycastle/Code/projects/hwpx/python-hwpx` — branch `feat/builder-integration`, 현재 local version `2.9.1`.
- hwpx-mcp-server: `/Users/wilycastle/Code/projects/hwpx/hwpx-mcp-server` — branch `feat/b4-gov-mcp`, 현재 local version `2.2.6`, dependency floor `python-hwpx>=2.9.1`.
- hwpx-skill: `/Users/wilycastle/Code/projects/hwpx/hwpx-skill` — branch `feat/d1-hancom-scale`, Codex bundle/marketplace worktree. 현재 launcher/docs는 `hwpx-mcp-server==2.3.2` pin을 포함하므로 pyproject/PyPI 실상과 정합성 확인이 필요하다.

**Important constraints:**
- PyPI/GitHub 최신 상태는 실행 시점에 반드시 확인한다. 로컬 handoff나 badge 값을 release truth로 간주하지 않는다.
- base 중복 커밋 `08c642a repair`, `efc9d93 split-run`이 `origin/main`의 `7b5fdb5`, `69b5917`과 중복되는 문제를 merge/rebase 전에 정리한다.
- `hwpx-skill`의 기존 `.omx/`는 삭제하지 않는다.
- production/PyPI/GitHub push는 명시 확인 후 수행한다.

## Stage Context

- Wily Stage: `S-032` / `STG-05d6ff78d7a6`
- Status: done
- Dependency: `S-031` done
- Acceptance target: clean main integration, python-hwpx release, hwpx-mcp-server floor/tool release, hwpx-skill bundle baseline, 3-repo stack smoke.

## File Structure

- Modify: `python-hwpx/CHANGELOG.md`
- Modify: `python-hwpx/pyproject.toml`
- Modify: `hwpx-mcp-server/pyproject.toml`
- Modify: `hwpx-mcp-server/README.md` if dependency/install docs change.
- Modify: `hwpx-skill/README.md`
- Modify: `hwpx-skill/packaging/templates/hwpx-mcp-server`
- Modify: `hwpx-skill/packaging/templates/*.json`, `*.md` pins if MCP version changes.
- Generated: `hwpx-skill/plugins/**`, `.agents/plugins/marketplace.json`, `.claude-plugin/marketplace.json` after `scripts/build_hwpx_plugins.py`.
- Create/update: stack smoke script or documented equivalent if `shared/hwpx/scripts/run_stack_smoke_test.sh` is absent.

## Execution Protocol

SPIKE -> branch/diff cleanup -> dependency-order release -> plugin bundle rebuild -> local install smoke -> push/install verification. Do not batch unrelated repo changes into one commit. Each repo gets its own focused checks before commit/tag/push.

### Task 1: SPIKE — release truth and duplicate-commit map

- [x] **PyPI truth:** Check current PyPI versions for `python-hwpx` and `hwpx-mcp-server`; record whether local `python-hwpx==2.9.1`, local `hwpx-mcp-server==2.2.6`, and `hwpx-skill` pin `hwpx-mcp-server==2.3.2` are already released or need new releases. Result: PyPI had `python-hwpx==2.10.0` and `hwpx-mcp-server==2.3.2`, but fresh install lacked `report_utils`, `report_parser`, `id_integrity`, `table_cleanup`, and government-report MCP tools.
- [x] **Git truth:** Fetch all three repos, inspect `origin/main`, current feature branches, unpushed commits, tags, and dirty files.
- [x] **Duplicate map:** Confirm where `08c642a`/`efc9d93` duplicate `7b5fdb5`/`69b5917`, then choose merge strategy: rebase/drop duplicate commits or merge with explicit conflict resolution. Result: `origin/main..feat/builder-integration` cherry-pick path excludes the duplicate repair/form-fill commits.
- [x] **Release numbering:** Choose the next versions in dependency order. If `hwpx-mcp-server==2.3.2` is already published and contains required behavior, align local pyproject/docs to that; otherwise select the next patch/minor and update all pins consistently. Result: selected `python-hwpx==2.10.1`, `hwpx-mcp-server==2.3.3`, `hwpx-plugin==0.1.3`.

### Task 2: python-hwpx main integration and release

**Files:** `python-hwpx/CHANGELOG.md`, `python-hwpx/pyproject.toml`, integration branches.

- [x] **RED/criteria:** On a clean branch from updated `origin/main`, the builder/API/fidelity work merges without duplicate base commits or noisy repeated diffs.
- [x] **GREEN:** Integrate `feat/s013-builder-core`/builder-integration and required A/B/C/D work. Resolve conflicts by preserving current builder public API, plan v2 lowering, government_report preset, namespace/id gates, and D1 acceptance artifacts.
- [x] **Version/docs:** Bump `python-hwpx` version and add CHANGELOG entry for builder API exposure, plan v2/government_report, fidelity/stability gates, and Hancom acceptance evidence.
- [x] **Verify:** Run focused tests for builder/plan/government_report/fidelity gates, then full available python-hwpx test suite.
- [x] **Release:** Built sdist/wheel, inspected artifacts, and published `python-hwpx==2.10.1` through GitHub Actions trusted publishing. Release run `26935505409` succeeded; PyPI JSON verified `2.10.1`.
- [x] **Commit/tag:** Pushed `bfbc70191e18af16490f96d6515dcf259d1bb6ee` to `origin/main` and pushed tag `v2.10.1`.

### Task 3: hwpx-mcp-server floor bump, MCP tool release

**Files:** `hwpx-mcp-server/pyproject.toml`, `hwpx-mcp-server/README.md`, MCP tool/tests.

- [x] **RED/criteria:** With the released `python-hwpx` version, MCP tests cover plan v2, `create_government_report_document`, `compute_report_value`, and `parse_government_report_text` without editable-only assumptions.
- [x] **GREEN:** Bump `python-hwpx` dependency floor to the released version. Align `hwpx-mcp-server` package version with the selected release number.
- [x] **Verify:** Run focused MCP tests plus e2e document-plan/government-report tests using the released `python-hwpx`; then run the full available hwpx-mcp-server suite.
- [x] **Release:** Built and published `hwpx-mcp-server==2.3.3` through GitHub Actions trusted publishing. Release run `26935556190` succeeded; PyPI specific endpoint/simple index verified `2.3.3`. Fresh install verified `python-hwpx==2.10.1`, government-report support module imports, and MCP server tool attributes.
- [x] **Commit/tag:** Pushed `100a09490dfe21e1aa6ceda2b776a6875c763d66` to `origin/main` and pushed tag `v2.3.3`.

### Task 4: hwpx-skill bundle baseline and marketplace install

**Files:** `hwpx-skill/README.md`, `packaging/templates/*`, `packaging/hosts.json`, `plugins/**`, `.agents/plugins/marketplace.json`.

- [x] **Pin sweep:** Update every `hwpx-mcp-server==<version>` pin and plugin/template version baseline to match the released MCP server. Use `rg -n "hwpx-mcp-server==|2\\.3\\."` before and after.
- [x] **Docs:** Ensure README install commands document the real Git marketplace path:

```bash
codex plugin marketplace add airmang/hwpx-plugins
codex plugin add hwpx-plugin@hwpx
```

- [x] **Rebuild:** Run `python3 scripts/build_hwpx_plugins.py` and inspect generated diffs.
- [x] **Validate:** Run `python3 scripts/validate_hwpx_plugin.py`, the Codex plugin validator, and `git diff --check`.
- [x] **Local install smoke:** Installed from local marketplace, confirmed `.mcp.json`, `scripts/hwpx-mcp-server`, plugin-local venv marker, and MCP server executable. Removed local test plugin/marketplace afterward.
- [x] **Commit:** Committed source templates plus generated plugin bundle diffs as `c5e034f99aba36040bf6e4733a1241949f346314` and pushed to `airmang/hwpx-plugins` main.

### Task 5: 3-repo stack smoke, push, and real GitHub install verification

- [x] **Stack smoke:** Equivalent smoke passed: `uv run --with lxml --with-editable /Users/wilycastle/Code/projects/hwpx/python-hwpx-s032-release python scripts/quickcheck.py --builder --document-plan --operating-plan --template-formfit --visual-review`, plus fresh PyPI install/import checks.
- [x] **Push order:** Pushed python-hwpx, then hwpx-mcp-server, then hwpx-skill. GitHub release workflows/tags were verified for the two PyPI packages.
- [x] **Fresh Codex boundary:** Noted operational requirement: installed skills/MCP tools are picked up on a new Codex session boundary.
- [x] **GitHub marketplace smoke:** Tested the real path:

```bash
codex plugin marketplace add airmang/hwpx-plugins
codex plugin add hwpx-plugin@hwpx
```

- [x] **Verify installed MCP:** Installed plugin `0.1.3` from GitHub marketplace, confirmed `.mcp.json`, executable launcher, plugin-local venv marker `hwpx-mcp-server==2.3.3`, venv package versions `python-hwpx==2.10.1` and `hwpx-mcp-server==2.3.3`, government-report module imports, MCP server attributes, and launcher clean EOF startup.
- [x] **Cleanup:** Removed test plugin and marketplace after verification.

## Stage 완료 게이트

- [x] All required feature work was integrated into main release commits with duplicate base commits removed from the cherry-pick path.
- [x] `python-hwpx` is released, changelogged, tagged, and install-verified from PyPI.
- [x] `hwpx-mcp-server` depends on the released `python-hwpx`, exposes the new MCP tools, passes e2e tests, and is install-verified from PyPI.
- [x] `hwpx-skill` docs/templates/bundles/marketplace metadata are rebuilt and validated against the released MCP version.
- [x] Local marketplace install and real GitHub marketplace install both succeed.
- [x] 3-repo stack smoke passes and completion evidence records exact versions, commands, changed files, and remaining risks.
