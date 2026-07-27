#!/usr/bin/env python3
"""Fail when public repository hygiene regresses."""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
PINNED_ROOT = ROOT

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
_INTERNAL_IDENTIFIER_COUNT = 13
_INTERNAL_IDENTIFIER_SHA256 = (
    "77148a88acca7a059919a6c2ca40a6eed354297a823ea63784b546e9808c0de5"
)
_WORKSTATION_PATH = re.compile(
    ("/" + "Users" + r"/[^/\s]+/").encode()
    + b"|"
    + ("/" + "home" + r"/[^/\s]+/").encode()
    + b"|[A-Za-z]:\\\\[Uu]sers\\\\"
)
_TEXT_ARTIFACT_SUFFIXES = (
    ".cfg",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)
_REJECTED_ARTIFACT_PREFIXES = (
    "tests/",
    "shared/hwpx/",
    "docs/superpowers/",
    "examples/out/",
    ".harness/",
    ".omx/",
)


class RepositoryFile(NamedTuple):
    """One exact file snapshot from the index or current worktree."""

    path: str
    source: str
    data: bytes


def _git_output(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_bytes,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _git_paths(*args: str, root: Path = ROOT) -> list[str]:
    output = _git_output(root, *args, "-z")
    return [os.fsdecode(item) for item in output.split(b"\0") if item]


def _cat_index_blobs(root: Path, object_ids: list[bytes]) -> dict[bytes, bytes]:
    """Read index objects in one binary-safe ``git cat-file --batch`` call."""

    unique_ids = list(dict.fromkeys(object_ids))
    if not unique_ids:
        return {}
    output = _git_output(
        root,
        "cat-file",
        "--batch",
        input_bytes=b"".join(object_id + b"\n" for object_id in unique_ids),
    )
    blobs: dict[bytes, bytes] = {}
    cursor = 0
    for expected_id in unique_ids:
        line_end = output.find(b"\n", cursor)
        if line_end < 0:
            raise RuntimeError("truncated git cat-file header")
        header = output[cursor:line_end].split()
        if len(header) != 3:
            raise RuntimeError(
                f"cannot read index object {expected_id.decode('ascii', 'replace')}"
            )
        actual_id, object_type, raw_size = header
        if actual_id != expected_id or object_type != b"blob":
            raise RuntimeError(
                "index entry does not resolve to the expected blob: "
                f"{expected_id.decode('ascii', 'replace')}"
            )
        size = int(raw_size)
        start = line_end + 1
        end = start + size
        if end >= len(output) or output[end : end + 1] != b"\n":
            raise RuntimeError(
                f"truncated git cat-file payload for {expected_id.decode('ascii')}"
            )
        blobs[expected_id] = output[start:end]
        cursor = end + 1
    return blobs


def _index_files(root: Path = ROOT) -> list[RepositoryFile]:
    """Read stage-zero index paths and their exact blobs, never worktree bytes."""

    raw_entries = _git_output(root, "ls-files", "--stage", "-z")
    parsed: list[tuple[str, bytes]] = []
    for raw_entry in raw_entries.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            _mode, object_id, stage = metadata.split()
        except ValueError as exc:
            raise RuntimeError("cannot parse git index entry") from exc
        path = os.fsdecode(raw_path)
        if stage != b"0":
            raise RuntimeError(f"unmerged git index entry: {path}")
        parsed.append((path, object_id))

    blobs = _cat_index_blobs(root, [object_id for _, object_id in parsed])
    return [
        RepositoryFile(path, "index", blobs[object_id]) for path, object_id in parsed
    ]


def _worktree_files(
    root: Path = ROOT,
    *,
    indexed: list[RepositoryFile] | None = None,
) -> list[RepositoryFile]:
    """Read tracked worktree and untracked files, preserving index differences."""

    indexed = indexed or []
    index_payloads = {(item.path, item.data) for item in indexed}
    files: list[RepositoryFile] = []
    for path in _git_paths(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        root=root,
    ):
        candidate = root / path
        if candidate.is_symlink():
            data = os.fsencode(os.readlink(candidate))
        elif candidate.is_file():
            data = candidate.read_bytes()
        else:
            continue
        if (path, data) in index_payloads:
            continue
        files.append(RepositoryFile(path, "worktree", data))
    return files


def _repository_files(root: Path = ROOT) -> list[RepositoryFile]:
    """Return exact commit candidates plus differing worktree/untracked snapshots."""

    indexed = _index_files(root)
    return indexed + _worktree_files(root, indexed=indexed)


def _project_kind(root: Path = ROOT) -> str:
    if (root / "packaging" / "hosts.json").is_file():
        return "plugin"
    metadata = (root / "pyproject.toml").read_text(encoding="utf-8")
    return "mcp" if 'name = "hwpx-mcp-server"' in metadata else "core"


def _forbidden_path(path: str, kind: str) -> bool:
    common_prefixes = (".harness/", ".omx/")
    if path.startswith(common_prefixes):
        return True
    if kind == "core":
        return path.startswith(
            ("shared/hwpx/", "docs/superpowers/", "tests/evidence/", "examples/out/")
        )
    if kind == "mcp":
        return path.startswith("docs/superpowers/") or bool(
            re.fullmatch(r"tests/(?:.*report.*|.*evidence.*)\.md", path)
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


def _text_bytes(data: bytes) -> bytes | None:
    if b"\0" in data[:8192]:
        return None
    return data


def _location(item: RepositoryFile) -> str:
    return f"{item.path} [{item.source}]"


def _is_public_runtime_surface(path: str) -> bool:
    return path in _PUBLIC_RUNTIME_EXACT_PATHS or path.startswith(
        _PUBLIC_RUNTIME_PREFIXES
    )


def _private_practice_surface_failures(
    files: list[RepositoryFile],
) -> list[str]:
    failures: list[str] = []
    folded_markers = {
        marker: marker.casefold() for marker in _REMOVED_PRIVATE_PRACTICE_MARKERS
    }
    for item in files:
        if not _is_public_runtime_surface(item.path):
            continue

        folded_path = item.path.casefold()
        path_hits = sorted(
            marker for marker, folded in folded_markers.items() if folded in folded_path
        )
        data = _text_bytes(item.data)
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
                f"{', '.join(hits)} in public runtime surface: {_location(item)}"
            )
    return failures


def _internal_identifier_failures(files: list[RepositoryFile]) -> list[str]:
    failures: list[str] = []
    public_root_files = {"README.md", "SKILL.md", "CHANGELOG.md", "CONTRIBUTING.md"}
    for item in files:
        if not (
            item.path in public_root_files
            or item.path.startswith("plugins/")
            or item.path.startswith("scripts/")
        ):
            continue
        data = _text_bytes(item.data)
        if data is None:
            continue
        matches = sorted(
            set(_INTERNAL_CODENAME_RE.findall(data))
            | set(_INTERNAL_WORKTREE_RE.findall(data))
        )
        if matches:
            rendered = ", ".join(value.decode("ascii", "replace") for value in matches)
            failures.append(
                f"internal Stage/worktree identifier: {_location(item)}: {rendered}"
            )
    return failures


def _internal_identifier_inventory_failures(
    files: list[RepositoryFile],
    root: Path = ROOT,
) -> list[str]:
    """Reject drift beyond the frozen historical identifier inventory."""

    if root != PINNED_ROOT:
        return []
    records = sorted(
        {
            f"{item.path}\0{match.decode('ascii')}"
            for item in files
            if (data := _text_bytes(item.data)) is not None
            for pattern in (_INTERNAL_CODENAME_RE, _INTERNAL_WORKTREE_RE)
            for match in pattern.findall(data)
        }
    )
    digest = hashlib.sha256(
        ("\n".join(records) + "\n").encode("utf-8")
    ).hexdigest()
    if (
        len(records) == _INTERNAL_IDENTIFIER_COUNT
        and digest == _INTERNAL_IDENTIFIER_SHA256
    ):
        return []
    return [
        (
            "internal identifier source inventory differs from frozen baseline: "
            f"count={len(records)} sha256={digest}"
        )
    ]


def _rejected_artifact_member(member: str) -> bool:
    return member.startswith(_REJECTED_ARTIFACT_PREFIXES) or any(
        f"/{part}" in f"/{member}" for part in _REJECTED_ARTIFACT_PREFIXES
    )


def _artifact_text_failures(
    item: RepositoryFile,
    member: str,
    data: bytes,
) -> list[str]:
    basename = Path(member).name
    if not (
        member.casefold().endswith(_TEXT_ARTIFACT_SUFFIXES)
        or basename in {"METADATA", "PKG-INFO"}
    ):
        return []
    display = f"{_location(item)}!{member}"
    failures: list[str] = []
    if _INTERNAL_CODENAME_RE.search(data) or _INTERNAL_WORKTREE_RE.search(data):
        failures.append(f"internal Stage/worktree identifier in artifact: {display}")
    if _WORKSTATION_PATH.search(data):
        failures.append(f"workstation-shaped path in artifact: {display}")
    return failures


def _wheel_failures(
    files: list[RepositoryFile],
    root: Path = ROOT,
) -> list[str]:
    """Inspect candidate wheel blobs plus ignored local dist artifacts."""

    failures: list[str] = []
    wheels = [
        item
        for item in files
        if item.path.startswith("dist/") and item.path.endswith(".whl")
    ]
    known = {(item.path, item.data) for item in wheels}
    for wheel in sorted((root / "dist").rglob("*.whl")):
        item = RepositoryFile(
            wheel.relative_to(root).as_posix(),
            "worktree",
            wheel.read_bytes(),
        )
        if (item.path, item.data) not in known:
            wheels.append(item)

    for item in wheels:
        try:
            archive_context = zipfile.ZipFile(io.BytesIO(item.data))
        except zipfile.BadZipFile:
            failures.append(f"invalid wheel archive: {_location(item)}")
            continue
        with archive_context as archive:
            names = archive.namelist()
            for name in names:
                data = archive.read(name)
                if _rejected_artifact_member(name):
                    failures.append(f"{_location(item)} contains {name}")
                failures.extend(_artifact_text_failures(item, name, data))
            for name in names:
                if not name.endswith(".dist-info/METADATA"):
                    continue
                requirements = [
                    line.casefold()
                    for line in archive.read(name)
                    .decode("utf-8", "replace")
                    .splitlines()
                    if line.startswith("Requires-Dist:")
                ]
                if any(
                    line.startswith("requires-dist: modelcontextprotocol")
                    for line in requirements
                ):
                    failures.append(f"{_location(item)} declares modelcontextprotocol")
    return failures


def _sdist_failures(
    files: list[RepositoryFile],
    root: Path = ROOT,
) -> list[str]:
    """Inspect candidate sdist blobs plus ignored local dist artifacts."""

    failures: list[str] = []
    sdists = [
        item
        for item in files
        if item.path.startswith("dist/") and item.path.endswith(".tar.gz")
    ]
    known = {(item.path, item.data) for item in sdists}
    for sdist in sorted((root / "dist").rglob("*.tar.gz")):
        item = RepositoryFile(
            sdist.relative_to(root).as_posix(),
            "worktree",
            sdist.read_bytes(),
        )
        if (item.path, item.data) not in known:
            sdists.append(item)

    for item in sdists:
        try:
            with tarfile.open(
                fileobj=io.BytesIO(item.data),
                mode="r:gz",
            ) as archive:
                for member in archive.getmembers():
                    if _rejected_artifact_member(member.name):
                        failures.append(
                            f"{_location(item)} contains {member.name}"
                        )
                    if not member.isfile():
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    failures.extend(
                        _artifact_text_failures(
                            item,
                            member.name,
                            extracted.read(),
                        )
                    )
        except tarfile.TarError:
            failures.append(f"invalid sdist archive: {_location(item)}")
            continue
    return failures


def _action_pin_failures(files: list[RepositoryFile]) -> list[str]:
    failures: list[str] = []
    action_ref = re.compile(
        r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)",
        re.MULTILINE,
    )
    for item in files:
        if not item.path.startswith(".github/workflows/") or not item.path.endswith(
            (".yml", ".yaml")
        ):
            continue
        text = item.data.decode("utf-8", "replace")
        for action, ref in action_ref.findall(text):
            if action.startswith(("./", "docker://")):
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                failures.append(
                    f"mutable GitHub Action ref: {_location(item)}: {action}@{ref}"
                )
    return failures


def _hwpx_member_failures(
    files: list[RepositoryFile],
    workstation_path: re.Pattern[bytes],
    private_markers: list[bytes],
) -> list[str]:
    failures: list[str] = []
    for item in files:
        if not item.path.casefold().endswith(".hwpx"):
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(item.data)) as archive:
                for member in archive.namelist():
                    data = archive.read(member)
                    if workstation_path.search(data):
                        failures.append(
                            f"workstation-shaped path: {_location(item)}!{member}"
                        )
                    if any(marker in data for marker in private_markers):
                        failures.append(
                            f"private-origin marker: {_location(item)}!{member}"
                        )
        except zipfile.BadZipFile:
            # Some corruption fixtures are intentionally invalid packages.
            continue
    return failures


def _collect_failures(root: Path = ROOT) -> tuple[str, int, list[str]]:
    kind = _project_kind(root)
    files = _repository_files(root)
    paths = sorted({item.path for item in files})
    failures = [
        f"forbidden tracked path: {path}"
        for path in paths
        if _forbidden_path(path, kind)
    ]

    tracked_ignored = _git_paths(
        "ls-files",
        "-ci",
        "--exclude-standard",
        root=root,
    )
    failures.extend(f"tracked file is ignored: {path}" for path in tracked_ignored)

    private_markers = [b">" + b"ko" + b"kyu" + b"<"]
    private_markers.extend(
        value.strip().encode("utf-8")
        for value in os.environ.get("HWPX_PRIVATE_PII_NEEDLES", "").split(",")
        if value.strip()
    )

    for item in files:
        data = _text_bytes(item.data)
        if data is None:
            continue
        if _WORKSTATION_PATH.search(data):
            failures.append(f"workstation-shaped path: {_location(item)}")
        if any(marker in data for marker in private_markers):
            failures.append(f"private-origin marker: {_location(item)}")

    failures.extend(_hwpx_member_failures(files, _WORKSTATION_PATH, private_markers))
    failures.extend(_action_pin_failures(files))
    failures.extend(_wheel_failures(files, root))
    failures.extend(_sdist_failures(files, root))
    failures.extend(_private_practice_surface_failures(files))
    failures.extend(_internal_identifier_failures(files))
    failures.extend(_internal_identifier_inventory_failures(files, root))
    return kind, len(paths), sorted(set(failures))


def main() -> int:
    try:
        kind, path_count, failures = _collect_failures()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[FAIL] public hygiene scan could not read repository snapshot: {exc}")
        return 2
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print(f"[OK] public hygiene: {kind}; {path_count} repository files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
