"""Version literals in the plugin source come from the automation identity.

The automation ``src/hwpx_automation/identity.json`` (``releaseState``) is the
only place a release coordinate is written by hand. ``scripts/project_identity.py``
writes every projected field from it. These tests fail when

* a projected file drifts from the identity (someone edited a literal), or
* a release coordinate appears as a hand-written literal anywhere else.

The second check projects a *sentinel* identity in memory (every coordinate
replaced by a value that cannot occur), then looks for the real coordinates.
A real coordinate that survives was not produced by the projection.

Prose that still restates the public train (README and the API reference stack
tables) is frozen below as a ratchet: the counts may only go down, by turning
those passages into generated blocks.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IDENTITY = REPO / "src" / "hwpx_automation" / "identity.json"

_spec = importlib.util.spec_from_file_location("project_identity", ROOT / "scripts" / "project_identity.py")
assert _spec and _spec.loader
project_identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(project_identity)

# Files that may restate a coordinate because they record history or are
# generated from automation and gated elsewhere.
EXEMPT = (
    re.compile(r"^references/release-[^/]+\.md$"),  # dated release notes, immutable
    re.compile(r"^packaging/s\d{3}-[^/]+\.md$"),  # dated wording evidence records
    re.compile(r"^references/tool-contract\.generated\.(md|json)$"),  # render_tool_contract.py --check
    re.compile(r"^packaging/chatgpt/"),  # own chatgpt-plugin-v* line, hash-pinned wheels
    re.compile(r"^packaging/templates/claude-runtime/"),  # exact pins follow uv.lock; validate_claude_locked_runtime gates them
)

# Hand-written train literals still to be turned into generated blocks.
# Lower a count when you remove literals; never raise it. The README count is
# 12 while the source is `released`; a `release-approved` source also names the
# candidate train next to the public one (the validator requires both), so it
# reads 15 until the promotion commit takes those lines out again.
PENDING_PROSE = {
    "README.md": 14,
    "references/api.md": 15,
}

SCANNED_GLOBS = (
    "README.md",
    "SKILL.md",
    "references/*.md",
    "references/*.json",
    "packaging/*.json",
    "packaging/*.md",
    "packaging/templates/**/*",
)


def _identity() -> dict:
    return json.loads(IDENTITY.read_text(encoding="utf-8"))


def _coordinate_blocks(identity: dict) -> tuple[str, ...]:
    """releaseState blocks that carry coordinates; publicationEvidence is null until promotion."""
    blocks = ("candidate", "currentPublic", "previousPublic")
    if isinstance(identity["releaseState"].get("publicationEvidence"), dict):
        blocks += ("publicationEvidence",)
    return blocks


def _coordinates(identity: dict) -> dict[str, str]:
    """Every version and hash value written in releaseState."""
    state = identity["releaseState"]
    values: dict[str, str] = {}
    for block in _coordinate_blocks(identity):
        for key, value in state[block].items():
            if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+|[0-9a-f]{16}", value):
                values[f"{block}.{key}"] = value
    return values


def _sentinel(identity: dict) -> dict:
    sentinel = copy.deepcopy(identity)
    real = sorted(set(_coordinates(identity).values()))
    mapping = {
        value: (f"{90 + index}.{index}.{index}" if "." in value else f"{index:016x}".replace("0", "f"))
        for index, value in enumerate(real, start=1)
    }
    for block in _coordinate_blocks(identity):
        for key, value in list(sentinel["releaseState"][block].items()):
            if value in mapping:
                sentinel["releaseState"][block][key] = mapping[value]
    return sentinel


def _scanned_files() -> list[Path]:
    seen: set[Path] = set()
    for pattern in SCANNED_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
    return sorted(seen)


def test_projected_files_match_the_identity() -> None:
    drift = [
        path.relative_to(ROOT).as_posix()
        for path, text in project_identity.plan(_identity()).items()
        if path.read_bytes().decode("utf-8") != text
    ]
    assert not drift, f"run python plugins-src/scripts/project_identity.py: {drift}"


def test_no_hand_written_release_coordinate_outside_the_projection() -> None:
    identity = _identity()
    real = set(_coordinates(identity).values())
    projected = project_identity.plan(_sentinel(identity))
    pattern = re.compile(
        r"(?<![\w.])(" + "|".join(re.escape(v) for v in sorted(real, key=len, reverse=True)) + r")(?![\w.])"
    )
    hits: dict[str, list[str]] = {}
    for path in _scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        if any(rule.search(rel) for rule in EXEMPT):
            continue
        text = projected[path] if path in projected else path.read_bytes().decode("utf-8", "replace")
        found = [
            f"{rel}:{number}: {match.group(1)}"
            for number, line in enumerate(text.splitlines(), start=1)
            # Floors are projected from the tool contract, not from the identity,
            # so the sentinel does not move them; a floor may equal a coordinate.
            if not (path == project_identity.PRODUCT_IDENTITY and '"minimumCompatibleVersion"' in line)
            for match in pattern.finditer(line)
        ]
        if found:
            hits[rel] = found
    unexpected = {rel: lines for rel, lines in hits.items() if rel not in PENDING_PROSE}
    assert not unexpected, (
        "release coordinates written by hand; derive them in scripts/project_identity.py:\n"
        + "\n".join(line for lines in unexpected.values() for line in lines)
    )
    counts = {rel: len(hits.get(rel, [])) for rel in PENDING_PROSE}
    assert counts == PENDING_PROSE, (
        f"pending prose ratchet changed (lower PENDING_PROSE when you remove literals): {counts}"
    )


def test_the_sentinel_really_replaces_every_projected_coordinate() -> None:
    identity = _identity()
    sentinel = _sentinel(identity)
    assert set(_coordinates(identity).values()).isdisjoint(_coordinates(sentinel).values())


def test_minimum_versions_are_the_contract_floors() -> None:
    contract = json.loads((ROOT / "references" / "tool-contract.generated.json").read_text(encoding="utf-8"))
    projected = json.loads(project_identity.plan(_identity())[project_identity.PRODUCT_IDENTITY])
    components = projected["components"]
    assert components["core"]["minimumCompatibleVersion"] == contract["minPythonHwpx"]
    assert components["automation"]["minimumCompatibleVersion"] == contract["minAutomationVersion"]
    assert components["plugin"]["minimumCompatibleVersion"] == contract["minSkillVersion"]


def test_claude_version_follows_the_runtime_refresh_rule() -> None:
    """A refresh onto the candidate pair writes the plain version; the projection must agree."""
    spec = importlib.util.spec_from_file_location("refresh_claude_runtime", ROOT / "scripts" / "refresh_claude_runtime.py")
    assert spec and spec.loader
    refresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(refresh)
    identity = _identity()
    product = json.loads(project_identity.plan(identity)[project_identity.PRODUCT_IDENTITY])
    cand = identity["releaseState"]["candidate"]
    pair = {"core": cand["pythonHwpx"], "automation": cand["canonicalAutomation"]}
    for lock in (pair, {"core": "0.0.1", "automation": "0.0.2"}):
        coordinates = project_identity.coordinates(identity, lock)
        expected = refresh.claude_plugin_version(cand["plugin"], lock["core"], lock["automation"], product)
        assert project_identity._claude_version(coordinates) == expected
    assert project_identity._claude_version(project_identity.coordinates(identity, pair)) == cand["plugin"]
