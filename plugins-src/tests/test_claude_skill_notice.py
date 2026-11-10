# SPDX-License-Identifier: Apache-2.0
"""The Claude bundle's host-only SKILL.md notice (audit ENG-01).

The Claude bundle pins python-hwpx 6.8.0, which fills the wrong cell in
documents with nested tables. Until the pin reaches 6.11.0 the Claude SKILL.md
carries one notice telling the agent to re-read such fills. It lives in one
template so that retiring it is deleting that file and its hosts.json key.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ROOT / "packaging" / "templates" / "claude-skill-notice.md"
FIXED_IN = (6, 11, 0)


def _builder():
    spec = importlib.util.spec_from_file_location("build_hwpx_plugins", ROOT / "scripts" / "build_hwpx_plugins.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _hosts() -> dict[str, dict]:
    config = json.loads((ROOT / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    return {host["id"]: host for host in config["hosts"]}


def _skill_md(host: dict) -> Path:
    out = ROOT / host["outputDir"]
    return (out if host["skillSubdir"] == "." else out / host["skillSubdir"]) / "SKILL.md"


def _vendored_core_version() -> tuple[int, ...]:
    vendor = json.loads(
        (ROOT / "plugins/claude/hwpx-plugin/skills/hwpx/engine/VENDOR.json").read_text(encoding="utf-8")
    )
    version = next(w["version"] for w in vendor["wheels"] if w["distribution"] == "python-hwpx")
    return tuple(int(part) for part in version.split("."))


def test_notice_is_rendered_under_the_first_heading_and_only_when_given() -> None:
    builder = _builder()
    canonical = "---\nname: hwpx\n---\n\n# hwpx\n\nbody\n\n# later\n"

    assert builder.render_skill_md(canonical, "") == canonical
    rendered = builder.render_skill_md(canonical, "", "> notice line 1\n> notice line 2\n")

    assert rendered == "---\nname: hwpx\n---\n\n# hwpx\n\n> notice line 1\n> notice line 2\n\nbody\n\n# later\n"


def test_nested_table_notice_ships_in_the_claude_skill_only() -> None:
    hosts = _hosts()
    notice = NOTICE.read_text(encoding="utf-8")
    assert "표 안에 표" in notice and "다시 읽어" in notice and "쓰지 않고" in notice

    assert hosts["claude"].get("skillNotice") == "templates/claude-skill-notice.md"
    assert notice.strip() in _skill_md(hosts["claude"]).read_text(encoding="utf-8")
    for host_id in ("codex", "openclaw", "hermes"):
        assert "skillNotice" not in hosts[host_id]
        assert "표 안에 표가 있는 문서의 칸 채움" not in _skill_md(hosts[host_id]).read_text(encoding="utf-8")
    # One place only: the canonical skill and the chat guide do not repeat it.
    assert "표 안에 표가 있는 문서의 칸 채움" not in (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "표 안에 표가 있는 문서의 칸 채움" not in (
        ROOT / "packaging/templates/claude-chat-engine.md"
    ).read_text(encoding="utf-8")


def test_notice_is_retired_once_the_bundled_engine_has_the_fix() -> None:
    """Fails when the Claude engine pin reaches the fixed core: delete the notice then."""

    vendored = _vendored_core_version()
    notice = NOTICE.read_text(encoding="utf-8")
    assert vendored < FIXED_IN, (
        "the bundled python-hwpx now has the nested-table fix: remove "
        "packaging/templates/claude-skill-notice.md and the claude host's skillNotice key"
    )
    assert ".".join(str(part) for part in vendored) in notice, "the notice must name the bundled engine version"
