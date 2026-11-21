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
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_ROOT = ROOT
INTERNAL_STAGE_CODE = re.compile(
    rb"(?<![A-Za-z0-9])(?:S-[0-9]{3}(?![0-9])|STG-[A-Za-z0-9]+)"
)
PLUGIN_SOURCE_PREFIX = "plugins-src/"
INTERNAL_STAGE_CODE_COUNT = 60
INTERNAL_STAGE_CODE_SHA256 = (
    "5fa4756713848bf51587afa0b345afc19e4ab24b33e771ebce3d8025487d3d08"
)
WORKSTATION_PATH = re.compile(
    ("/" + "Users" + r"/[^/\s]+/").encode()
    + b"|"
    + ("/" + "home" + r"/[^/\s]+/").encode()
    + b"|[A-Za-z]:\\\\[Uu]sers\\\\"
)
TEXT_ARTIFACT_SUFFIXES = (
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

_AUTOMATION_INTERNAL_RUNTIME_MARKERS = (
    b"hwpx_automation.practice",
    b"hwpx.practice",
    b"private_practice",
    b"HWPX_PRACTICE_ROOT",
    b"HWPX_PRACTICE_RUNNER_MANIFEST",
    b"HWPX_PRACTICE_ENCRYPTION_KEY",
    b"HWPX_CORPUS_SOURCE",
    b"CAMPAIGN_UNAVAILABLE",
    b"CAMPAIGN_QUEUE_UNAVAILABLE",
    b"start_practice_scenario",
    b"apply_practice_scenario",
    b"start_practice_campaign",
    b"get_practice_campaign",
    b"continue_practice_campaign",
    b"cancel_practice_campaign",
    b"export_practice_campaign",
)


def _git_paths(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args, "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        item
        for item in result.stdout.decode("utf-8", "surrogateescape").split("\0")
        if item
    ]


def _git_index_blobs() -> dict[str, bytes]:
    """Read stage-0 index objects, never their potentially different worktree."""

    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    entries: list[tuple[str, bytes]] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        index_header, raw_path = record.split(b"\t", 1)
        _mode, object_id, stage = index_header.split()
        if stage != b"0":
            path = raw_path.decode("utf-8", "surrogateescape")
            raise RuntimeError(f"unmerged git index entry: {path}")
        entries.append((raw_path.decode("utf-8", "surrogateescape"), object_id))
    if not entries:
        return {}

    batch = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=b"".join(object_id + b"\n" for _path, object_id in entries),
        check=True,
        capture_output=True,
    ).stdout
    cursor = 0
    blobs: dict[str, bytes] = {}
    for path, expected_id in entries:
        line_end = batch.find(b"\n", cursor)
        if line_end < 0:
            raise RuntimeError("git cat-file batch response ended before its header")
        batch_header = batch[cursor:line_end].split()
        cursor = line_end + 1
        if len(batch_header) != 3:
            raise RuntimeError(
                f"unexpected git cat-file header: {batch_header!r}"
            )
        object_id, object_type, raw_size = batch_header
        size = int(raw_size)
        data = batch[cursor : cursor + size]
        cursor += size
        if batch[cursor : cursor + 1] != b"\n":
            raise RuntimeError("git cat-file batch response lacks a separator")
        cursor += 1
        if object_id != expected_id:
            raise RuntimeError(f"git index object changed while reading {path}")
        if object_type != b"blob":
            raise RuntimeError(f"git index entry is not a blob: {path}")
        blobs[path] = data
    return blobs


def _differing_worktree_blobs(
    indexed_blobs: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Read differing tracked and untracked files without reviving HEAD blobs."""

    blobs: dict[str, bytes] = {}
    for rel in _git_paths(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
    ):
        path = ROOT / rel
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", "surrogateescape")
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        if indexed_blobs.get(rel) != data:
            blobs[rel] = data

    # Built release artifacts are commonly ignored, but remain part of the
    # local pre-publication hygiene surface.
    for pattern in ("*.whl", "*.tar.gz"):
        for path in sorted((ROOT / "dist").rglob(pattern)):
            rel = str(path.relative_to(ROOT))
            data = path.read_bytes()
            if indexed_blobs.get(rel) != data:
                blobs[rel] = data
    return blobs


def _project_kind(blobs: Mapping[str, bytes] | None = None) -> str:
    paths = set(blobs) if blobs is not None else None
    has_plugin_manifest = (
        "packaging/hosts.json" in paths
        if paths is not None
        else (ROOT / "packaging" / "hosts.json").is_file()
    )
    if has_plugin_manifest:
        return "plugin"
    if blobs is None:
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        has_automation_tree = (ROOT / "src" / "hwpx_automation").is_dir()
    else:
        metadata = blobs.get("pyproject.toml", b"").decode(
            "utf-8", "replace"
        )
        has_automation_tree = any(
            path.startswith("src/hwpx_automation/") for path in paths or ()
        )
    # 이름 하나로 판별하면 배포명이 바뀌는 순간 이 저장소가 core로 분류되고
    # automation 전용 금지 규칙이 통째로 건너뛰어진다. 실제로 6.0.0 재명명 뒤 게이트가
    # "[OK] public hygiene: core"를 내며 아무것도 검사하지 않았다.
    #
    # 이름 목록이 아니라 **구조**로 판별한다. 이 저장소만 응용 소유자 트리를
    # 갖는다.
    if has_automation_tree:
        return "automation"
    # The legacy distribution name still identifies this same application
    # repository while the 6.x compatibility line remains supported.
    if 'name = "hwpx-mcp-server"' in metadata:
        return "automation"
    return "core"


def _forbidden_path(path: str, kind: str) -> bool:
    common_prefixes = (".harness/", ".omx/",)
    if path.startswith(common_prefixes):
        return True
    if kind == "core":
        return path.startswith(("shared/hwpx/", "docs/superpowers/", "tests/evidence/", "examples/out/"))
    if kind == "automation":
        return (
            path.startswith("docs/superpowers/")
            or path.startswith("src/hwpx_automation/practice/")
            or path.startswith("tests/test_practice_")
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


def _blob_bytes(
    rel: str,
    blobs: Mapping[str, bytes] | None,
) -> bytes | None:
    if blobs is not None:
        return blobs.get(rel)
    path = ROOT / rel
    return path.read_bytes() if path.is_file() else None


def _text_blob(data: bytes | None) -> bytes | None:
    if data is None or b"\0" in data[:8192]:
        return None
    return data


def _artifact_text_failure(
    artifact: Path,
    member: str,
    data: bytes,
) -> list[str]:
    basename = Path(member).name
    if not (
        member.casefold().endswith(TEXT_ARTIFACT_SUFFIXES)
        or basename in {"METADATA", "PKG-INFO"}
    ):
        return []
    try:
        artifact_name: Path | str = artifact.relative_to(ROOT)
    except ValueError:
        artifact_name = artifact
    display = f"{artifact_name}!{member}"
    failures: list[str] = []
    if INTERNAL_STAGE_CODE.search(data):
        failures.append(f"internal Stage code in public artifact: {display}")
    if WORKSTATION_PATH.search(data):
        failures.append(f"workstation-shaped path in public artifact: {display}")
    return failures


def _artifact_candidates(
    pattern: str,
    blobs: Mapping[str, bytes] | None,
) -> list[tuple[Path, bytes | None]]:
    candidates: dict[str, bytes | None] = {}
    if blobs is not None:
        candidates = {
            rel: data
            for rel, data in blobs.items()
            if rel.startswith("dist/") and Path(rel).match(pattern)
        }
    else:
        for artifact in sorted((ROOT / "dist").rglob(pattern)):
            rel = str(artifact.relative_to(ROOT))
            candidates[rel] = None
    return [(ROOT / rel, data) for rel, data in sorted(candidates.items())]


def _wheel_failures(
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    rejected = (
        "tests/",
        "shared/hwpx/",
        "docs/superpowers/",
        "examples/out/",
        ".harness/",
        ".omx/",
        "hwpx_automation/practice/",
    )
    for wheel, indexed_data in _artifact_candidates("*.whl", blobs):
        source = (
            io.BytesIO(indexed_data)
            if indexed_data is not None
            else wheel
        )
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            for name in names:
                if name.startswith(rejected) or any(f"/{part}" in f"/{name}" for part in rejected):
                    failures.append(f"{wheel.relative_to(ROOT)} contains {name}")
                if name.endswith(".py"):
                    data = archive.read(name)
                    for marker in _AUTOMATION_INTERNAL_RUNTIME_MARKERS:
                        if marker in data:
                            failures.append(
                                f"{wheel.relative_to(ROOT)} contains internal runtime marker "
                                f"{marker.decode('ascii')!r} in {name}"
                            )
                failures.extend(
                    _artifact_text_failure(wheel, name, archive.read(name))
                )
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


def _sdist_failures(
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    for sdist, indexed_data in _artifact_candidates("*.tar.gz", blobs):
        archive = (
            tarfile.open(fileobj=io.BytesIO(indexed_data), mode="r:gz")
            if indexed_data is not None
            else tarfile.open(sdist, "r:gz")
        )
        with archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                failures.extend(
                    _artifact_text_failure(sdist, member.name, extracted.read())
                )
    return failures


def _shipped_source_stage_failures(
    tracked: list[str],
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    for rel in tracked:
        if rel != "pyproject.toml" and not rel.startswith("src/hwpx_automation/"):
            continue
        data = _text_blob(_blob_bytes(rel, blobs))
        if data is not None and INTERNAL_STAGE_CODE.search(data):
            failures.append(f"internal Stage code in shipped source: {rel}")
    return failures


def _internal_stage_inventory_failures(
    *snapshots: Mapping[str, bytes],
) -> list[str]:
    """Reject any identifier outside the frozen historical source inventory."""

    if ROOT != PINNED_ROOT:
        return []
    records = sorted(
        {
            f"{rel}\0{match.decode('ascii')}"
            for blobs in snapshots
            for rel, raw_data in blobs.items()
            # plugins-src/ is the moved hwpx-plugins source. It is never
            # shipped in the wheel/sdist and carries its own frozen inventory
            # in plugins-src/scripts/check_public_hygiene.py.
            if not rel.startswith(PLUGIN_SOURCE_PREFIX)
            if (data := _text_blob(raw_data)) is not None
            for match in INTERNAL_STAGE_CODE.findall(data)
        }
    )
    digest = hashlib.sha256(
        ("\n".join(records) + "\n").encode("utf-8")
    ).hexdigest()
    if (
        len(records) == INTERNAL_STAGE_CODE_COUNT
        and digest == INTERNAL_STAGE_CODE_SHA256
    ):
        return []
    return [
        (
            "internal Stage-code source inventory differs from frozen baseline: "
            f"count={len(records)} sha256={digest}"
        )
    ]


def _automation_runtime_failures(
    tracked: list[str],
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    for rel in tracked:
        if not rel.startswith("src/") or not rel.endswith(".py"):
            continue
        data = _blob_bytes(rel, blobs)
        if data is None:
            continue
        for marker in _AUTOMATION_INTERNAL_RUNTIME_MARKERS:
            if marker in data:
                failures.append(
                    f"internal runtime marker {marker.decode('ascii')!r}: {rel}"
                )
    return failures


def _action_pin_failures(
    tracked: list[str],
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    action_ref = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
    for rel in tracked:
        if not rel.startswith(".github/workflows/") or not rel.endswith((".yml", ".yaml")):
            continue
        data = _blob_bytes(rel, blobs)
        if data is None:
            continue
        text = data.decode("utf-8", "replace")
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
    blobs: Mapping[str, bytes] | None = None,
) -> list[str]:
    failures: list[str] = []
    for rel in tracked:
        if not rel.casefold().endswith(".hwpx"):
            continue
        data = _blob_bytes(rel, blobs)
        if data is None:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
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


def _snapshot_failures(
    source: str,
    blobs: Mapping[str, bytes],
    kind: str,
    private_markers: list[bytes],
) -> list[str]:
    tracked = sorted(blobs)
    failures = [
        f"forbidden tracked path: {path}"
        for path in tracked
        if _forbidden_path(path, kind)
    ]

    for rel in tracked:
        data = _text_blob(blobs.get(rel))
        if data is None:
            continue
        if WORKSTATION_PATH.search(data):
            failures.append(f"workstation-shaped path: {rel}")
        if any(marker in data for marker in private_markers):
            failures.append(f"private-origin marker: {rel}")

    failures.extend(
        _hwpx_member_failures(
            tracked,
            WORKSTATION_PATH,
            private_markers,
            blobs,
        )
    )
    failures.extend(_action_pin_failures(tracked, blobs))
    failures.extend(_shipped_source_stage_failures(tracked, blobs))
    if kind == "automation":
        failures.extend(_automation_runtime_failures(tracked, blobs))
    failures.extend(_wheel_failures(blobs))
    failures.extend(_sdist_failures(blobs))
    return [f"{failure} [{source}]" for failure in failures]


def main() -> int:
    try:
        indexed_blobs = _git_index_blobs()
        worktree_blobs = _differing_worktree_blobs(indexed_blobs)
        kind = _project_kind(indexed_blobs)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[FAIL] public hygiene could not read repository snapshots: {exc}")
        return 2

    private_markers = [b">" + b"ko" + b"kyu" + b"<"]
    private_markers.extend(
        value.strip().encode("utf-8")
        for value in os.environ.get("HWPX_PRIVATE_PII_NEEDLES", "").split(",")
        if value.strip()
    )

    failures = _snapshot_failures(
        "index",
        indexed_blobs,
        kind,
        private_markers,
    )
    failures.extend(
        _snapshot_failures(
            "worktree",
            worktree_blobs,
            kind,
            private_markers,
        )
    )
    failures.extend(
        _internal_stage_inventory_failures(indexed_blobs, worktree_blobs)
    )
    tracked_ignored = _git_paths("ls-files", "-ci", "--exclude-standard")
    failures.extend(
        f"tracked file is ignored: {path} [index]"
        for path in tracked_ignored
    )
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    repository_paths = set(indexed_blobs) | set(worktree_blobs)
    print(
        f"[OK] public hygiene: {kind}; "
        f"{len(repository_paths)} repository files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
