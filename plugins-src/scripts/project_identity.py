#!/usr/bin/env python3
"""Project the release coordinates of the automation identity into the plugin source.

One place holds every version: ``src/hwpx_automation/identity.json``
(``releaseState``). Before the hwpx-plugins source moved into this repository,
``packaging/product-identity.json`` (25 version literals) and about a dozen
template files (about 65 more) restated those coordinates by hand or through a
daily bot, and drifted. This script writes them all from the identity.

    python plugins-src/scripts/project_identity.py            # write
    python plugins-src/scripts/project_identity.py --check    # fail on drift

Derivation rules (each is a decision, see ``RULES`` below to change one):

* plugin version            = ``candidate.plugin``
* component currentVersion  = candidate coordinates
* minimumCompatibleVersion  = ``<candidate major>.0.0`` of that component
* installConstraint         = ``<name[extras]> >=<candidate>,<<major+1>``
* verifiedStack             = candidate (``verifiedAt`` stays as recorded data)
* currentPublicStack        = ``currentPublic``
* Claude plugin version     = ``<plugin>+core.<locked core>.automation.<locked automation>``
  where the locked pair is read from ``packaging/templates/claude-runtime/uv.lock``.
  The Claude runtime is pinned by that lock (``uv run --frozen``); its pins
  follow the lock, not the identity, so the daily runtime refresh still moves
  them and every refresh still changes the Claude plugin version.

Not projected (own version line or prose; see ``tests/test_identity_projection.py``
for the allowlist): ``packaging/chatgpt/*`` (ChatGPT plugin has its own
``chatgpt-plugin-v*`` line and hash-pinned wheels), historical notes in
README/SKILL/install guides.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore[no-redef, unused-ignore]

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
IDENTITY = REPO_ROOT / "src" / "hwpx_automation" / "identity.json"
PRODUCT_IDENTITY = PLUGIN_ROOT / "packaging" / "product-identity.json"
TEMPLATES = PLUGIN_ROOT / "packaging" / "templates"
CLAUDE_LOCK = TEMPLATES / "claude-runtime" / "uv.lock"


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def _constraint(existing: str, version: str) -> str:
    """Keep the requirement name and extras, regenerate the specifier."""
    head = re.match(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)", existing)
    if head is None:
        raise SystemExit(f"cannot parse install constraint: {existing!r}")
    return f"{head.group(1)}>={version},<{_major(version) + 1}"


def _set(doc: dict[str, Any], pointer: str, value: Any) -> None:
    parts = pointer.strip("/").split("/")
    node: Any = doc
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def _get(doc: dict[str, Any], pointer: str) -> Any:
    node: Any = doc
    for part in pointer.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def locked_runtime(lock_path: Path = CLAUDE_LOCK) -> dict[str, str]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    found = {p["name"]: p["version"] for p in data.get("package", [])}
    try:
        return {"core": found["python-hwpx"], "automation": found["python-hwpx-automation"]}
    except KeyError as exc:  # pragma: no cover - lock shape guard
        raise SystemExit(f"{lock_path}: missing locked package {exc}") from None


def coordinates(identity: dict[str, Any], lock: dict[str, str]) -> dict[str, Any]:
    state = identity["releaseState"]
    cand = state["candidate"]
    return {
        "status": state["status"],
        "candidate": cand,
        "currentPublic": state["currentPublic"],
        "previousPublic": state["previousPublic"],
        "promotionGate": state["promotionGate"],
        "publicationEvidence": state["publicationEvidence"],
        "core": cand["pythonHwpx"],
        "automation": cand["canonicalAutomation"],
        "plugin": cand["plugin"],
        "contractHash": cand["contractHash"],
        "lock": lock,
    }


# --- product-identity.json -------------------------------------------------

Rule = Callable[[dict[str, Any], dict[str, Any]], Any]

RULES: list[tuple[str, Rule]] = [
    ("/releaseState/status", lambda c, d: c["status"]),
    ("/releaseState/candidate", lambda c, d: copy.deepcopy(c["candidate"])),
    ("/releaseState/currentPublic", lambda c, d: copy.deepcopy(c["currentPublic"])),
    ("/releaseState/previousPublic", lambda c, d: copy.deepcopy(c["previousPublic"])),
    ("/releaseState/promotionGate", lambda c, d: c["promotionGate"]),
    ("/releaseState/publicationEvidence", lambda c, d: copy.deepcopy(c["publicationEvidence"])),
    ("/currentPublicStack/core/version", lambda c, d: c["currentPublic"]["pythonHwpx"]),
    ("/currentPublicStack/application/version", lambda c, d: c["currentPublic"]["primaryApplication"]),
    ("/currentPublicStack/plugin/version", lambda c, d: c["currentPublic"]["plugin"]),
    ("/components/core/currentVersion", lambda c, d: c["core"]),
    ("/components/core/minimumCompatibleVersion", lambda c, d: f"{_major(c['core'])}.0.0"),
    ("/components/automation/currentVersion", lambda c, d: c["automation"]),
    ("/components/automation/minimumCompatibleVersion", lambda c, d: f"{_major(c['automation'])}.0.0"),
    ("/components/plugin/currentVersion", lambda c, d: c["plugin"]),
    ("/components/plugin/minimumCompatibleVersion", lambda c, d: f"{_major(c['plugin'])}.0.0"),
    ("/verifiedStack/pythonHwpx", lambda c, d: c["core"]),
    ("/verifiedStack/automation", lambda c, d: c["automation"]),
    ("/verifiedStack/plugin", lambda c, d: c["plugin"]),
    ("/verifiedStack/contractHash", lambda c, d: c["contractHash"]),
    ("/installConstraint/core", lambda c, d: _constraint(_get(d, "/installConstraint/core"), c["core"])),
    ("/installConstraint/automation",
     lambda c, d: _constraint(_get(d, "/installConstraint/automation"), c["automation"])),
]


def project_product_identity(text: str, c: dict[str, Any]) -> str:
    doc = json.loads(text)
    for pointer, rule in RULES:
        _set(doc, pointer, rule(c, doc))
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


# --- templates --------------------------------------------------------------

JSON_TEMPLATES: list[tuple[str, str, Callable[[dict[str, Any]], str]]] = [
    ("claude.plugin.json", "/version",
     lambda c: f"{c['plugin']}+core.{c['lock']['core']}.automation.{c['lock']['automation']}"),
    ("claude.mcp.json", "/mcpServers/hwpx/env/HWPX_SKILL_VERSION", lambda c: c["plugin"]),
    ("codex.mcp.json", "/mcpServers/hwpx/env/HWPX_SKILL_VERSION", lambda c: c["plugin"]),
    ("codex.plugin.json", "/version", lambda c: c["plugin"]),
    ("codex.marketplace.json", "/plugins/0/version", lambda c: c["plugin"]),
    ("openclaw.plugin.json", "/version", lambda c: c["plugin"]),
]

LAUNCHER = "hwpx-automation-mcp"


def _launcher_lines(c: dict[str, Any], pi: dict[str, Any]) -> dict[str, str]:
    return {
        "VERIFIED_SERVER_PACKAGE": f"python-hwpx-automation[mcp,oracle]=={c['automation']}",
        "VERIFIED_CORE_PACKAGE": f"python-hwpx[preview]=={c['core']}",
        "CONSTRAINT_SERVER_PACKAGE": pi["installConstraint"]["automation"],
        "CONSTRAINT_CORE_PACKAGE": pi["installConstraint"]["core"],
    }


def project_json_template(text: str, pointer: str, value: str) -> str:
    """Replace one JSON string value in place, keeping the file's formatting."""
    doc = json.loads(text)
    old = _get(doc, pointer)
    if old == value:
        return text
    key = pointer.rsplit("/", 1)[1]
    if key.isdigit():  # pragma: no cover - templates address object keys only
        raise SystemExit(f"unsupported pointer {pointer}")
    pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*)"{re.escape(str(old))}"')
    new, count = pattern.subn(lambda m: f'{m.group(1)}"{value}"', text)
    if count != 1:
        raise SystemExit(f"expected one {key!r} value {old!r}, found {count}")
    if _get(json.loads(new), pointer) != value:  # pragma: no cover - guard
        raise SystemExit(f"projection of {pointer} did not land")
    return new


def project_launcher(text: str, c: dict[str, Any], pi: dict[str, Any]) -> str:
    for name, value in _launcher_lines(c, pi).items():
        text, count = re.subn(rf'^{name}="[^"\n]*"$', f'{name}="{value}"', text, flags=re.MULTILINE)
        if count != 1:
            raise SystemExit(f"{LAUNCHER}: expected one {name}= line, found {count}")
    text, count = re.subn(
        r'(HWPX_SKILL_VERSION="\$\{HWPX_SKILL_VERSION:-)[^}]*(\}")',
        lambda m: f"{m.group(1)}{c['plugin']}{m.group(2)}",
        text,
    )
    if count != 1:
        raise SystemExit(f"{LAUNCHER}: expected one HWPX_SKILL_VERSION default, found {count}")
    return text


# --- driver -----------------------------------------------------------------


def plan(identity: dict[str, Any], plugin_root: Path = PLUGIN_ROOT) -> dict[Path, str]:
    """Return {path: projected text} for every projected file."""
    templates = plugin_root / "packaging" / "templates"
    c = coordinates(identity, locked_runtime(templates / "claude-runtime" / "uv.lock"))
    out: dict[Path, str] = {}
    pi_path = plugin_root / "packaging" / "product-identity.json"
    pi_text = project_product_identity(pi_path.read_text(encoding="utf-8"), c)
    out[pi_path] = pi_text
    for name, pointer, value in JSON_TEMPLATES:
        path = templates / name
        out[path] = project_json_template(path.read_text(encoding="utf-8"), pointer, value(c))
    launcher = templates / LAUNCHER
    out[launcher] = project_launcher(launcher.read_text(encoding="utf-8"), c, json.loads(pi_text))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail when a projected file differs")
    parser.add_argument("--identity", type=Path, default=IDENTITY)
    args = parser.parse_args(argv)
    identity = json.loads(args.identity.read_text(encoding="utf-8"))
    drift = []
    for path, text in plan(identity).items():
        current = path.read_bytes().decode("utf-8")
        if current == text:
            continue
        drift.append(path)
        if not args.check:
            path.write_bytes(text.encode("utf-8"))
    rel = [p.relative_to(REPO_ROOT).as_posix() for p in drift]
    if args.check and drift:
        print("[FAIL] version literals differ from identity.json; run "
              "python plugins-src/scripts/project_identity.py:\n  " + "\n  ".join(rel))
        return 1
    print(f"[OK] identity projection: {'wrote ' + str(len(rel)) if rel else 'no drift'}"
          f" ({len(plan(identity))} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
