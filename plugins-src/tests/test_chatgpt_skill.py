# SPDX-License-Identifier: Apache-2.0
"""G1 gate for the ChatGPT web skill (``hwpx-web``): lock, source and ZIP shape."""

import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packaging" / "chatgpt"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build = _load("build_chatgpt_skill")
sim = _load("chatgpt_sandbox_sim")
portal = _load("check_openai_plugin_zip")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_lock_pins_current_public_train() -> None:
    lock = build.load_json(build.LOCK)
    build.check_lock(lock)
    wheels = {w["distribution"] for w in lock["wheels"]}
    assert {"python-hwpx", "python-hwpx-automation"} <= wheels
    assert all(w["filename"].endswith("-py3-none-any.whl") for w in lock["wheels"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in lock["wheels"] + lock["coreDocs"])


def test_skill_frontmatter_follows_agent_skills_limits() -> None:
    fields = _frontmatter((SOURCE / "skill" / "SKILL.md").read_text(encoding="utf-8"))
    assert fields["name"] == build.load_json(build.SOURCES)["skillName"] == "hwpx-web"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    rendered = build.render_template(fields["description"], build.load_json(build.LOCK))
    assert 0 < len(rendered) <= 1024


def test_only_known_build_tokens_are_used() -> None:
    known = {"{{WEB_VERSION}}", "{{CORE_VERSION}}", "{{AUTOMATION_VERSION}}", "{{CORE_WHEEL}}", "{{AUTOMATION_WHEEL}}"}
    for path in SOURCE.rglob("*"):
        if path.is_file() and path.suffix in build.TEMPLATE_SUFFIXES:
            used = set(build.BUILD_TOKEN.findall(path.read_text(encoding="utf-8")))
            assert used <= known, f"{path}: {used - known}"


def test_code_blocks_use_only_the_public_engine_surface() -> None:
    skill_md = (SOURCE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    workflows = sim.workflow_blocks((SOURCE / "skill" / "references" / "web-workflows.md").read_text(encoding="utf-8"))
    assert sorted(workflows) == ["W1", "W2", "W3", "W4", "W5"]
    problems = sim.check_imports("prelude", sim.python_blocks(skill_md)[0])
    for block, code in workflows.items():
        problems += sim.check_imports(block, code)
        sim.inject_overrides(code, {})  # every block exposes a P parameter mapping
    assert problems == []


def test_every_workflow_block_has_simulation_cases() -> None:
    workflows = sim.workflow_blocks((SOURCE / "skill" / "references" / "web-workflows.md").read_text(encoding="utf-8"))
    covered = {case[1] for case in sim.CASES}
    assert covered == set(workflows)
    refusals = {case[1] for case in sim.CASES if case[4] == "refuse"}
    assert {"W2", "W3", "W4", "W5"} <= refusals


def _fake_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Swap network fetches for deterministic local bytes with matching digests."""
    lock = json.loads(json.dumps(build.load_json(build.LOCK)))
    payloads = {}
    for item in lock["wheels"] + lock["coreDocs"]:
        if item in lock["wheels"]:
            data = _real_wheel_bytes(item["distribution"], "MIT")
        else:
            data = f"stand-in for {item['url']}".encode()
        item["sha256"] = hashlib.sha256(data).hexdigest()
        payloads[item["url"]] = data
    monkeypatch.setattr(build, "fetch", lambda url: payloads[url])
    monkeypatch.setattr(build, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    return lock


def test_zip_has_one_top_folder_and_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = _fake_lock(tmp_path, monkeypatch)
    first, first_plugin = build.build(lock)
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, first_plugin)]
    second, second_plugin = build.build(lock)
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (second, second_plugin)] == digests
    assert first.name == f"hwpx-web-{build.web_version()}.zip"

    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert {name.split("/")[0] for name in names} == {"hwpx-web"}
        for required in (
            "hwpx-web/SKILL.md",
            "hwpx-web/skill-manifest.json",
            "hwpx-web/THIRD_PARTY_NOTICES.md",
            "hwpx-web/agents/openai.yaml",
            "hwpx-web/scripts/bootstrap.py",
            "hwpx-web/wheels/SHA256SUMS",
            "hwpx-web/references/web-workflows.md",
            "hwpx-web/references/automation-python-api.md",
            "hwpx-web/references/core/llms.txt",
        ):
            assert required in names
        skill_md = archive.read("hwpx-web/SKILL.md").decode("utf-8")
        assert not build.BUILD_TOKEN.search(skill_md)
        manifest = json.loads(archive.read("hwpx-web/skill-manifest.json"))
        assert manifest["version"] == build.web_version()
        assert manifest["core"] == lock["versions"]["core"]
        assert manifest["automation"] == lock["versions"]["automation"]
        sums = archive.read("hwpx-web/wheels/SHA256SUMS").decode()
        assert all(w["sha256"] in sums for w in lock["wheels"])
        skill_files = {n.split("/", 1)[1]: archive.read(n) for n in names if not n.endswith("/")}

    with zipfile.ZipFile(first_plugin) as archive:
        plugin_names = archive.namelist()
        assert "plugin.json" in plugin_names  # portal expects the manifest at the archive root
        plugin_skill = {n.split("/", 2)[2]: archive.read(n) for n in plugin_names if n.startswith("skills/hwpx-web/") and not n.endswith("/")}
        assert plugin_skill == skill_files
        assert json.loads(archive.read("plugin.json"))["version"] == build.web_version()


def _real_wheel_bytes(name: str, license_expr: str) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}.dist-info/METADATA", f"Name: {name}\nLicense-Expression: {license_expr}\nProject-URL: Source, https://example.org/{name}\n")
    return buffer.getvalue()


def test_plugin_zip_passes_portal_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = _fake_lock(tmp_path, monkeypatch)
    _, plugin_zip = build.build(lock)
    assert portal.check(str(plugin_zip)) == []


def test_portal_preflight_rejects_mcp_config_and_long_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = _fake_lock(tmp_path, monkeypatch)
    _, plugin_zip = build.build(lock)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(plugin_zip) as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "plugin.json":
                manifest = json.loads(data)
                manifest["extensions"]["com.openai"]["interface"]["displayName"] = "x" * 31
                data = json.dumps(manifest).encode()
            dst.writestr(info, data)
        dst.writestr(".mcp.json", "{}")
    problems = portal.check(str(bad))
    assert any(".mcp.json" in p for p in problems)
    assert any("displayName" in p for p in problems)


def test_build_refuses_a_tampered_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = _fake_lock(tmp_path, monkeypatch)
    lock["wheels"][0]["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        build.assemble(lock)


def test_build_skips_hidden_files_and_bytecode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    import shutil

    shutil.copytree(build.SOURCE, source)
    (source / "skill" / ".DS_Store").write_bytes(b"x")
    (source / "skill" / "scripts" / "__pycache__").mkdir()
    (source / "skill" / "scripts" / "__pycache__" / "bootstrap.cpython-312.pyc").write_bytes(b"x")
    monkeypatch.setattr(build, "SOURCE", source)
    lock = _fake_lock(tmp_path, monkeypatch)
    skill_zip, plugin_zip = build.build(lock)
    for archive_path in (skill_zip, plugin_zip):
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
        assert not [n for n in names if "/." in n or n.startswith(".") or "__pycache__" in n]
        assert any(n.endswith("LICENSE") for n in names)


def test_portal_preflight_requires_portal_product_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = _fake_lock(tmp_path, monkeypatch)
    _, plugin_zip = build.build(lock)
    with zipfile.ZipFile(plugin_zip) as archive:
        yaml_text = archive.read("skills/hwpx-web/agents/openai.yaml").decode()
    assert "- CHAT\n" in yaml_text
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(plugin_zip) as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "skills/hwpx-web/agents/openai.yaml":
                data = data.replace(b"- CHAT\n", b"- CHATGPT\n")
            dst.writestr(info, data)
    assert any("CHAT and/or CODEX" in p for p in portal.check(str(bad)))
