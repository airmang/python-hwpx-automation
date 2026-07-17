#!/usr/bin/env python3
"""Replay and verify the released S-080 runtime-modularization reference via MCP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterator, Mapping


HERE = Path(__file__).resolve().parent
SOURCE_SPEC_PATH = HERE / "source-spec.json"
SOURCE_PATH = HERE / "source.hwpx"
REQUEST_PATH = HERE / "expected-request.json"
EXPECTED_PATH = HERE / "expected.hwpx"
RECEIPT_PATH = HERE / "receipt.json"
VISUAL_REVIEW_PATH = HERE / "visual-review.json"

SOURCE_SHA256 = "4eb6d40043ae553d603bea4c310e22b3b222e8abe669903bbb0d04f739d900ff"
EXPECTED_SHA256 = "7745ca81cc4dc93e412cff2e236111f1cf2d32f9899260527cfba8c74215d62f"
TARGET_STACK = {
    "pythonHwpx": "3.2.0",
    "mcpServer": "4.1.0",
    "plugin": "0.4.0",
}
HEADER_PATH = '/section[1]/header[@page-type="BOTH"]'
PRESERVED_BODY = "붙임 1. 2절 보존 점검표"
PRESERVED_HEADER = "S-080 붙임 보존 머리글"
EXPECTED_CHANGED_MEMBERS = ["Contents/section0.xml"]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _member_map(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as package:
        return {
            item.filename: package.read(item.filename)
            for item in package.infolist()
            if not item.is_dir()
        }


def _changed_members(source: Path, output: Path) -> list[str]:
    source_members = _member_map(source)
    output_members = _member_map(output)
    if set(source_members) != set(output_members):
        raise AssertionError("source/output OPC member sets differ")
    return sorted(
        name
        for name in source_members
        if source_members[name] != output_members[name]
    )


def _package_surface(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path) as package:
        for name in sorted(package.namelist()):
            chunks.append(name)
            chunks.append(package.read(name).decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def verify_static_fixtures() -> dict[str, Any]:
    """Verify frozen bytes and their public request without importing HWPX."""

    spec = _load_object(SOURCE_SPEC_PATH)
    request = _load_object(REQUEST_PATH)
    receipt = _load_object(RECEIPT_PATH)
    if _sha256_path(SOURCE_PATH) != SOURCE_SHA256 or SOURCE_PATH.stat().st_size != 9496:
        raise AssertionError("source.hwpx differs from the frozen fixture")
    if _sha256_path(EXPECTED_PATH) != EXPECTED_SHA256 or EXPECTED_PATH.stat().st_size != 9486:
        raise AssertionError("expected.hwpx differs from the frozen fixture")
    if request.get("filename") != SOURCE_PATH.name or request.get("output") != EXPECTED_PATH.name:
        raise AssertionError("the public request must use fixture-relative filenames")
    if request.get("expected_revision") != f"sha256:{SOURCE_SHA256}":
        raise AssertionError("expected_revision does not match source bytes")
    if [item.get("path") for item in request.get("commands", [])] != [
        '/section[1]/paragraph[@id="0"]',
        '/section[1]/paragraph[@id="641758544"]/table[@id="1279708826"]/row[1]/cell[2]',
        HEADER_PATH,
    ]:
        raise AssertionError("the three frozen command paths changed")
    changed = _changed_members(SOURCE_PATH, EXPECTED_PATH)
    if changed != EXPECTED_CHANGED_MEMBERS:
        raise AssertionError(f"unexpected frozen member diff: {changed}")
    if spec.get("document") != {"pageIntent": 2, "sectionCount": 2}:
        raise AssertionError("the two-section source intent changed")
    if receipt.get("releaseState") != "released":
        raise AssertionError("receipt must describe the approved release")
    if receipt.get("readyForPublicRelease") is not True:
        raise AssertionError("release-final receipt must record public readiness")
    return {
        "changedMembers": changed,
        "expectedSha256": EXPECTED_SHA256,
        "sourceSha256": SOURCE_SHA256,
    }


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", ()):
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError("MCP tool result did not contain an object payload")


@contextmanager
def _release_workspace(workspace: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    keys = ("HWPX_MCP_WORKSPACE_ROOTS", "HWPX_SKILL_VERSION")
    previous_env = {key: os.environ.get(key) for key in keys}
    os.environ["HWPX_MCP_WORKSPACE_ROOTS"] = json.dumps([str(workspace)])
    os.environ["HWPX_SKILL_VERSION"] = TARGET_STACK["plugin"]
    os.chdir(workspace)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"{distribution} is not installed; run this builder in the exact release environment"
        ) from exc


async def _run_protocol(server: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(server.mcp) as client:
        initialized = await client.initialize()
        health = _tool_payload(await client.call_tool("mcp_server_health", {}))
        first = _tool_payload(
            await client.call_tool("apply_document_commands", dict(request))
        )
        first_bytes = Path(str(request["output"])).read_bytes()
        replay = _tool_payload(
            await client.call_tool("apply_document_commands", dict(request))
        )
        replay_bytes = Path(str(request["output"])).read_bytes()
    return {
        "initializedVersion": initialized.serverInfo.version,
        "health": health,
        "first": first,
        "firstBytes": first_bytes,
        "replay": replay,
        "replayBytes": replay_bytes,
    }


def _verify_reopen(output: Path) -> dict[str, bool]:
    from hwpx import HwpxDocument
    from hwpx.agent import HwpxAgentDocument

    with HwpxDocument.open(output) as document:
        first_header = document.sections[0].properties.get_header("BOTH")
        second_header = document.sections[1].properties.get_header("BOTH")
        section_checks = {
            "sectionCountTwo": len(document.sections) == 2,
            "firstHeaderApplied": first_header is not None
            and first_header.id == "1094637672"
            and first_header.text == "S-080 확정 머리글",
            "secondHeaderPreserved": second_header is not None
            and second_header.id == "1464399287"
            and second_header.text == PRESERVED_HEADER,
            "secondBodyPreserved": document.sections[1].paragraphs[0].text
            == PRESERVED_BODY,
        }
    with HwpxAgentDocument.open(output) as view:
        body = view.resolve_record('/section[1]/paragraph[@id="0"]').summary.get("text")
        cell = view.resolve_record(
            '/section[1]/paragraph[@id="641758544"]'
            '/table[@id="1279708826"]/row[1]/cell[2]'
        ).summary.get("text")
    section_checks.update(
        {
            "bodyApplied": body == "2026학년도 디지털 교육 운영 계획(확정)",
            "cellApplied": cell == "디지털교육지원팀",
        }
    )
    return section_checks


def replay_release(
    *,
    require_installed: bool = False,
    package_origin: str = "check-only-unspecified",
) -> dict[str, Any]:
    """Replay through installed FastMCP and return an exact release receipt."""

    static = verify_static_fixtures()
    runtime = {
        "pythonHwpx": _installed_version("python-hwpx"),
        "mcpServer": _installed_version("hwpx-mcp-server"),
        "plugin": TARGET_STACK["plugin"],
    }
    if runtime != TARGET_STACK:
        raise RuntimeError(f"release stack mismatch: expected {TARGET_STACK}, got {runtime}")
    if "hwpx_mcp_server.server" in sys.modules:
        raise RuntimeError(
            "hwpx_mcp_server.server was imported before the temporary workspace was fixed"
        )

    source_before = SOURCE_PATH.read_bytes()
    request = _load_object(REQUEST_PATH)
    with tempfile.TemporaryDirectory(prefix="hwpx-demo-025-") as temp_dir:
        workspace = Path(temp_dir)
        temp_source = workspace / SOURCE_PATH.name
        temp_output = workspace / EXPECTED_PATH.name
        shutil.copyfile(SOURCE_PATH, temp_source)
        with _release_workspace(workspace):
            import hwpx
            import hwpx_mcp_server
            from hwpx import validate_editor_open_safety
            from hwpx_mcp_server import server

            protocol = asyncio.run(_run_protocol(server, request))
            package_isolation = {
                "pythonHwpxSitePackages": "site-packages"
                in str(Path(hwpx.__file__).resolve()),
                "mcpServerSitePackages": "site-packages"
                in str(Path(hwpx_mcp_server.__file__).resolve()),
            }

        first = protocol["first"]
        replay = protocol["replay"]
        verification = first.get("verificationReport") or {}
        replay_verification = replay.get("verificationReport") or {}
        story = verification.get("storyPreservation") or {}
        changed = _changed_members(temp_source, temp_output)
        source_safety = validate_editor_open_safety(temp_source)
        output_safety = validate_editor_open_safety(temp_output)
        reopen = _verify_reopen(temp_output)
        expected_bytes = EXPECTED_PATH.read_bytes()
        checks = {
            "sourceUnchanged": temp_source.read_bytes() == source_before,
            "firstCommitted": first.get("ok") is True
            and first.get("rolledBack") is False,
            "idempotentReplay": replay.get("ok") is True
            and (replay_verification.get("idempotency") or {}).get("replayed")
            is True,
            "idempotentBytesExact": protocol["firstBytes"]
            == protocol["replayBytes"],
            "expectedBytesExact": protocol["replayBytes"] == expected_bytes,
            "changedMembersExact": changed == EXPECTED_CHANGED_MEMBERS,
            "openSafety": source_safety.ok
            and output_safety.ok
            and (verification.get("openSafety") or {}).get("ok") is True,
            "reopen": all(reopen.values()),
            "storyPreservation": story.get("ok") is True
            and story.get("storyCount") == 1
            and (story.get("stories") or [{}])[0].get("path") == HEADER_PATH
            and (story.get("stories") or [{}])[0].get("textMatched") is True,
        }
        if not all(checks.values()):
            failed = sorted(name for name, ok in checks.items() if not ok)
            raise AssertionError(f"release replay checks failed: {failed}")

        health = protocol["health"]
        tool_surface = health.get("toolSurface") or {}
        if tool_surface.get("status") != "ok":
            raise AssertionError("release MCP health does not report an exact tool surface")
        result = {
            "status": "passed",
            "runtime": runtime,
            "initializedServerVersion": protocol["initializedVersion"],
            "contractHash": tool_surface.get("contractHash"),
            "outputSha256": f"sha256:{_sha256_path(temp_output)}",
            "checks": checks,
            "changedMembers": changed,
            "reopen": reopen,
            "storyPreservation": story,
            "environment": {
                "installedPackageIsolation": package_isolation,
                "packageOrigin": package_origin,
                "publicIndexResolution": package_origin == "public-index",
                "publicMcpToolBoundary": True,
            },
        }
    if SOURCE_PATH.read_bytes() != source_before:
        raise AssertionError("checked-in source changed during replay")
    if result["outputSha256"] != f"sha256:{static['expectedSha256']}":
        raise AssertionError("release output hash differs from the frozen expectation")
    if require_installed and not all(package_isolation.values()):
        raise RuntimeError(
            "receipt updates require wheel-installed core and MCP packages; "
            "source/editable imports may only use --check"
        )
    return result


def _write_release_receipt(replay: Mapping[str, Any]) -> None:
    receipt = _load_object(RECEIPT_PATH)
    package_origin = (replay.get("environment") or {}).get("packageOrigin")
    public_index = package_origin == "public-index"
    receipt["status"] = (
        "public-index-replay-passed" if public_index else "release-replay-passed"
    )
    receipt["publicIndexReplay" if public_index else "releaseFinalV3"] = dict(replay)
    receipt["contract"]["officialHash"] = replay.get("contractHash")
    receipt["contract"]["status"] = (
        "observed-from-public-runtime"
        if public_index
        else "observed-from-release-final-runtime"
    )
    receipt["realHancom"]["scope"] = (
        "The replay output is exact-byte identical to the bundled warning-free "
        f"Hancom-reviewed release-final-v3 bytes; package origin was {package_origin}."
    )
    receipt["realHancom"]["releaseExactByteLineageVerified"] = True
    if public_index:
        receipt["realHancom"]["publicIndexExactByteLineageVerified"] = True
    receipt["readyForPublicRelease"] = True
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    temporary = RECEIPT_PATH.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, RECEIPT_PATH)
    if public_index:
        visual = _load_object(VISUAL_REVIEW_PATH)
        visual["lineage"]["publicIndexExactByteLineageVerified"] = True
        visual["summary"]["publicIndexReplayStatus"] = "passed"
        visual["summary"]["reason"] = (
            "Release-final bytes, visual evidence, and exact public-index replay pass."
        )
        visual_payload = json.dumps(visual, ensure_ascii=False, indent=2) + "\n"
        visual_temporary = VISUAL_REVIEW_PATH.with_suffix(".json.tmp")
        visual_temporary.write_text(visual_payload, encoding="utf-8")
        os.replace(visual_temporary, VISUAL_REVIEW_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify in a temporary workspace without writing checked-in artifacts",
    )
    parser.add_argument(
        "--package-origin",
        choices=("local-wheel", "public-index"),
        help="classify installed packages without recording paths or credentials",
    )
    args = parser.parse_args(argv)
    if not args.check and args.package_origin is None:
        parser.error("receipt updates require --package-origin")
    replay = replay_release(
        require_installed=not args.check,
        package_origin=args.package_origin or "check-only-unspecified",
    )
    if not args.check:
        _write_release_receipt(replay)
    print(json.dumps(replay, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
