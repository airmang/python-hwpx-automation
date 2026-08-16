#!/usr/bin/env python3
"""Fail closed on automation/compat identity and packaging drift."""

from __future__ import annotations

import ast
import json
import re
import sys

from packaging.version import Version
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = project["project"]
    scripts = metadata["scripts"]
    _require(
        metadata["name"] == "python-hwpx-automation",
        "canonical distribution name drifted",
        errors,
    )
    _require(
        "sources" not in project.get("tool", {}).get("uv", {}),
        "local uv source override may leak a sibling/dirty core checkout",
        errors,
    )
    _require(
        scripts.get("hwpx") == "hwpx_automation.office.agent.cli:main",
        "canonical task CLI drifted",
        errors,
    )
    _require(
        scripts.get("hwpx-automation-mcp") == "hwpx_automation.mcp_cli:main",
        "canonical MCP console does not use the guarded optional-MCP entry point",
        errors,
    )
    _require(
        "hwpx-mcp-server" not in scripts,
        "canonical distribution must not also own the compatibility console",
        errors,
    )

    identity = json.loads(
        (ROOT / "src" / "hwpx_automation" / "identity.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {
        (item["surface"], item["value"]): item["classification"]
        for item in identity["identifiers"]
    }
    expected_rows = {
        ("distribution", "python-hwpx-automation"): "canonical",
        ("import-namespace", "hwpx_automation"): "canonical",
        ("mcp-console", "hwpx-automation-mcp"): "canonical",
        ("fastmcp-server-info-name", "python-hwpx-automation"): "canonical",
        ("distribution", "hwpx-mcp-server"): "compatibility",
        ("import-namespace", "hwpx_mcp_server"): "compatibility",
        ("mcp-console", "hwpx-mcp-server"): "compatibility",
        ("capability-version-field", "versions.automation"): "canonical",
        (
            "capability-version-field",
            "versions.mcp",
        ): "compatibility-preserved",
        ("capability-floor-field", "minAutomationVersion"): "canonical",
        (
            "capability-floor-field",
            "minMcpVersion",
        ): "compatibility-preserved",
        ("contract-floor-constant", "MIN_AUTOMATION_VERSION"): "canonical",
        (
            "contract-floor-constant",
            "MIN_MCP_VERSION",
        ): "compatibility-preserved",
        (
            "protocol-error-schema",
            "hwpx.mcp-error/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.authoring-runtime-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.compliance-quality-utilities-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.document-operations-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.evalplan-runtime-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.exam-runtime-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.form-fill-runtime-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.form-fill-runtime-parity/v1",
        ): "compatibility-preserved",
        (
            "frozen-receipt-schema",
            "hwpx-mcp.visual-runtime-owner/v1",
        ): "compatibility-preserved",
        (
            "frozen-parity-receipt-field",
            "mcpRuntimeMembers",
        ): "compatibility-preserved",
        (
            "workflow-state-environment",
            "HWPX_AUTOMATION_WORKFLOW_STORE",
        ): "canonical",
        (
            "workflow-state-environment",
            "HWPX_WORKFLOW_STORE",
        ): "compatibility-preserved",
        (
            "workflow-state-path",
            "${XDG_STATE_HOME:-~/.local/state}/hwpx-mcp-server/workflows.sqlite3",
        ): "compatibility-preserved",
        ("render-queue-principal", "hwpx-mcp-server"): "compatibility-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_QUEUE_ROOT",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_QUEUE_URL",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_QUEUE_SECRET",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_TRANSPORT_AUTH",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_CA_FILE",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_CLIENT_CERT_FILE",
        ): "integration-preserved",
        (
            "render-integration-environment",
            "HWPX_RENDER_CLIENT_KEY_FILE",
        ): "integration-preserved",
        (
            "workflow-security-environment",
            "HWPX_WORKFLOW_ENCRYPTION_KEY",
        ): "capability-preserved",
        (
            "oracle-capability-environment",
            "HWPX_ORACLE_STRUCTURAL_ONLY",
        ): "capability-preserved",
        (
            "oracle-capability-environment",
            "HWPX_ORACLE_BUDGET_SECONDS",
        ): "capability-preserved",
        (
            "plugin-integration-environment",
            "HWPX_SKILL_VERSION",
        ): "integration-preserved",
        (
            "plugin-integration-environment",
            "HWPX_PLUGIN_ROOT",
        ): "integration-preserved",
    }
    for key, classification in expected_rows.items():
        _require(
            rows.get(key) == classification,
            f"identity row drifted: {key!r}",
            errors,
        )
    policy = identity["compatibilityPolicy"]
    _require(policy["removalNotBeforeMajor"] >= 7, "compat removal floor drifted", errors)
    _require(
        policy["minimumPublicNoticeDays"] >= 90,
        "compat public-notice floor drifted",
        errors,
    )
    _require(
        policy["requiresSeparateOwnerApproval"] is True,
        "compat removal lost owner approval gate",
        errors,
    )
    preserved_pattern = re.compile(r"\bHWPX_[A-Z][A-Z0-9_]+\b")
    observed_preserved: set[str] = set()
    for source in (ROOT / "src" / "hwpx_automation").rglob("*.py"):
        for name in preserved_pattern.findall(
            source.read_text(encoding="utf-8")
        ):
            if (
                name.startswith(("HWPX_RENDER_", "HWPX_ORACLE_"))
                or name
                in {
                    "HWPX_WORKFLOW_ENCRYPTION_KEY",
                    "HWPX_SKILL_VERSION",
                    "HWPX_PLUGIN_ROOT",
                }
            ):
                observed_preserved.add(name)
    manifest_preserved = {
        item["value"]: item["classification"]
        for item in identity["identifiers"]
        if item["classification"]
        in {"integration-preserved", "capability-preserved"}
    }
    expected_preserved_classification = {
        name: (
            "capability-preserved"
            if name.startswith("HWPX_ORACLE_")
            or name == "HWPX_WORKFLOW_ENCRYPTION_KEY"
            else "integration-preserved"
        )
        for name in observed_preserved
    }
    _require(
        manifest_preserved == expected_preserved_classification,
        "product-neutral integration/capability environment census drifted",
        errors,
    )

    ownership_patterns = (
        re.compile(r"\bMCP[- ]owned\b", re.IGNORECASE),
        re.compile(r"\bMCP owner(?:'s)?\b", re.IGNORECASE),
        re.compile(r"\bMCP application layer\b", re.IGNORECASE),
        re.compile(r"\bMCP layer\b", re.IGNORECASE),
        re.compile(r"\bMCP production imports\b", re.IGNORECASE),
        re.compile(r"\bMCP repository\b", re.IGNORECASE),
        re.compile(r"\blive MCP modules?\b", re.IGNORECASE),
        re.compile(r"\bMCP copy\b", re.IGNORECASE),
        re.compile(r"\bcanonical MCP semantic agent runtime\b", re.IGNORECASE),
        re.compile(r"\bcanonical MCP VisualComplete\b", re.IGNORECASE),
        re.compile(r"\bMCP's application-layer ownership\b", re.IGNORECASE),
        re.compile(r"_mcp_owner\b", re.IGNORECASE),
        re.compile(r"Stateless HWPX MCP 서버"),
    )
    nomenclature_failures: list[str] = []
    nomenclature_files = [
        *(ROOT / "src" / "hwpx_automation").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    ]
    for path in sorted(nomenclature_files):
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in ownership_patterns:
            if pattern.search(text):
                nomenclature_failures.append(
                    f"{path.relative_to(ROOT).as_posix()}: {pattern.pattern}"
                )
    architecture_receipts = sorted(
        (ROOT / "docs" / "architecture").glob("*-owner.json")
    )
    for path in architecture_receipts:
        text = path.read_text(encoding="utf-8")
        receipt = json.loads(text)
        if not str(receipt.get("schemaVersion", "")).startswith("hwpx-mcp."):
            nomenclature_failures.append(
                f"{path.relative_to(ROOT).as_posix()}: receipt schema drifted"
            )
        if (
            '"mcpRuntime"' in text
            or '"mcpCanonical"' in text
            or "MCP canonical owner" in text
        ):
            nomenclature_failures.append(
                f"{path.relative_to(ROOT).as_posix()}: MCP ownership residue"
            )
        removal_gate = receipt.get("compatibilityPolicy", {}).get("removalGate", "")
        if re.search(r"\bS-\d+\b", str(removal_gate)):
            nomenclature_failures.append(
                f"{path.relative_to(ROOT).as_posix()}: active removal gate uses an internal Stage codename"
            )
        if re.search(r"S-\d+", str(receipt.get("packageFilesNote", ""))):
            nomenclature_failures.append(
                f"{path.relative_to(ROOT).as_posix()}: active package note uses an internal Stage codename"
            )
    current_architecture_docs = (
        ROOT / "docs" / "architecture" / "agent-runtime-owner.md",
        ROOT / "docs" / "architecture" / "authoring-runtime-owner.json",
    )
    for path in current_architecture_docs:
        if re.search(r"\bS-\d+\b", path.read_text(encoding="utf-8")):
            nomenclature_failures.append(
                f"{path.relative_to(ROOT).as_posix()}: active ownership prose uses an internal Stage codename"
            )
    frozen_schema_pattern = re.compile(
        r'"schemaVersion"\s*:\s*"(hwpx-mcp\.[^"]+)"'
    )
    observed_frozen_schemas: set[str] = set()
    for base in (ROOT / "docs", ROOT / "tests"):
        for path in base.rglob("*.json"):
            observed_frozen_schemas.update(
                frozen_schema_pattern.findall(
                    path.read_text(encoding="utf-8")
                )
            )
    classified_frozen_schemas = {
        item["value"]
        for item in identity["identifiers"]
        if item["surface"] == "frozen-receipt-schema"
        and item["classification"] == "compatibility-preserved"
    }
    if observed_frozen_schemas != classified_frozen_schemas:
        nomenclature_failures.append(
            "frozen hwpx-mcp receipt schema census differs from identity taxonomy"
        )
    _require(
        not nomenclature_failures,
        "canonical ownership nomenclature drifted: "
        + ", ".join(nomenclature_failures),
        errors,
    )

    compat = tomllib.loads(
        (ROOT / "compat" / "hwpx-mcp-server" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )["project"]
    version = metadata["version"]
    _require(compat["version"] == version, "canonical/compat versions differ", errors)
    _require(
        compat["dependencies"] == [
            f"python-hwpx-automation[mcp]=={version}"
        ],
        "compat dependency is not the exact canonical [mcp] release",
        errors,
    )
    _require(
        compat["scripts"] == {
            "hwpx-mcp-server": "hwpx_automation.mcp_cli:main"
        },
        "compatibility distribution does not exclusively own its console",
        errors,
    )

    contract = json.loads(
        (ROOT / "docs" / "tool-contract.generated.json").read_text(
            encoding="utf-8"
        )
    )
    release_state = identity.get("releaseState", {})
    expected_promotion_gate = (
        "Three states are mandatory: unreleased-candidate while auditing; "
        "release-approved only after separate owner approval and while "
        "currentPublic still names the previously observed coherent stack; "
        "released only in a follow-up commit after remote truth is observed "
        "for core, canonical automation, the compatibility distribution, the "
        "plugin GitHub release, the marketplace entry, and a real marketplace "
        "install. The automation tag workflow publishes only release-approved, "
        "leaves currentPublic unchanged, and hands an attached receipt to "
        "plugin publication."
    )
    _require(
        release_state.get("promotionGate") == expected_promotion_gate,
        "whole-stack release promotion gate drifted",
        errors,
    )
    candidate = release_state.get("candidate", {})
    # The candidate names the exact train being shipped, not the contract
    # floor. The two coincided until core recovered as 5.0.1 over a preserved
    # v5.0.0 tag.
    #
    # This used to regex the exact core version out of a literal in
    # release.yml, which made the workflow the authority and required the
    # literal to be hand advanced every train. Leaving it behind produced the
    # preserved failure tags v6.6.0 and v6.6.3. The authority is now
    # identity.json, and the workflow is required to *derive* from it.
    release_workflow_text = (
        ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")
    _require(
        'python-hwpx[visual,preview]==${CANDIDATE_CORE}' in release_workflow_text
        and "release_coordinates.py --verify --github-output"
        in release_workflow_text
        and "steps.coords.outputs.candidate_core" in release_workflow_text,
        "release workflow does not derive the observed core version from identity",
        errors,
    )
    observed_core_version = candidate.get("pythonHwpx", "")
    _require(
        bool(observed_core_version)
        and Version(observed_core_version)
        >= Version(contract["minPythonHwpx"]),
        "observed core version does not satisfy the contract floor",
        errors,
    )
    expected_candidate = {
        "pythonHwpx": observed_core_version,
        "canonicalDistribution": metadata["name"],
        "canonicalAutomation": version,
        "compatibilityDistribution": compat["name"],
        "compatibility": compat["version"],
        "plugin": candidate.get("plugin"),
        "contractHash": contract["contractHash"],
    }
    _require(
        candidate == expected_candidate,
        "identity release candidate does not match package/contract truth",
        errors,
    )
    # The plugin version has no same-repository package truth (it lives in
    # hwpx-plugins); the contract only pins its floor. Equality with the floor
    # held while every train advanced the floor, but a plugin patch train
    # moves the version without moving the floor. Remote observation
    # (check_current_public_remote.py) verifies the actual public version.
    candidate_plugin = candidate.get("plugin", "")
    _require(
        bool(candidate_plugin)
        and Version(candidate_plugin) >= Version(contract["minSkillVersion"]),
        "identity candidate plugin does not satisfy the contract skill floor",
        errors,
    )
    status = release_state.get("status")
    _require(
        status in {"unreleased-candidate", "release-approved", "released"},
        "identity release status is outside the three-state lifecycle",
        errors,
    )
    current_public = release_state.get("currentPublic", {})
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    use_cases = (ROOT / "docs" / "use-cases.md").read_text(encoding="utf-8")
    release_runbook = (ROOT / "docs" / "release-runbook.md").read_text(
        encoding="utf-8"
    )
    compat_surface = (ROOT / "docs" / "compatibility-6x.md").read_text(
        encoding="utf-8"
    )
    _require(
        "docs/compatibility-6x.md" in readme,
        "README does not link the 6.x compatibility surface document",
        errors,
    )
    _require(
        all(name in compat_surface for name in observed_preserved),
        "compatibility surface doc omits a preserved integration/capability "
        "environment key",
        errors,
    )
    _require(
        all(
            name in compat_surface
            for name in (
                "versions.automation",
                "versions.mcp",
                "minAutomationVersion",
                "minMcpVersion",
                "MIN_AUTOMATION_VERSION",
                "MIN_MCP_VERSION",
                "hwpx.mcp-error/v1",
                "hwpx-mcp.*",
                "mcpRuntimeMembers",
            )
        ),
        "compatibility surface doc omits canonical or compatibility-preserved "
        "wire identifiers",
        errors,
    )
    _require(
        "last coherent public three-stack" in release_runbook
        and "does not\npromote the global state or `currentPublic`"
        in release_runbook
        and "a real marketplace install resolves the exact 5.0/6.0/1.0 stack"
        in release_runbook
        and "receipt deliberately says `release-approved`" in release_runbook
        and "plugin GitHub\n> Release·marketplace·실제 marketplace 설치"
        in readme,
        "release docs do not preserve the whole-stack promotion boundary",
        errors,
    )
    if status in {"unreleased-candidate", "release-approved"}:
        # This used to freeze the expected currentPublic as a hand-advanced
        # literal dictionary — the exact device whose stale copies produced the
        # preserved failure tags v6.1.2, v6.4.1, and v6.7.0 in the workflow,
        # and which would have fired here on the first train after this one.
        # The structural half of the guarantee (a complete five-field public
        # stack that still differs from the candidate) is checked here; whether
        # that stack is REALLY public is the external observation's job
        # (scripts/check_current_public_remote.py, run by both CI paths).
        _require(
            all(
                current_public.get(field)
                for field in (
                    "pythonHwpx",
                    "primaryDistribution",
                    "primaryApplication",
                    "plugin",
                    "contractHash",
                )
            ),
            "currentPublic does not name a complete five-field public stack",
            errors,
        )
        _require(
            current_public.get("contractHash") != candidate.get("contractHash")
            or current_public.get("pythonHwpx") != candidate.get("pythonHwpx")
            or current_public.get("primaryApplication")
            != candidate.get("canonicalAutomation"),
            "currentPublic was promoted to the candidate before the full "
            "three-stack remote truth was observed",
            errors,
        )
    if status == "unreleased-candidate":
        # Derived from identity, not restated: the previous literals here named
        # one specific train and would have failed the first commit of every
        # following train — the same hand-advanced-coordinate disease this
        # script exists to catch in others.
        candidate_automation = str(candidate.get("canonicalAutomation", ""))
        public_train = (
            f"python-hwpx {current_public.get('pythonHwpx')} → "
            f"python-hwpx-automation {current_public.get('primaryApplication')} → "
            f"hwpx-plugin {current_public.get('plugin')}"
        )
        _require(
            "<!-- release-state: unreleased-candidate -->" in readme
            and f"아직 공개되지 않은 {candidate_automation} 후보" in readme
            and public_train in readme,
            "README does not prominently distinguish candidate from public release",
            errors,
        )
        _require(
            f"아직 공개되지 않은 {candidate_automation} source candidate" in use_cases
            and f"`python-hwpx >= {candidate.get('pythonHwpx')}`" in use_cases
            and f"`{current_public.get('contractHash')}`" in use_cases
            and f"`{candidate.get('contractHash')}`" in use_cases,
            "use-cases guide does not separate candidate and current-public coordinates",
            errors,
        )
        _require(
            "현재 MCP 표면, document-plan" not in use_cases
            and "버전 바닥은 `python-hwpx >= 4.2.0`" not in use_cases,
            "use-cases guide retains stale-current 5.1 wording",
            errors,
        )
    elif status == "release-approved":
        release_facing_docs = (
            readme,
            use_cases,
            (ROOT / "docs" / "hardening_guide_ko.md").read_text(
                encoding="utf-8"
            ),
            (ROOT / "docs" / "skill-first-workflows.md").read_text(
                encoding="utf-8"
            ),
        )
        _require(
            "<!-- release-state: release-approved -->" in readme
            and all("release-approved" in text for text in release_facing_docs),
            "approved tag docs do not identify remote truth as still pending",
            errors,
        )
    elif status == "released":
        _require(
            current_public.get("pythonHwpx") == candidate.get("pythonHwpx")
            and current_public.get("primaryDistribution")
            == candidate.get("canonicalDistribution")
            and current_public.get("primaryApplication")
            == candidate.get("canonicalAutomation")
            and current_public.get("plugin") == candidate.get("plugin")
            and current_public.get("contractHash")
            == candidate.get("contractHash"),
            "released identity does not point currentPublic at the promoted candidate",
            errors,
        )
        _require(
            "<!-- release-state: released -->" in readme
            and "<!-- release-state: unreleased-candidate -->" not in readme,
            "released README marker was not promoted",
            errors,
        )
        release_facing_docs = "\n".join(
            (
                readme,
                use_cases,
                (
                    ROOT / "docs" / "hardening_guide_ko.md"
                ).read_text(encoding="utf-8"),
                (
                    ROOT / "docs" / "skill-first-workflows.md"
                ).read_text(encoding="utf-8"),
            )
        )
        _require(
            "아직 공개되지 않은" not in release_facing_docs
            and "unreleased 6.0" not in release_facing_docs,
            "released current-facing docs still call the train unpublished",
            errors,
        )

    public_delta = json.loads(
        (ROOT / "docs" / "tool-contract-delta-5.1.0.json").read_text(
            encoding="utf-8"
        )
    )
    _require(
        public_delta.get("releaseStatus") == "released"
        and public_delta.get("target", {}).get("contractHash")
        == "429cb6706323e762"
        and public_delta.get("coreDependency", {}).get("floorBumped") is True
        and "PENDING_CONTRACT_HASH"
        not in json.dumps(public_delta, ensure_ascii=False)
        and "Not yet released"
        not in json.dumps(public_delta, ensure_ascii=False),
        "released 5.1 contract delta still describes a pending candidate",
        errors,
    )

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    _require(
        'pip install ".[mcp,http]"' in dockerfile,
        "Docker runtime does not install MCP+HTTP extras",
        errors,
    )
    _require(
        'CMD ["hwpx-automation-mcp"' in dockerfile,
        "Docker command is not canonical",
        errors,
    )

    tests_workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    _require(
        'metadata("python-hwpx-automation")' in tests_workflow,
        "clean-wheel job queries the wrong distribution",
        errors,
    )
    _require(
        "EXPECT_MCP" in tests_workflow and 'extras: "[mcp,' in tests_workflow,
        "clean-wheel matrix does not distinguish base from MCP install",
        errors,
    )
    _require(
        "f6b79f010d40a190fa6a8391eb212835022b3851" not in tests_workflow,
        "tests workflow retains the pre-5.0 core pin",
        errors,
    )
    _require(
        "platform-oracle-smoke:" in tests_workflow
        and "os: [macos-latest, windows-latest]" in tests_workflow
        and 'python-version: "3.10"' in tests_workflow
        and "scripts/check_platform_optional_smoke.py" in tests_workflow
        and "--core-repo ../python-hwpx" in tests_workflow,
        "native macOS/Windows minimum-Python clean-wheel smoke drifted",
        errors,
    )

    release_workflow = (
        ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")
    canonical_publish = release_workflow.find("packages-dir: dist/canonical/")
    canonical_observe = release_workflow.find("Observe canonical PyPI truth")
    compat_prebuild = release_workflow.find(
        "Prebuild compatibility distribution before any publish"
    )
    compat_publish = release_workflow.find("packages-dir: dist/compat/")
    compat_observe = release_workflow.find("Observe compatibility PyPI truth")
    _require(
        -1 not in (
            compat_prebuild,
            canonical_publish,
            canonical_observe,
            compat_publish,
            compat_observe,
        )
        and compat_prebuild
        < canonical_publish
        < canonical_observe
        < compat_publish
        < compat_observe,
        "release is not canonical publish/observe -> compat publish/observe",
        errors,
    )
    _require(
        "packages-dir: dist/" not in release_workflow.replace(
            "packages-dir: dist/canonical/", ""
        ).replace("packages-dir: dist/compat/", ""),
        "release contains a broad one-shot dist publish",
        errors,
    )
    # The tag gate moved out of this workflow into scripts/check_tag_release_gate.py
    # so a dry run can execute it without pushing a tag. Assert that the
    # workflow delegates and that the script still enforces both rules.
    tag_gate = (ROOT / "scripts" / "check_tag_release_gate.py").read_text(
        encoding="utf-8"
    )
    _require(
        "scripts/check_tag_release_gate.py" in release_workflow,
        "tag release does not run the extracted release gate",
        errors,
    )
    _require(
        "PUBLISHABLE_STATUS" in tag_gate
        and "release-state: release-approved" in tag_gate,
        "tag release does not require the truthful intermediate approved state",
        errors,
    )
    _require(
        "'## [x.y.z] - YYYY-MM-DD'" in tag_gate
        and r"\d{{4}}-\d{{2}}-\d{{2}}" in tag_gate,
        "tag release does not reject an unreleased changelog heading",
        errors,
    )
    _require(
        "Write release-approved plugin handoff receipt" in release_workflow
        and "python-hwpx-automation.plugin-handoff/v1" in release_workflow
        and '"globalReleaseState": "release-approved"' in release_workflow
        and '"promotionForbiddenUntilRemainingObserved": True'
        in release_workflow
        and "Observe automation GitHub Release and record plugin handoff"
        in release_workflow
        and "The global state remains" in release_workflow
        # The handoff line used to be a verbatim version string repeated here,
        # in the workflow, and in tests/test_release_state_handoff.py. Three
        # copies of one coordinate is how v6.7.0 happened. Assert that the
        # workflow *derives* the line instead of stating it.
        and "release_coordinates.py --handoff-summary" in release_workflow
        and "release_coordinates.py --candidate-triple" in release_workflow
        and "plugin GitHub Release, marketplace entry, and a real marketplace"
        in release_workflow,
        "automation release does not leave a truthful plugin handoff receipt",
        errors,
    )
    _require(
        "scripts/release_coordinates.py --verify" in release_workflow
        and "check_current_public_remote.py --require-network" in release_workflow,
        "release path no longer derives and externally witnesses currentPublic",
        errors,
    )
    _require(
        "from release-approved to released" not in release_workflow
        and "promotes currentPublic" not in release_workflow,
        "automation tag workflow still instructs premature global promotion",
        errors,
    )
    _require(
        "Gate minimum-Python clean wheel and optional boundaries"
        in release_workflow
        and 'python-version: "3.10"' in release_workflow
        and "scripts/check_platform_optional_smoke.py" in release_workflow
        and '--core-wheel "${CORE_WHEEL}"' in release_workflow,
        "release does not gate the clean wheel on minimum Python",
        errors,
    )

    contract_tree = ast.parse(
        (ROOT / "src" / "hwpx_automation" / "tool_contract.py").read_text(
            encoding="utf-8"
        )
    )
    eager_fastmcp = [
        node
        for node in contract_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("fastmcp_adapter")
            or isinstance(node, ast.Import)
            and any(alias.name.startswith("mcp") for alias in node.names)
        )
    ]
    _require(
        not eager_fastmcp,
        "static ToolSpec module eagerly imports the optional MCP adapter",
        errors,
    )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("automation transition identity: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
