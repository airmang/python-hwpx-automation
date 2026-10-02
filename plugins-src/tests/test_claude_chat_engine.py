"""The Claude bundle's no-MCP path: vendored engine integrity and the generated guide."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "plugins" / "claude" / "hwpx-plugin"
SKILL = BUNDLE / "skills" / "hwpx"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_vendored_engine_is_the_locked_pair_and_within_directory_limits() -> None:
    vendor = _load("vendor_claude_engine")
    assert vendor.check() == []
    manifest = json.loads((SKILL / "engine" / "VENDOR.json").read_text(encoding="utf-8"))
    pins = dict(re.findall(r'"(python-hwpx(?:-automation)?)\[[^\]]*\]==([^"]+)"',
                           (BUNDLE / "server" / "pyproject.toml").read_text(encoding="utf-8")))
    assert {w["distribution"]: w["version"] for w in manifest["wheels"]} == pins
    # importlib.metadata needs the dist-info METADATA to report __version__ from the vendored path.
    for wheel in manifest["wheels"]:
        stem = wheel["filename"].split("-py3-none-any")[0]
        assert f"{stem}.dist-info/METADATA" in manifest["files"]


def test_engine_check_detects_an_edited_or_extra_file(tmp_path, monkeypatch) -> None:
    vendor = _load("vendor_claude_engine")
    bundle = tmp_path / "hwpx-plugin"
    shutil.copytree(BUNDLE, bundle, ignore=shutil.ignore_patterns("__pycache__"))
    engine = bundle / "skills" / "hwpx" / "engine"
    monkeypatch.setattr(vendor, "BUNDLE", bundle)
    monkeypatch.setattr(vendor, "ENGINE", engine)
    monkeypatch.setattr(vendor, "MANIFEST", engine / "VENDOR.json")
    assert vendor.check() == []

    target = engine / "hwpx" / "__init__.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    (engine / "hwpx" / "extra.py").write_text("", encoding="utf-8")
    problems = vendor.check()
    assert any("engine file changed: hwpx/__init__.py" in p for p in problems)
    assert any("extra" in p and "hwpx/extra.py" in p for p in problems)


def test_chat_guide_is_rendered_for_claude_without_chatgpt_paths() -> None:
    guide = (SKILL / "chat-engine.md").read_text(encoding="utf-8")
    for block in ("# W1 ", "# W2 ", "# W3 ", "# W4 ", "# W5 "):
        assert block in guide
    for leftover in ("/mnt/data/", "`/mnt/data`의", "sandbox:", "](core/", "automation-python-api.md", "{{"):
        assert leftover not in guide
    assert "sys.path.insert(0, ENGINE)" in guide
    assert "from hwpx_automation import api" in guide  # package import alone does not prove pydantic
    for target in re.findall(r"\]\((engine/[^)#]+)\)", guide):
        assert (SKILL / target).is_file(), target


def test_only_the_claude_bundle_carries_the_engine_and_every_skill_points_to_it() -> None:
    for skill_md in ROOT.glob("plugins/*/*/**/SKILL.md"):
        if "/engine/" in skill_md.as_posix():
            continue
        assert "`chat-engine.md`" in skill_md.read_text(encoding="utf-8")
    hosts_with_engine = sorted(p.parents[4].name for p in ROOT.glob("plugins/*/*/skills/hwpx/engine/VENDOR.json"))
    assert hosts_with_engine == ["claude"]


def test_claude_bundle_text_never_pipes_a_download_into_a_shell() -> None:
    # The Claude plugin directory flags download-and-run commands anywhere in shipped text
    # (RUNTIME_FETCH_EXEC), including skill prose that only tells the user what to run.
    fetch_exec = re.compile(
        r"(curl|wget|irm|iwr|Invoke-WebRequest|Invoke-RestMethod)\b[^\n`]*\|\s*(sh|bash|zsh|iex|python3?|pwsh|powershell)\b"
    )
    offenders = [
        path.relative_to(BUNDLE).as_posix()
        for path in BUNDLE.rglob("*")
        if path.is_file() and path.suffix in {".md", ".json", ".txt", ".py", ".toml", ".sh", ""}
        and fetch_exec.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == []
