#!/usr/bin/env python3
"""Validate every generated HWPX host bundle against packaging/hosts.json."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
CONFIG = PACKAGING / "hosts.json"
MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?P<target><[^>]*>|[^\s)]+)",
    re.MULTILINE,
)
EXTERNAL_LINK_SCHEMES = {"http", "https", "mailto"}
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


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


def _markdown_target_path(raw_target: str, label: str) -> str | None:
    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    target = target.strip()
    if not target or target.startswith("#"):
        return None
    require(not target.startswith("//"), f"{label}: network-relative link is not allowed: {target}")
    parsed = urlsplit(target)
    if parsed.scheme:
        require(
            parsed.scheme.lower() in EXTERNAL_LINK_SCHEMES,
            f"{label}: unsupported or unsafe link scheme: {target}",
        )
        return None
    require(not parsed.netloc, f"{label}: network-relative link is not allowed: {target}")
    path = unquote(parsed.path)
    if not path:
        return None
    require("\\" not in path, f"{label}: backslash path is not allowed: {target}")
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    require(not posix_path.is_absolute(), f"{label}: absolute local link is not allowed: {target}")
    require(not windows_path.is_absolute(), f"{label}: absolute local link is not allowed: {target}")
    require(not windows_path.drive, f"{label}: drive-qualified local link is not allowed: {target}")
    require(".." not in posix_path.parts, f"{label}: parent traversal is not allowed: {target}")
    require(".." not in windows_path.parts, f"{label}: parent traversal is not allowed: {target}")
    return path


def validate_markdown_links(paths: list[Path], root: Path, label: str) -> None:
    """Fail closed for missing local links or links escaping the supplied artifact root."""
    resolved_root = root.resolve()
    for markdown in sorted(set(paths)):
        require_file(markdown)
        text = markdown.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(text):
            raw_target = match.group("target")
            path = _markdown_target_path(raw_target, f"{label}: {markdown}")
            if path is None:
                continue
            target = (markdown.parent / path).resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError:
                raise SystemExit(
                    f"{label}: Markdown link escapes artifact root: {markdown} -> {raw_target}"
                ) from None
            require(
                target.exists(),
                f"{label}: missing Markdown link target: {markdown} -> {raw_target}",
            )


def frontmatter_of(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    require(text.startswith("---\n"), f"SKILL.md missing frontmatter: {skill_md}")
    return text.split("\n---\n", 1)[0]


def _require_fragments(path: Path, fragments: list[str], label: str) -> None:
    require_file(path)
    text = path.read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    require(not missing, f"{label} missing identity fragments: {missing}")


def validate_product_identity(config: dict, identity: dict) -> None:
    require(
        identity.get("schemaVersion") == "hwpx.product-identity.v1",
        "product identity schemaVersion mismatch",
    )
    require(
        identity.get("releaseState") == "released",
        "product identity must describe the approved public release",
    )
    components = identity.get("components")
    require(isinstance(components, dict), "product identity components missing")
    for component_name in ("core", "mcp", "plugin"):
        component = components.get(component_name)
        require(isinstance(component, dict), f"product identity missing {component_name}")
        for version_field in ("currentVersion", "minimumCompatibleVersion"):
            version = component.get(version_field)
            require(
                isinstance(version, str) and SEMVER_RE.fullmatch(version) is not None,
                f"product identity {component_name}.{version_field} is not semver",
            )
        require(
            component.get("maturity") in {"alpha", "beta", "stable", "not-declared"},
            f"product identity {component_name}.maturity invalid",
        )

    core = components["core"]
    mcp = components["mcp"]
    plugin = components["plugin"]
    require(
        identity.get("pluginPinPolicy") == {"core": "exact-current", "mcp": "exact-current"},
        "plugin pin policy must remain explicit exact-current",
    )
    require("pluginName" not in config and "skillName" not in config, "hosts.json duplicates product identity")
    for host in config["hosts"]:
        require(
            "version:" not in host.get("frontmatterExtra", ""),
            f"{host['id']}: version must come from product identity",
        )

    contract = load_json(ROOT / "references" / "tool-contract.generated.json")
    require(
        contract.get("minPythonHwpx") == core["minimumCompatibleVersion"],
        "contract/core minimum differs from product identity",
    )
    require(
        contract.get("minMcpVersion") == mcp["minimumCompatibleVersion"],
        "contract/MCP minimum differs from product identity",
    )
    require(
        contract.get("minSkillVersion") == plugin["minimumCompatibleVersion"],
        "contract/skill minimum differs from product identity",
    )

    skill_fm = frontmatter_of(ROOT / config["canonicalSkill"])
    require(
        f"name: {plugin['installedSkillName']}" in skill_fm,
        "canonical skill name differs from product identity",
    )

    first_party = identity["firstPartyLabelKo"]
    visual_note = identity["visualVerificationNoteKo"]
    readme = ROOT / "README.md"
    _require_fragments(
        readme,
        [
            first_party,
            visual_note,
            "공개 릴리스",
            "최소 호환 버전",
            "플러그인 설치 핀",
            "Development Status :: 3 - Alpha",
            "MCP 서버·플러그인 성숙도: 미선언",
            f"`{core['repository']} {core['currentVersion']}`",
            f"`{mcp['repository']} {mcp['currentVersion']}`",
            f"`{plugin['installedPluginId']} {plugin['currentVersion']}`",
        ],
        "README.md",
    )
    api = ROOT / "references" / "api.md"
    _require_fragments(
        api,
        [
            "공개 릴리스",
            "최소 호환 버전",
            "플러그인 설치 핀",
            f"`{core['distribution']} {core['currentVersion']}`",
            f"`{mcp['distribution']} {mcp['currentVersion']}`",
            f"`{plugin['installedPluginId']} {plugin['currentVersion']}`",
        ],
        "references/api.md",
    )

    claim_targets = [readme]
    template_manifests = [
        PACKAGING / "templates" / "claude.plugin.json",
        PACKAGING / "templates" / "codex.plugin.json",
        PACKAGING / "templates" / "openclaw.plugin.json",
    ]
    for manifest_path in template_manifests:
        manifest = load_json(manifest_path)
        manifest_id = manifest.get("id", manifest.get("name"))
        if manifest_path.name == "openclaw.plugin.json":
            manifest_id = manifest.get("id")
        require(manifest_id == plugin["installedPluginId"], f"{manifest_path}: plugin id mismatch")
        require(manifest.get("version") == plugin["currentVersion"], f"{manifest_path}: version mismatch")
        require("first-party" in manifest.get("description", ""), f"{manifest_path}: first-party scope missing")
        claim_targets.append(manifest_path)

    for path in claim_targets:
        text = path.read_text(encoding="utf-8")
        for forbidden in identity.get("forbiddenUnqualifiedClaimsKo", []):
            require(forbidden not in text, f"{path}: unqualified product claim remains: {forbidden}")

    mcp_pin = f"{mcp['distribution']}=={mcp['currentVersion']}"
    core_pin = f"{core['distribution']}[visual,preview]=={core['currentVersion']}"
    skill_env = f'"HWPX_SKILL_VERSION": "{plugin["currentVersion"]}"'
    for path in (
        PACKAGING / "templates" / "claude.mcp.json",
        PACKAGING / "templates" / "codex.mcp.json",
        PACKAGING / "templates" / "openclaw.mcp-install.md",
        PACKAGING / "templates" / "hermes.mcp-install.md",
    ):
        text = path.read_text(encoding="utf-8")
        require(
            plugin["currentVersion"] in text,
            f"{path}: skill version differs from product identity",
        )
        if path.name != "claude.mcp.json":
            require(mcp_pin in text and core_pin in text, f"{path}: package pins differ from product identity")
    require(skill_env in (PACKAGING / "templates" / "codex.mcp.json").read_text(encoding="utf-8"), "Codex MCP skill pin mismatch")

    _require_fragments(
        PACKAGING / "templates" / "hwpx-mcp-server",
        [mcp_pin, core_pin, f"HWPX_SKILL_VERSION:-{plugin['currentVersion']}"],
        "launcher template",
    )
    _require_fragments(
        ROOT / "scripts" / "clean_install_smoke.py",
        [
            f'"HWPX_MCP_SERVER_VERSION": "{mcp["currentVersion"]}"',
            f'"HWPX_PYTHON_HWPX_VERSION": "{core["currentVersion"]}"',
            f'"HWPX_SKILL_VERSION": "{plugin["currentVersion"]}"',
        ],
        "clean-install smoke",
    )
    profile = load_json(
        ROOT
        / "examples"
        / "eval_tasks"
        / "profiles"
        / f"current-{plugin['currentVersion']}.json"
    )
    require(profile.get("pluginVersion") == plugin["currentVersion"], "current replay profile version mismatch")
    require(
        profile.get("availableTools") == {"source": "generated-contract", "profile": "default"},
        "current replay profile must resolve tools from generated contract",
    )
    _require_fragments(
        PACKAGING / "s080-cross-repo-readme-wording.md",
        [
            "first-party",
            "Development Status :: 3 - Alpha",
            "actions/workflows/tests.yml/badge.svg",
            "서버 전체를\n> stateless라고 표현하지 않습니다.",
            f"hwpx-mcp-server {mcp['currentVersion']}",
            f"python-hwpx {core['currentVersion']}",
            f"hwpx-plugin {plugin['currentVersion']}",
            "현재 공개 릴리스",
        ],
        "cross-repository README evidence",
    )


def validate_sync(host: dict, out: Path, skill_dir: Path, identity: dict) -> set[Path]:
    sync_path = out / "plugin-sync.json"
    require_file(sync_path)
    sync = load_json(sync_path)
    require(sync.get("schemaVersion") == "hwpx.plugin-sync.v2", f"{host['id']}: bad sync schemaVersion")
    require(sync.get("host") == host["id"], f"{host['id']}: sync host mismatch")
    plugin_id = identity["components"]["plugin"]["installedPluginId"]
    require(sync.get("plugin") == plugin_id, f"{host['id']}: sync plugin identity mismatch")

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


def _canonical_server_package_line() -> str:
    """The SERVER_PACKAGE pin read from the canonical launcher template — the single
    source of truth. Deriving it here (instead of hardcoding a version) keeps this
    check from drifting behind what the bundles actually ship on a version bump."""
    template = PACKAGING / "templates" / "hwpx-mcp-server"
    for line in template.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("SERVER_PACKAGE="):
            return stripped
    raise SystemExit(f"canonical launcher template missing SERVER_PACKAGE=: {template}")


def validate_launcher(out: Path, host_id: str, identity: dict) -> None:
    launcher = out / "scripts" / "hwpx-mcp-server"
    require_file(launcher)
    require(os.access(launcher, os.X_OK), f"{host_id}: launcher not executable")
    text = launcher.read_text(encoding="utf-8")
    components = identity["components"]
    core_version = components["core"]["currentVersion"]
    mcp_version = components["mcp"]["currentVersion"]
    plugin_version = components["plugin"]["currentVersion"]
    fragments = [
        "find_stack_root",
        "HWPX_MCP_SERVER_REPO",
        "PYTHON_HWPX_REPO",
        "uv run --no-project",
        _canonical_server_package_line(),
        "HWPX_SKILL_VERSION",
        "HWPX_PLUGIN_ROOT",
        ".hwpx-mcp-runtime",
        "HWPX_MCP_RUNTIME_ROOT",
        ".hwpx-stack-fingerprint",
        "install.lock",
        "uv pip install",
        "--refresh-package hwpx-mcp-server",
        "--refresh-package python-hwpx",
        "--from \"${SERVER_PACKAGE}\"",
        f"hwpx-mcp-server=={mcp_version}",
        f"python-hwpx[visual,preview]=={core_version}",
        f"HWPX_SKILL_VERSION:-{plugin_version}",
    ]
    missing = [fragment for fragment in fragments if fragment not in text]
    require(not missing, f"{host_id}: launcher missing fragments: {missing}")


def validate_host(host: dict, config: dict, identity: dict) -> None:
    out = ROOT / host["outputDir"]
    require(out.is_dir(), f"{host['id']}: missing output dir {host['outputDir']}")
    skill_dir = out if host["skillSubdir"] == "." else out / host["skillSubdir"]

    skill_md = skill_dir / "SKILL.md"
    require_file(skill_md)
    validate_no_placeholder(skill_md, host["id"])
    fm = frontmatter_of(skill_md)
    components = identity["components"]
    plugin = components["plugin"]
    skill_name = plugin["installedSkillName"]
    plugin_id = plugin["installedPluginId"]
    plugin_version = plugin["currentVersion"]
    mcp = components["mcp"]
    core = components["core"]
    require(f"name: {skill_name}" in fm, f"{host['id']}: SKILL.md missing name")
    require("description:" in fm, f"{host['id']}: SKILL.md missing description")
    if host.get("includeVersionFrontmatter"):
        require(f"version: {plugin_version}" in fm, f"{host['id']}: SKILL.md version mismatch")
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
        require(data.get("version") == plugin_version, f"{host['id']}: manifest version mismatch")
        if host["id"] == "claude":
            require(data.get("name") == plugin_id, "claude: manifest name invalid")
            require(data.get("skills") == "./skills/", "claude: manifest skills invalid")
            require(data.get("mcpServers") == "./.mcp.json", "claude: manifest mcpServers invalid")
        elif host["id"] == "codex":
            require(data.get("name") == plugin_id, "codex: manifest name invalid")
            require(data.get("skills") == "./skills/", "codex: manifest skills invalid")
            require(data.get("mcpServers") == "./.mcp.json", "codex: manifest mcpServers invalid")
        elif host["id"] == "openclaw":
            require(data.get("id") == plugin_id, "openclaw: manifest id invalid")
            require(data.get("skills") == ["./skills"], "openclaw: manifest skills invalid")
            schema = data.get("configSchema")
            require(isinstance(schema, dict) and schema.get("type") == "object", "openclaw: configSchema invalid")
            require(schema.get("additionalProperties") is False, "openclaw: configSchema must set additionalProperties false")

    mcp_config = host["mcp"]
    mcp_path = out / mcp_config["dest"]
    require_file(mcp_path)
    if mcp_config["strategy"] == "bundled":
        mcp_data = load_json(mcp_path)
        server = mcp_data.get("mcpServers", {}).get(mcp["serverId"])
        require(isinstance(server, dict), f"{host['id']}: .mcp.json missing hwpx-mcp-server")
        command = server.get("command", "")
        if host["id"] == "claude":
            require("hwpx-mcp-server" in command, "claude: .mcp.json command invalid")
            require("${CLAUDE_PLUGIN_ROOT}" in command, "claude: .mcp.json must use ${CLAUDE_PLUGIN_ROOT}")
            require("cwd" not in server, "claude: .mcp.json must preserve project cwd")
        if host["id"] == "codex":
            args = server.get("args", [])
            require(command == "uvx", "codex: .mcp.json command must be root-independent uvx")
            require("cwd" not in server, "codex: .mcp.json must preserve the thread workspace cwd")
            require(
                f"{mcp['distribution']}=={mcp['currentVersion']}" in args,
                "codex: MCP package pin missing",
            )
            require(
                f"{core['distribution']}[visual,preview]=={core['currentVersion']}" in args,
                "codex: core package pin missing",
            )
        require(
            server.get("env", {}).get("HWPX_SKILL_VERSION") == plugin_version,
            f"{host['id']}: MCP skill version mismatch",
        )
    else:
        text = mcp_path.read_text(encoding="utf-8")
        require("mcp_servers" in text or "hwpx-mcp-server" in text, f"{host['id']}: INSTALL-mcp.md missing MCP guidance")

    if host.get("bundleLauncher"):
        validate_launcher(out, host["id"], identity)

    recorded = validate_sync(host, out, skill_dir, identity)
    validate_skill_files_match(host, skill_dir, recorded)
    validate_markdown_links(
        list(out.rglob("*.md")),
        out,
        f"{host['id']} bundle",
    )


def validate_marketplace(config: dict, identity: dict) -> None:
    plugin = identity["components"]["plugin"]
    for artifact in config.get("repoRootArtifacts", []):
        path = ROOT / artifact["dest"]
        require_file(path)
        if path.name == "marketplace.json":
            data = load_json(path)
            require(isinstance(data.get("name"), str) and data["name"], "marketplace: name invalid")
            plugins = data.get("plugins")
            require(isinstance(plugins, list) and plugins, "marketplace: plugins invalid")
            entry = plugins[0]
            require(entry.get("name") == plugin["installedPluginId"], "marketplace: plugin name invalid")
            if "version" in entry:
                require(entry["version"] == plugin["currentVersion"], "marketplace: plugin version invalid")
            if artifact["dest"].startswith(".claude-plugin/"):
                require(isinstance(data.get("owner"), dict), "claude marketplace: owner invalid")
                require(entry.get("source") == "./plugins/claude/hwpx-plugin", "claude marketplace: plugin source invalid")
            elif artifact["dest"].startswith(".agents/plugins/"):
                source = entry.get("source")
                require(isinstance(source, dict), "codex marketplace: source invalid")
                require(source.get("source") == "local", "codex marketplace: source type invalid")
                require(source.get("path") == "./plugins/codex/hwpx-plugin", "codex marketplace: plugin path invalid")
                policy = entry.get("policy")
                require(isinstance(policy, dict), "codex marketplace: policy invalid")
                require(policy.get("installation") == "AVAILABLE", "codex marketplace: installation policy invalid")
                require(policy.get("authentication") == "ON_INSTALL", "codex marketplace: authentication policy invalid")
                require(entry.get("category") == "Productivity", "codex marketplace: category invalid")


def main() -> int:
    config = load_json(CONFIG)
    identity_path = PACKAGING / config["identityFile"]
    require_file(identity_path)
    identity = load_json(identity_path)
    validate_product_identity(config, identity)
    canonical_markdown = [ROOT / config["canonicalSkill"]]
    canonical_markdown.extend(
        ROOT / rel for rel in config["sharedAssets"] if Path(rel).suffix.lower() == ".md"
    )
    validate_markdown_links(canonical_markdown, ROOT, "canonical bundle source")
    for host in config["hosts"]:
        validate_host(host, config, identity)
    validate_marketplace(config, identity)
    print(f"[OK] validated {len(config['hosts'])} host bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
