from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "025-runtime-modularization"
SOURCE_SHA256 = "4eb6d40043ae553d603bea4c310e22b3b222e8abe669903bbb0d04f739d900ff"
EXPECTED_SHA256 = "7745ca81cc4dc93e412cff2e236111f1cf2d32f9899260527cfba8c74215d62f"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_reference_025",
        DEMO / "build_reference.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> dict:
    value = json.loads((DEMO / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(name: str) -> str:
    return hashlib.sha256((DEMO / name).read_bytes()).hexdigest()


def _members(name: str) -> dict[str, bytes]:
    with zipfile.ZipFile(DEMO / name) as package:
        return {
            item.filename: package.read(item.filename)
            for item in package.infolist()
            if not item.is_dir()
        }


def _surface(name: str) -> str:
    return "\n".join(
        value.decode("utf-8", errors="replace")
        for value in _members(name).values()
    )


def test_demo_025_frozen_bytes_and_member_diff_are_exact() -> None:
    assert _sha256("source.hwpx") == SOURCE_SHA256
    assert _sha256("expected.hwpx") == EXPECTED_SHA256
    assert (DEMO / "source.hwpx").stat().st_size == 9496
    assert (DEMO / "expected.hwpx").stat().st_size == 9486

    source = _members("source.hwpx")
    expected = _members("expected.hwpx")
    assert set(source) == set(expected)
    assert sorted(name for name in source if source[name] != expected[name]) == [
        "Contents/section0.xml"
    ]
    assert source["Contents/section1.xml"] == expected["Contents/section1.xml"]


def test_demo_025_request_matches_three_atomic_targets() -> None:
    spec = _load("source-spec.json")
    request = _load("expected-request.json")

    assert spec["document"] == {"pageIntent": 2, "sectionCount": 2}
    assert request["filename"] == "source.hwpx"
    assert request["output"] == "expected.hwpx"
    assert request["expected_revision"] == f"sha256:{SOURCE_SHA256}"
    assert request["idempotency_key"] == "s080-demo-025-runtime-modularization-v1"
    assert request["dry_run"] is False
    assert request["overwrite"] is False
    assert request["quality"] == "transparent"
    assert request["verification_requirements"] == [
        "package",
        "reopen",
        "openSafety",
        "semanticDiff",
        "bytePreservation",
    ]
    assert request["commands"] == [
        {
            "commandId": "body",
            "op": "set",
            "path": '/section[1]/paragraph[@id="0"]',
            "properties": {
                "text": "2026학년도 디지털 교육 운영 계획(확정)"
            },
        },
        {
            "commandId": "cell",
            "op": "set",
            "path": (
                '/section[1]/paragraph[@id="641758544"]'
                '/table[@id="1279708826"]/row[1]/cell[2]'
            ),
            "properties": {"text": "디지털교육지원팀"},
        },
        {
            "commandId": "header",
            "op": "set",
            "path": '/section[1]/header[@page-type="BOTH"]',
            "properties": {"text": "S-080 확정 머리글"},
        },
    ]
    assert [target["path"] for target in spec["targets"]] == [
        command["path"] for command in request["commands"]
    ]


def test_demo_025_expected_content_and_section_two_story_are_preserved() -> None:
    source_surface = _surface("source.hwpx")
    expected_surface = _surface("expected.hwpx")
    for before, after in (
        (
            "2026학년도 디지털 교육 운영 계획(초안)",
            "2026학년도 디지털 교육 운영 계획(확정)",
        ),
        ("교육연구부", "디지털교육지원팀"),
        ("S-080 검토용 머리글", "S-080 확정 머리글"),
    ):
        assert before in source_surface
        assert before not in expected_surface
        assert after not in source_surface
        assert after in expected_surface
    for preserved in ("붙임 1. 2절 보존 점검표", "S-080 붙임 보존 머리글"):
        assert preserved in source_surface
        assert preserved in expected_surface

    section_one = ElementTree.fromstring(
        _members("expected.hwpx")["Contents/section0.xml"]
    )
    section_two = ElementTree.fromstring(
        _members("expected.hwpx")["Contents/section1.xml"]
    )
    first_headers = section_one.findall(f".//{{{HP}}}header")
    second_headers = section_two.findall(f".//{{{HP}}}header")
    assert {(item.get("id"), item.get("applyPageType")) for item in first_headers} == {
        ("1094637672", "BOTH")
    }
    assert {(item.get("id"), item.get("applyPageType")) for item in second_headers} == {
        ("1464399287", "BOTH")
    }


def test_demo_025_receipts_are_honest_release_final_evidence() -> None:
    receipt = _load("receipt.json")
    visual = _load("visual-review.json")

    assert receipt["releaseState"] == "released"
    assert receipt["targetStack"] == {
        "pythonHwpx": "3.2.0",
        "mcpServer": "4.1.0",
        "plugin": "0.4.0",
    }
    assert receipt["contract"]["officialHash"] == "c127914cc3f4480e"
    assert receipt["preliminaryReplay"]["runtimeNature"] == (
        "pre-version-bump S-080 source-worktree metadata"
    )
    assert receipt["preliminaryReplay"]["publicPackagesUsed"] is False
    public_index_status = receipt["publicIndexReplay"]["status"]
    assert public_index_status in {"pending", "passed"}
    assert receipt["contract"]["status"] == (
        "observed-from-public-runtime"
        if public_index_status == "passed"
        else "observed-from-release-final-runtime"
    )
    assert receipt["status"] == (
        "public-index-replay-passed"
        if public_index_status == "passed"
        else "release-final-v3-passed"
    )
    assert receipt["releaseFinalV3"]["status"] == "passed"
    assert receipt["releaseFinalV3"]["outputSha256"] == f"sha256:{EXPECTED_SHA256}"
    assert all(receipt["releaseFinalV3"]["checks"].values())
    assert receipt["releaseFinalV3"]["storyPreservation"]["stories"] == [
        {
            "commandId": "header",
            "path": '/section[1]/header[@page-type="BOTH"]',
            "stableId": "header:1094637672",
            "pageType": "BOTH",
            "textMatched": True,
        }
    ]
    assert receipt["candidateReplay"]["status"] == "passed"
    assert receipt["candidateReplay"]["environment"] == {
        "installedPackageIsolation": {
            "pythonHwpxSitePackages": True,
            "mcpServerSitePackages": True,
        },
        "packageOrigin": "local-wheel",
        "publicIndexResolution": False,
        "publicMcpToolBoundary": True,
    }
    assert receipt["candidateSourceWorktreeCheck"]["status"] == "passed"
    assert receipt["candidateSourceWorktreeCheck"]["publicPackagesUsed"] is False
    assert receipt["candidateSourceWorktreeCheck"]["contractHash"] == (
        "c127914cc3f4480e"
    )
    assert all(receipt["candidateSourceWorktreeCheck"]["checks"].values())
    assert receipt["realHancom"]["status"] == "pass"
    assert receipt["realHancom"]["pagesObserved"] == "2/2"
    assert receipt["realHancom"]["sectionsObserved"] == "2/2"
    assert receipt["realHancom"]["releaseExactByteLineageVerified"] is True
    assert receipt["realHancom"]["screenshotsBundled"] is True
    assert receipt["publicationPerformed"] is False
    assert receipt["readyForPublicRelease"] is True

    assert visual["current"]["status"] == "observed_pass"
    assert visual["current"]["screenshotPath"] == "release-final-v3-page-1.jpeg"
    assert len(visual["current"]["screenshots"]) == 3
    assert visual["current"]["screenshotsBundled"] is True
    for screenshot in visual["current"]["screenshots"]:
        assert (DEMO / screenshot["path"]).stat().st_size == screenshot["bytes"]
        assert _sha256(screenshot["path"]) == screenshot["sha256"].removeprefix(
            "sha256:"
        )
    assert visual["lineage"]["releaseExactByteLineageVerified"] is True
    assert visual["lineage"]["officialContractHash"] == "c127914cc3f4480e"
    assert visual["summary"]["readyForPublicRelease"] is True
    assert visual["summary"]["publicIndexReplayStatus"] == public_index_status


def test_demo_025_builder_static_check_and_public_protocol_route() -> None:
    module = _module()
    assert module.verify_static_fixtures() == {
        "changedMembers": ["Contents/section0.xml"],
        "expectedSha256": EXPECTED_SHA256,
        "sourceSha256": SOURCE_SHA256,
    }
    source = (DEMO / "build_reference.py").read_text(encoding="utf-8")
    assert "create_connected_server_and_client_session" in source
    assert 'client.call_tool("apply_document_commands"' in source
    assert "apply_document_commands(" not in source
    assert "from hwpx_mcp_server.office.agent import HwpxAgentDocument" in source
    assert "from hwpx_mcp_server import server" in source
    assert "import hwpx_mcp_server" in source
    assert "hwpx_automation" not in source
    assert '"publicIndexReplay" if public_index' in source
    assert 'parser.add_argument(\n        "--check"' in source


def test_demo_025_builder_records_public_index_without_erasing_history(
    tmp_path: Path,
) -> None:
    module = _module()
    receipt_path = tmp_path / "receipt.json"
    visual_path = tmp_path / "visual-review.json"
    receipt_path.write_bytes((DEMO / "receipt.json").read_bytes())
    visual_path.write_bytes((DEMO / "visual-review.json").read_bytes())
    module.RECEIPT_PATH = receipt_path
    module.VISUAL_REVIEW_PATH = visual_path
    replay = {
        "status": "passed",
        "contractHash": "c127914cc3f4480e",
        "outputSha256": f"sha256:{EXPECTED_SHA256}",
        "environment": {
            "installedPackageIsolation": {
                "pythonHwpxSitePackages": True,
                "mcpServerSitePackages": True,
            },
            "packageOrigin": "public-index",
            "publicIndexResolution": True,
            "publicMcpToolBoundary": True,
        },
    }

    module._write_release_receipt(replay)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "public-index-replay-passed"
    assert receipt["publicIndexReplay"] == replay
    assert receipt["contract"]["status"] == "observed-from-public-runtime"
    assert receipt["realHancom"]["publicIndexExactByteLineageVerified"] is True
    assert receipt["candidateReplay"]["status"] == "passed"
    assert receipt["readyForPublicRelease"] is True
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    assert visual["lineage"]["publicIndexExactByteLineageVerified"] is True
    assert visual["summary"]["publicIndexReplayStatus"] == "passed"


def test_demo_025_public_text_has_no_private_workspace_lineage() -> None:
    for name in (
        "README.md",
        "source-spec.json",
        "expected-request.json",
        "receipt.json",
        "visual-review.json",
        "build_reference.py",
    ):
        text = (DEMO / name).read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert ".harness/" not in text
