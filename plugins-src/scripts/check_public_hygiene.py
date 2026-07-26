#!/usr/bin/env python3
"""Fail when public repository hygiene regresses."""

from __future__ import annotations

import os
import re
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Internal corpus-practice machinery is preserved outside the public repositories.
# Keep this denylist exact: public fixture/oracle and real-Hancom verification
# language remains supported product surface, and release-only contract-delta
# records may intentionally name removed tools outside these runtime paths.
_REMOVED_PRIVATE_PRACTICE_MARKERS = (
    "private_practice",
    "workflows-private-practice",
    "start_practice_scenario",
    "apply_practice_scenario",
    "start_practice_campaign",
    "get_practice_campaign",
    "continue_practice_campaign",
    "cancel_practice_campaign",
    "export_practice_campaign",
    "CAMPAIGN_UNAVAILABLE",
    "PRACTICE_SCENARIO_UNAVAILABLE",
    "HWPX_CORPUS_SOURCE",
    "HWPX_PRACTICE_ROOT",
    "HWPX_PRACTICE_RUNNER_MANIFEST",
    "HWPX_SKILL_ROOT",
    "private practice campaign",
)
_PUBLIC_RUNTIME_EXACT_PATHS = {
    "README.md",
    "SKILL.md",
    "packaging/hosts.json",
}
_PUBLIC_RUNTIME_PREFIXES = (
    ".agents/plugins/",
    ".claude-plugin/",
    "packaging/templates/",
    "plugins/",
    "references/",
)
_INTERNAL_CODENAME_RE = re.compile(
    rb"(?<![A-Za-z0-9])(?:S-[0-9]{3}|STG-[A-Za-z0-9_-]+)(?![A-Za-z0-9])"
)
_INTERNAL_WORKTREE_RE = re.compile(
    rb"(?:python-hwpx(?:-automation)?|hwpx-mcp-server|hwpx-skill)-s[0-9]{3}\b",
    re.IGNORECASE,
)


def _git_paths(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args, "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def _project_kind() -> str:
    if (ROOT / "packaging" / "hosts.json").is_file():
        return "plugin"
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return "mcp" if 'name = "hwpx-mcp-server"' in metadata else "core"


def _forbidden_path(path: str, kind: str) -> bool:
    common_prefixes = (".harness/", ".omx/",)
    if path.startswith(common_prefixes):
        return True
    if kind == "core":
        return path.startswith(("shared/hwpx/", "docs/superpowers/", "tests/evidence/", "examples/out/"))
    if kind == "mcp":
        return (
            path.startswith("docs/superpowers/")
            or bool(re.fullmatch(r"tests/(?:.*report.*|.*evidence.*)\.md", path))
        )
    generated_s070 = {
        "adjudication.json",
        "final-manifest.json",
        "private-routing.json",
        "result-manifest.json",
    }
    if path.startswith(("docs/", "tests/evidence/", "examples/out/")):
        return True
    if "/examples/s070_fixture_benchmark/" in path and path.startswith("plugins/"):
        return True
    prefix = "examples/s070_fixture_benchmark/"
    if path.startswith(prefix):
        tail = path.removeprefix(prefix)
        return tail.startswith(("blind/", "public/")) or tail in generated_s070
    return False


def _text_bytes(path: Path) -> bytes | None:
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    return data


def _is_public_runtime_surface(path: str) -> bool:
    return path in _PUBLIC_RUNTIME_EXACT_PATHS or path.startswith(
        _PUBLIC_RUNTIME_PREFIXES
    )


def _private_practice_surface_failures(tracked: list[str]) -> list[str]:
    failures: list[str] = []
    folded_markers = {
        marker: marker.casefold() for marker in _REMOVED_PRIVATE_PRACTICE_MARKERS
    }
    for rel in tracked:
        if not _is_public_runtime_surface(rel):
            continue

        folded_path = rel.casefold()
        path_hits = sorted(
            marker
            for marker, folded in folded_markers.items()
            if folded in folded_path
        )
        data = _text_bytes(ROOT / rel)
        text_hits: list[str] = []
        if data is not None:
            folded_text = data.decode("utf-8", "replace").casefold()
            text_hits = sorted(
                marker
                for marker, folded in folded_markers.items()
                if folded in folded_text
            )
        hits = sorted(set(path_hits + text_hits))
        if hits:
            failures.append(
                "removed internal-QA marker(s) "
                f"{', '.join(hits)} in public runtime surface: {rel}"
            )
    return failures


def _internal_identifier_failures(tracked: list[str]) -> list[str]:
    failures: list[str] = []
    public_root_files = {"README.md", "SKILL.md", "CHANGELOG.md", "CONTRIBUTING.md"}
    for rel in tracked:
        if not (
            rel in public_root_files
            or rel.startswith("plugins/")
            or rel.startswith("scripts/")
        ):
            continue
        data = _text_bytes(ROOT / rel)
        if data is None:
            continue
        matches = sorted(
            set(_INTERNAL_CODENAME_RE.findall(data))
            | set(_INTERNAL_WORKTREE_RE.findall(data))
        )
        if matches:
            rendered = ", ".join(value.decode("ascii", "replace") for value in matches)
            failures.append(f"internal Stage/worktree identifier: {rel}: {rendered}")
    return failures


def _wheel_failures() -> list[str]:
    failures: list[str] = []
    rejected = ("tests/", "shared/hwpx/", "docs/superpowers/", "examples/out/", ".harness/", ".omx/")
    for wheel in sorted((ROOT / "dist").glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for name in names:
                if name.startswith(rejected) or any(f"/{part}" in f"/{name}" for part in rejected):
                    failures.append(f"{wheel.relative_to(ROOT)} contains {name}")
            for name in names:
                if not name.endswith(".dist-info/METADATA"):
                    continue
                requirements = [
                    line.casefold()
                    for line in archive.read(name).decode("utf-8", "replace").splitlines()
                    if line.startswith("Requires-Dist:")
                ]
                if any(line.startswith("requires-dist: modelcontextprotocol") for line in requirements):
                    failures.append(f"{wheel.relative_to(ROOT)} declares modelcontextprotocol")
    return failures


def _action_pin_failures(tracked: list[str]) -> list[str]:
    failures: list[str] = []
    action_ref = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
    for rel in tracked:
        if not rel.startswith(".github/workflows/") or not rel.endswith((".yml", ".yaml")):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        for action, ref in action_ref.findall(text):
            if action.startswith(("./", "docker://")):
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                failures.append(f"mutable GitHub Action ref: {rel}: {action}@{ref}")
    return failures


def _hwpx_member_failures(
    tracked: list[str],
    workstation_path: re.Pattern[bytes],
    private_markers: list[bytes],
) -> list[str]:
    failures: list[str] = []
    for rel in tracked:
        if not rel.casefold().endswith(".hwpx"):
            continue
        try:
            with zipfile.ZipFile(ROOT / rel) as archive:
                for member in archive.namelist():
                    data = archive.read(member)
                    if workstation_path.search(data):
                        failures.append(f"workstation-shaped path: {rel}!{member}")
                    if any(marker in data for marker in private_markers):
                        failures.append(f"private-origin marker: {rel}!{member}")
        except zipfile.BadZipFile:
            # Some corruption fixtures are intentionally invalid packages.
            continue
    return failures


def main() -> int:
    kind = _project_kind()
    tracked = [
        path
        for path in _git_paths("ls-files", "--cached", "--others", "--exclude-standard")
        if (ROOT / path).is_file()
    ]
    failures = [
        f"forbidden tracked path: {path}"
        for path in tracked
        if _forbidden_path(path, kind)
    ]

    tracked_ignored = _git_paths("ls-files", "-ci", "--exclude-standard")
    failures.extend(f"tracked file is ignored: {path}" for path in tracked_ignored)

    workstation_path = re.compile(
        ("/" + "Users" + r"/[^/\s]+/").encode()
        + b"|"
        + ("/" + "home" + r"/[^/\s]+/").encode()
        + b"|[A-Za-z]:\\\\[Uu]sers\\\\"
    )
    private_markers = [b">" + b"ko" + b"kyu" + b"<"]
    private_markers.extend(
        value.strip().encode("utf-8")
        for value in os.environ.get("HWPX_PRIVATE_PII_NEEDLES", "").split(",")
        if value.strip()
    )

    for rel in tracked:
        data = _text_bytes(ROOT / rel)
        if data is None:
            continue
        if workstation_path.search(data):
            failures.append(f"workstation-shaped path: {rel}")
        if any(marker in data for marker in private_markers):
            failures.append(f"private-origin marker: {rel}")

    failures.extend(_hwpx_member_failures(tracked, workstation_path, private_markers))
    failures.extend(_action_pin_failures(tracked))
    failures.extend(_wheel_failures())
    failures.extend(_private_practice_surface_failures(tracked))
    failures.extend(_internal_identifier_failures(tracked))
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print(f"[OK] public hygiene: {kind}; {len(tracked)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
