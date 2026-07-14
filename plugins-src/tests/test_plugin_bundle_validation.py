# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_plugin_bundles_validate() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_hwpx_plugin.py")],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_bundled_launchers_use_isolated_editable_dev_stack() -> None:
    launchers = sorted((ROOT / "plugins").glob("*/hwpx*/scripts/hwpx-mcp-server"))
    assert launchers

    for launcher in launchers:
        text = launcher.read_text(encoding="utf-8")
        assert "uv run --no-project" in text
        assert "uv run --project" not in text
        assert '--with-editable "${PYTHON_HWPX_REPO}[visual]"' in text
        assert '--with-editable "${MCP_REPO}"' in text


def test_quickcheck_verifies_editor_open_safety_for_generated_outputs() -> None:
    quickchecks = [ROOT / "scripts" / "quickcheck.py"]
    quickchecks.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/quickcheck.py")))
    assert quickchecks

    for quickcheck in quickchecks:
        text = quickcheck.read_text(encoding="utf-8")
        assert "validate_editor_open_safety" in text
        assert "create-open-safety" in text
        assert "proposal-open-safety" in text
        assert "document-plan-open-safety" in text
        assert "builder-open-safety" in text
        assert "operating-plan-open-safety" in text
        assert "template-formfit-open-safety" in text


def test_namespace_helpers_require_editor_open_safety_validator() -> None:
    helpers = [ROOT / "scripts" / "fix_namespaces.py"]
    helpers.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/fix_namespaces.py")))
    assert helpers

    for helper in helpers:
        text = helper.read_text(encoding="utf-8")
        assert "validate_editor_open_safety" in text
        assert "python-hwpx>=2.10.3 is required" in text
        assert "validate_package(" not in text
        assert "HwpxDocument.open" not in text
        assert "verify_open_safety" not in text


def test_zip_replace_helpers_do_not_expose_open_safety_bypass() -> None:
    helpers = [ROOT / "scripts" / "zip_replace_all.py"]
    helpers.extend(sorted((ROOT / "plugins").glob("*/hwpx*/scripts/zip_replace_all.py")))
    assert helpers

    for helper in helpers:
        text = helper.read_text(encoding="utf-8")
        assert "validate_open_safety" in text
        assert "verify_open_safety" not in text


def test_template_replace_examples_route_through_validated_helpers() -> None:
    examples = [ROOT / "examples" / "03_template_replace.py"]
    examples.extend(sorted((ROOT / "plugins").glob("*/hwpx*/**/examples/03_template_replace.py")))
    assert examples

    for example in examples:
        text = example.read_text(encoding="utf-8")
        assert "zip_replace_all(" in text
        assert "fix_namespaces(" in text
        assert "zipfile.ZipFile" not in text
        assert "os.replace" not in text
        assert "verify_open_safety" not in text


def test_api_reference_requires_current_open_safety_stack() -> None:
    references = [ROOT / "references" / "api.md"]
    references.extend(sorted((ROOT / "plugins").glob("*/hwpx*/references/api.md")))
    assert references

    for reference in references:
        text = reference.read_text(encoding="utf-8")
        assert "2.11.1+" in text
        assert "validate_editor_open_safety(path).ok == True" in text
        assert "2.9.1+ | ✅ 권장" not in text
        assert "2.6–2.9.0 | ✅ 기본 편집 호환" not in text


def test_task_eval_harness_assets_are_bundled() -> None:
    bundles = sorted((ROOT / "plugins").glob("*/hwpx*"))
    assert bundles

    for bundle in bundles:
        skill_root = bundle / "skills" / "hwpx"
        if not skill_root.exists():
            skill_root = bundle
        assert (skill_root / "scripts" / "task_eval_harness.py").exists()
        assert (skill_root / "examples" / "12_task_eval_replay.md").exists()
        assert (skill_root / "examples" / "eval_tasks" / "tasks.json").exists()
        assert (
            skill_root
            / "examples"
            / "eval_tasks"
            / "profiles"
            / "current-0.1.9.json"
        ).exists()
        assert (
            skill_root
            / "examples"
            / "eval_tasks"
            / "profiles"
            / "current-0.1.6.json"
        ).exists()
