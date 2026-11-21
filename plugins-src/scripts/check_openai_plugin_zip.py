#!/usr/bin/env python3
"""Pre-flight a skills-only plugin ZIP against the OpenAI plugin portal rules.

The rules mirror https://developers.openai.com/plugins/deploy/submission-errors
(read 2026-09-29).  Directory limits (30-character display name and short
description, 128-character starter prompts) are used instead of the looser
validation limits, because the ZIP is meant for public submission.

Usage::

    python3 scripts/check_openai_plugin_zip.py dist/python-hwpx-plugin-1.0.0.zip
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import PurePosixPath

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_DEPTH = 20
CATEGORIES = {
    "Productivity", "Creativity", "Developer Tools", "Business & Operations", "Data & Analytics",
    "Communication", "Education & Research", "Security", "Finance", "Healthcare", "Travel",
    "Entertainment", "Other",
}
# Portal rule: "products must contain CHAT, CODEX, or both" (the local Codex loader spells it
# differently; the portal is the authority for submission).
PRODUCTS = {"CHAT", "CODEX"}
POLICY_KEYS = {"products", "allow_implicit_invocation"}
HTTPS_FIELDS = ("websiteURL", "privacyPolicyURL", "termsOfServiceURL", "supportURL")
HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")
FORBIDDEN_REVIEW_KEYS = ("test_credentials", "reviewer_instructions")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, flags=re.DOTALL)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    fields["__body__"] = match.group(2).strip()
    return fields


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _svg_square(data: bytes) -> bool:
    text = data.decode("utf-8")
    if not text.lstrip().startswith("<svg"):
        return False
    box = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*"', text)
    if box:
        width, height = float(box.group(1)), float(box.group(2))
    else:
        w = re.search(r'\swidth="([\d.]+)"', text)
        h = re.search(r'\sheight="([\d.]+)"', text)
        if not (w and h):
            return False
        width, height = float(w.group(1)), float(h.group(1))
    return width == height and width >= 48


def check(path: str) -> list[str]:
    problems: list[str] = []
    if len(open(path, "rb").read()) > MAX_ARCHIVE:
        problems.append("archive_too_large")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        files = {i.filename: i for i in infos if not i.is_dir()}
        if len(infos) > MAX_ENTRIES:
            problems.append("archive_too_many_entries")
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
            problems.append("archive_uncompressed_too_large")
        for info in infos:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                problems.append(f"archive_member_type_unsupported (symlink): {info.filename}")
        seen = set()
        for name in names:
            parts = PurePosixPath(name.rstrip("/")).parts
            if "\\" in name or name.startswith("/") or ".." in parts or name != name.strip():
                problems.append(f"archive_member_path_unsafe: {name}")
            if len(parts) > MAX_DEPTH:
                problems.append(f"archive_member_path_too_deep: {name}")
            key = unicodedata.normalize("NFC", name).casefold()
            if key in seen:
                problems.append(f"archive_member_path_normalization_collision: {name}")
            seen.add(key)

        if "plugin.json" not in files:
            return problems + ["plugin_manifest_missing: plugin.json must sit at the archive root"]
        for forbidden in (".mcp.json", "mcp.json", ".app.json"):
            if forbidden in files:
                problems.append(f"mcp/app configuration excluded from skills-only upload: {forbidden}")

        manifest = json.loads(archive.read("plugin.json"))
        name = manifest.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            problems.append("plugin_name_format")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", manifest.get("version", "")):
            problems.append("plugin_version_not_semver")
        if not 0 < len(manifest.get("description", "")) <= 1024:
            problems.append("plugin_description length")
        for key in ("mcpServers", "apps", "skills"):
            if key in manifest:
                problems.append(f"portable skills-only manifest must not declare {key} (skills/ is discovered automatically)")
        openai_ext = manifest.get("extensions", {}).get("com.openai", {})
        if "hooks" in openai_ext or "apps" in openai_ext or any(n.startswith("hooks/") for n in names):
            problems.append("ZIPs with lifecycle hooks or app references cannot currently be submitted")
        review = openai_ext.get("review") or {}
        for key in FORBIDDEN_REVIEW_KEYS:
            if key in review:
                problems.append(f"review.{key} must not be in the package; enter reviewer access in the dashboard")
        publication = openai_ext.get("publication") or {}
        for locale, text in (publication.get("translations") or {}).items():
            if not locale.strip() or not isinstance(text, dict):
                problems.append(f"publication.translations: invalid locale entry {locale!r}")
                continue
            subtitle, description = text.get("subtitle"), text.get("description")
            if subtitle is not None and (not subtitle.strip() or len(subtitle) > 30 or "\n" in subtitle or "\t" in subtitle):
                problems.append(f"publication.translations.{locale}.subtitle must be one line of 1-30 characters")
            if description is not None and (not description.strip() or len(description) > 4000 or "\t" in description):
                problems.append(f"publication.translations.{locale}.description must be 1-4000 characters without tabs")
        author = manifest.get("author", {})
        if not author.get("name"):
            problems.append("plugin_developer_missing: author.name")
        if author.get("url") and not author["url"].startswith("https://"):
            problems.append("plugin_author_url_not_https")

        ui = manifest.get("extensions", {}).get("com.openai", {}).get("interface") or manifest.get("interface", {})
        limits = {"displayName": 30, "shortDescription": 30, "longDescription": 4000, "developerName": 80}
        for key, limit in limits.items():
            value = ui.get(key, "")
            if not value or len(value) > limit or (key != "longDescription" and "\n" in value):
                problems.append(f"interface.{key} required, single-line where applicable, <= {limit} chars")
        if ui.get("developerName") != author.get("name"):
            problems.append("developer_name_defaulted: author.name and interface.developerName differ")
        if ui.get("category", "Other") not in CATEGORIES:
            problems.append(f"plugin_category_unknown: {ui.get('category')}")
        for key in HTTPS_FIELDS:
            if not str(ui.get(key, "")).startswith("https://"):
                problems.append(f"interface.{key} must be an HTTPS URL")
        base_text = [ui.get(k, "") for k in ("displayName", "shortDescription", "longDescription")]
        base_text += ui.get("defaultPrompt", []) if isinstance(ui.get("defaultPrompt"), list) else [ui.get("defaultPrompt", "")]
        if any(HANGUL.search(text or "") for text in base_text):
            problems.append("base listing fields must be English; put Korean text in publication.translations.ko-KR")
        prompts = ui.get("defaultPrompt", [])
        prompts = [prompts] if isinstance(prompts, str) else prompts
        normalized = [" ".join(unicodedata.normalize("NFKC", p).split()) for p in prompts]
        if len(prompts) > 3 or any(len(p) > 128 or "\n" in p or "@" in p for p in prompts) or len(set(normalized)) != len(normalized):
            problems.append("interface.defaultPrompt: at most 3 unique single-line prompts, <= 128 chars, no @mentions")
        for key, background, minimum in (("brandColor", "#FFFFFF", 2.0), ("brandColorDark", "#212121", 2.0)):
            color = ui.get(key)
            if color is not None:
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                    problems.append(f"interface.{key} must be #RRGGBB")
                elif _contrast(color, background) < minimum:
                    problems.append(f"interface.{key} contrast below {minimum}:1 against {background}")
        for key in ("logo", "composerIcon"):
            ref = ui.get(key, "")
            member = ref[2:] if ref.startswith("./") else None
            if member is None:
                problems.append(f"interface.{key} must start with ./")
            elif member not in files:
                problems.append(f"interface.{key} file missing: {ref}")
            elif not member.endswith(".svg"):
                problems.append(f"interface.{key}: this checker only validates SVG icons")
            elif not _svg_square(archive.read(member)):
                problems.append(f"interface.{key} must be a square SVG of at least 48x48")

        skill_dirs = sorted({PurePosixPath(n).parts[1] for n in names if n.startswith("skills/") and len(PurePosixPath(n).parts) > 2})
        if not skill_dirs:
            problems.append("archive_plugin_files_missing: no skill under skills/")
        skill_names = []
        for skill in skill_dirs:
            if skill.startswith("."):
                problems.append(f"skill_directory_hidden: {skill}")
            skill_md = f"skills/{skill}/SKILL.md"
            if skill_md not in files:
                problems.append(f"skill_manifest_missing: {skill_md}")
                continue
            front = _frontmatter(archive.read(skill_md).decode("utf-8"))
            if not front.get("name") or not front.get("description") or not front.get("__body__"):
                problems.append(f"{skill_md}: name, description and body are required")
                continue
            if len(front["description"]) > 1024:
                problems.append(f"skill_description_too_long: {skill}")
            if len(f"{name}:{front['name']}") > 64:
                problems.append(f"skill_identity_too_long: {name}:{front['name']}")
            skill_names.append(front["name"])
            agent = f"skills/{skill}/agents/openai.yaml"
            if agent in files:
                text = archive.read(agent).decode("utf-8")
                for product in re.findall(r"^\s*-\s*(\S+)\s*$", text, flags=re.MULTILINE):
                    if product not in PRODUCTS:
                        problems.append(f"{agent}: products must be CHAT and/or CODEX, got {product}")
                policy = re.search(r"^policy:\n((?:[ \t]+.*\n?)*)", text, flags=re.MULTILINE)
                if policy:
                    keys = set(re.findall(r"^[ \t]{2}([A-Za-z_]+):", policy.group(1), flags=re.MULTILINE))
                    if keys - POLICY_KEYS:
                        problems.append(f"{agent}: policy may contain only {sorted(POLICY_KEYS)}, got {sorted(keys)}")
                if not re.search(r"display_name:\s*\S", text) or not re.search(r"short_description:\s*\S", text):
                    problems.append(f"{agent}: interface.display_name and short_description are required")
        if len(skill_names) != len(set(skill_names)):
            problems.append("skill_identity_duplicate")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip")
    args = parser.parse_args(argv)
    problems = check(args.zip)
    for problem in problems:
        print(f"[FAIL] {problem}")
    print("[OK] portal pre-flight passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
