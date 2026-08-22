from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

import hwpx_automation
from hwpx_automation import server
from hwpx_automation.tool_contract import (
    BASELINE_TOOL_SPECS,
    DOMAIN_SPECS,
    MIN_AUTOMATION_VERSION,
    MIN_MCP_VERSION,
    MIN_PYTHON_HWPX,
    MIN_SKILL_VERSION,
    ToolClassification,
    contract_hash,
    expected_tool_names,
    skill_required_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
REMOVED_PRACTICE_TOOLS = {
    "start_practice_scenario",
    "apply_practice_scenario",
    "start_practice_campaign",
    "get_practice_campaign",
    "continue_practice_campaign",
    "cancel_practice_campaign",
    "export_practice_campaign",
}
INTERNAL_FIXTURE_QA_TOOLS = {
    "run_fixture_benchmark",
    "export_fixture_benchmark",
    "visual_review_fixture",
    "visual_repair_fixture",
}
RETIRED_LEGACY_MODULES = {
    "hwpx_automation.tools": "tools.py",
    "hwpx_automation.legacy_server": "legacy_server.py",
    "hwpx_automation.prompts": "prompts.py",
    "hwpx_automation.logging_conf": "logging_conf.py",
    "hwpx_automation.schema.builder": "schema/builder.py",
    "hwpx_automation.schema.sanitizer": "schema/sanitizer.py",
}


def test_fastmcp_dependency_stays_on_the_audited_minor_line() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    optional_dependencies = project["project"]["optional-dependencies"]

    identity = json.loads(
        (ROOT / "src" / "hwpx_automation" / "identity.json").read_text(
            encoding="utf-8"
        )
    )
    assert project["project"]["version"] == (
        identity["releaseState"]["candidate"]["canonicalAutomation"]
    )
    # WP-F (core 6.0 namespace adaptation, design §9): the floor moved to the
    # 6.x line the automation code now targets. The dev-window pin
    # (>=6.0.0.dev0) served the pre-tag phase; the release narrows it to the
    # first published core of the line.
    assert "python-hwpx>=6.3.0,<7" in dependencies
    # The imaging stack is declared here since the 5.0 boundary closed: core
    # stopped reading PDFs and images, so its `visual` extra is empty and
    # deferring to it would have installed nothing.
    assert optional_dependencies["oracle"] == ["pymupdf>=1.24", "pillow>=10.0", "numpy>=1.26"]
    assert optional_dependencies["vision"] == ["pymupdf>=1.24", "pillow>=10.0", "numpy>=1.26"]
    # 필수가 아니라 extra. 이 패키지는 MCP 어댑터를 포함하지만 그것이 본체는
    # 아니다 — office/·workflow/·ops_services/·core/ 어느 파일도 mcp를
    # import하지 않는다.
    assert "mcp==1.28.1" not in dependencies
    assert "mcp==1.28.1" in optional_dependencies["mcp"]
    assert "pydantic>=2.11,<3" in dependencies


def _load_hygiene_module():
    path = ROOT / "scripts" / "check_public_hygiene.py"
    spec = importlib.util.spec_from_file_location("check_public_hygiene", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_practice_package_is_absent_from_the_import_surface() -> None:
    package_root = Path(hwpx_automation.__file__).resolve().parent

    assert not (package_root / "practice").exists()
    assert importlib.util.find_spec("hwpx_automation.practice") is None


def test_pre_fastmcp_shadow_modules_are_absent_from_the_import_surface() -> None:
    package_root = Path(hwpx_automation.__file__).resolve().parent

    for module_name, relative_path in RETIRED_LEGACY_MODULES.items():
        assert not (package_root / relative_path).exists()
        try:
            spec = importlib.util.find_spec(module_name)
        except ModuleNotFoundError:
            # Nested retired modules are absent when their retired parent
            # package is absent; Python 3.13 reports that state by raising.
            spec = None
        assert spec is None


def test_contract_and_live_registry_exclude_internal_product_boundaries() -> None:
    default = expected_tool_names(advanced=False)
    advanced = expected_tool_names(advanced=True)
    live = set(server._fastmcp_tool_names())

    assert len(default) == 128
    assert len(advanced) == 136
    assert len(skill_required_tool_names()) == 29
    assert (
        MIN_PYTHON_HWPX,
        MIN_AUTOMATION_VERSION,
        MIN_MCP_VERSION,
        MIN_SKILL_VERSION,
    ) == (
        "6.3.0",
        "7.0.1",
        "7.0.1",
        "2.0.0",
    )
    assert REMOVED_PRACTICE_TOOLS.isdisjoint(default)
    assert REMOVED_PRACTICE_TOOLS.isdisjoint(advanced)
    assert REMOVED_PRACTICE_TOOLS.isdisjoint(live)
    assert INTERNAL_FIXTURE_QA_TOOLS.isdisjoint(default)
    assert INTERNAL_FIXTURE_QA_TOOLS.isdisjoint(advanced)
    assert INTERNAL_FIXTURE_QA_TOOLS.isdisjoint(live)
    assert INTERNAL_FIXTURE_QA_TOOLS == {
        spec.name
        for spec in BASELINE_TOOL_SPECS
        if spec.classification is ToolClassification.INTERNAL
    }
    assert all(domain.key != "private_practice" for domain in DOMAIN_SPECS)

    health = server.mcp_server_health()
    assert health["toolSurface"]["status"] == "ok"
    assert health["toolSurface"]["expectedFastMcpToolCount"] == 128
    assert health["toolSurface"]["actualFastMcpToolCount"] == 128
    assert health["toolSurface"]["contractHash"] == contract_hash()
    assert health["toolSurface"]["missingExpectedTools"] == []
    assert health["toolSurface"]["unexpectedRegisteredTools"] == []


def test_public_hygiene_rejects_practice_source_and_wheel_members(
    tmp_path: Path, monkeypatch
) -> None:
    hygiene = _load_hygiene_module()

    assert hygiene._forbidden_path(
        "src/hwpx_automation/practice/runtime.py", "automation"
    )
    assert hygiene._forbidden_path("tests/test_practice_runtime.py", "automation")

    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "boundary-test.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("hwpx_automation/practice/runtime.py", b"pass\n")
        archive.writestr(
            "hwpx_automation/server.py",
            b"PRACTICE_ROOT = 'HWPX_PRACTICE_ROOT'\n",
        )

    monkeypatch.setattr(hygiene, "ROOT", tmp_path)
    failures = hygiene._wheel_failures()

    assert any("hwpx_automation/practice/runtime.py" in item for item in failures)
    assert any("HWPX_PRACTICE_ROOT" in item for item in failures)


def test_source_tree_has_no_internal_practice_runtime_markers() -> None:
    hygiene = _load_hygiene_module()
    tracked_source = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if path.is_file()
    ]

    assert hygiene._automation_runtime_failures(tracked_source) == []
