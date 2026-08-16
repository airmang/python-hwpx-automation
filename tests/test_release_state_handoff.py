from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _release_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
    )
    return workflow["jobs"]["release"]["steps"]


def _prepublish_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
    )
    return workflow["jobs"]["prepublish"]["steps"]


def test_prepublish_full_suite_installs_the_owned_oracle_runtime() -> None:
    install = next(
        step
        for step in _prepublish_steps()
        if step.get("name") == "Install test dependencies"
    )
    assert 'python -m pip install -e ".[mcp,oracle,test,typecheck]"' in str(
        install["run"]
    )


def test_phase0_legacy_cap_precedes_every_core_5_resolution() -> None:
    steps = _prepublish_steps()
    names = [str(step.get("name", "")) for step in steps]
    phase0 = names.index("Observe Phase-0 legacy cap before resolving core 5")
    dependencies = names.index("Install test dependencies")
    matrix = names.index("Run public core compatibility install matrix")
    coords = names.index("Derive release coordinates from identity.json")
    # Coordinates must be derived before anything that resolves a version.
    assert coords < phase0 < dependencies < matrix

    # The floors are still asserted, but as identity-derived environment rather
    # than as literals the workflow decides for itself.
    phase0_run = str(steps[phase0]["run"])
    phase0_env = steps[phase0]["env"]
    assert '"packaging>=23"' in phase0_run
    assert '"python-hwpx==${LEGACY_CORE}"' in phase0_run
    assert '"${LEGACY_DIST}==${LEGACY_COMPAT}"' in phase0_run
    assert "legacy_core_version" in str(phase0_env["LEGACY_CORE"])
    assert "legacy_compatibility_version" in str(phase0_env["LEGACY_COMPAT"])
    assert 'floors["legacyCoreSpecifiers"]' in phase0_run
    assert "{str(specifier) for specifier in item.specifier}" in phase0_run
    assert "assert len(core) == expected_count" in phase0_run
    assert "for item in core" in phase0_run

    matrix_run = str(steps[matrix]["run"])
    assert '--legacy-version "${LEGACY_COMPAT}"' in matrix_run
    assert '--legacy-core-version "${LEGACY_CORE}"' in matrix_run

    # Phase-0 is a safety prerequisite, not a promotion. The tag gate used to
    # keep the last observed public stack frozen as literals in the workflow;
    # that dictionary produced the preserved failure tags v6.1.2, v6.4.1, and
    # v6.7.0 without ever catching a real defect, so the workflow now derives
    # the coordinates and witnesses them against services we do not control.
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/release_coordinates.py --verify" in workflow
    assert "check_current_public_remote.py --require-network" in workflow


def test_automation_release_hands_off_without_global_promotion() -> None:
    steps = _release_steps()
    names = [str(step.get("name", "")) for step in steps]
    compat_observed = names.index("Observe compatibility PyPI truth")
    receipt_written = names.index("Write release-approved plugin handoff receipt")
    github_created = names.index("Create GitHub Release")
    github_observed = names.index(
        "Observe automation GitHub Release and record plugin handoff"
    )
    assert compat_observed < receipt_written < github_created < github_observed

    receipt_run = str(steps[receipt_written]["run"])
    assert "python-hwpx-automation.plugin-handoff/v1" in receipt_run
    assert '"globalReleaseState": "release-approved"' in receipt_run
    assert '"currentPublic": current_public' in receipt_run
    assert '"promotionForbiddenUntilRemainingObserved": True' in receipt_run
    assert all(
        requirement in receipt_run
        for requirement in (
            "pluginGitHubRelease",
            "marketplaceEntry",
            "realMarketplaceInstall",
        )
    )

    handoff_run = str(steps[github_observed]["run"])
    # Derived, not restated. See the comment in the phase-0 test above.
    assert "release_coordinates.py --handoff-summary" in handoff_run
    assert "release_coordinates.py --candidate-triple" in handoff_run
    assert "plugin GitHub Release, marketplace entry, and a real marketplace" in (
        handoff_run
    )
    whole_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "from release-approved to released" not in whole_workflow
    assert "promotes currentPublic" not in whole_workflow


def test_tag_release_requires_a_dated_changelog_heading() -> None:
    # The gate moved out of the workflow into a script so it can be dry-run
    # without a tag; assert the workflow delegates and the script still
    # enforces the dated heading.
    steps = _release_steps()
    validation = next(
        step
        for step in steps
        if step.get("name") == "Validate tag/version consistency"
    )
    assert "scripts/check_tag_release_gate.py" in str(validation["run"])

    gate = (ROOT / "scripts" / "check_tag_release_gate.py").read_text(
        encoding="utf-8"
    )
    assert r"\d{{4}}-\d{{2}}-\d{{2}}" in gate
    assert "'## [x.y.z] - YYYY-MM-DD'" in gate
    assert "_changelog_version" in gate


def test_identity_requires_complete_three_stack_remote_truth() -> None:
    identity = json.loads(
        (ROOT / "src" / "hwpx_automation" / "identity.json").read_text(
            encoding="utf-8"
        )
    )
    release = identity["releaseState"]
    assert release["status"] in {
        "unreleased-candidate",
        "release-approved",
        "released",
    }
    # While a train is in flight the public stack must still differ from the
    # candidate; once promoted the two agree. Stating the expected plugin
    # version here was a fourth copy of a coordinate that only identity.json
    # should own. An automation-only patch train moves neither core nor
    # plugin, so the difference may live in any of the three coordinates.
    if release["status"] != "released":
        assert (
            release["currentPublic"]["plugin"] != release["candidate"]["plugin"]
            or release["currentPublic"]["pythonHwpx"]
            != release["candidate"]["pythonHwpx"]
            or release["currentPublic"]["primaryApplication"]
            != release["candidate"]["canonicalAutomation"]
        )
    else:
        assert release["currentPublic"]["plugin"] == release["candidate"]["plugin"]
        assert (
            release["currentPublic"]["primaryApplication"]
            == release["candidate"]["canonicalAutomation"]
        )
    gate = release["promotionGate"]
    assert all(
        requirement in gate
        for requirement in (
            "core",
            "canonical automation",
            "compatibility distribution",
            "plugin GitHub release",
            "marketplace entry",
            "real marketplace install",
            "leaves currentPublic unchanged",
            "attached receipt",
        )
    )
