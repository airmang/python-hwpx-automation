# SPDX-License-Identifier: Apache-2.0
"""Installed-stack resolution for canonical and generated bundle code assets."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _validator_module():
    script = ROOT / "scripts" / "validate_shipped_code.py"
    spec = importlib.util.spec_from_file_location("validate_shipped_code", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_canonical_and_host_bundle_import_resolves_installed_stack() -> None:
    """All five skill roots resolve modules, imported names, and direct calls."""

    validator = _validator_module()
    roots = validator._skill_roots()
    sources, fence_count, json_fence_count = validator._all_sources()

    assert len(roots) == 5
    assert roots[0] == ROOT
    assert all(path != ROOT for path in roots[1:])
    assert fence_count >= 5 * 19
    assert json_fence_count >= 5 * 23
    assert any(source.label.startswith("plugins/claude/") for source in sources)
    assert any(source.label.startswith("plugins/codex/") for source in sources)
    assert any(source.label.startswith("plugins/hermes/") for source in sources)
    assert any(source.label.startswith("plugins/openclaw/") for source in sources)
    assert validator.find_stack_import_failures(sources) == []


@pytest.mark.parametrize(
    ("code", "expected", "expected_line"),
    (
        (
            "import hwpx.module_that_does_not_exist\n",
            "모듈 없음 — hwpx.module_that_does_not_exist",
            17,
        ),
        (
            "from hwpx import NameThatDoesNotExist\n",
            "hwpx에 NameThatDoesNotExist 없음",
            17,
        ),
        (
            "from hwpx import DEFAULT_NAMESPACES\nDEFAULT_NAMESPACES()\n",
            "hwpx.DEFAULT_NAMESPACES은 호출 불가",
            17,
        ),
        (
            "import hwpx.opc.package as package\npackage.NameThatDoesNotExist()\n",
            "속성 없음 — hwpx.opc.package.NameThatDoesNotExist",
            18,
        ),
        (
            "import hwpx as h\nh.DEFAULT_NAMESPACES()\n",
            "hwpx.DEFAULT_NAMESPACES은 호출 불가",
            18,
        ),
        (
            "from hwpx import *\n",
            "wildcard stack import 금지 — hwpx",
            17,
        ),
    ),
    ids=(
        "missing-module",
        "missing-name",
        "non-callable-name",
        "missing-aliased-attribute",
        "non-callable-aliased-attribute",
        "wildcard-import",
    ),
)
def test_markdown_stack_import_mutations_fail_closed(
    code: str,
    expected: str,
    expected_line: int,
) -> None:
    validator = _validator_module()
    source = validator.PythonSource(
        "references/mutation.md#python-fence-1",
        code,
        17,
    )

    failures = validator.find_stack_import_failures([source])

    assert failures
    assert expected in failures[0]
    assert f"references/mutation.md#python-fence-1:{expected_line}" in failures[0]


def test_nested_find_spec_keyerror_after_failed_root_import_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _validator_module()

    def broken_find_spec(module: str):
        if module == "hwpx":
            return object()
        if module == "hwpx.opc.package":
            raise KeyError("hwpx")
        raise AssertionError(f"unexpected module lookup: {module}")

    def missing_root_import(module: str):
        if module == "hwpx":
            raise ModuleNotFoundError("optional dependency is missing")
        raise AssertionError(f"unexpected module import: {module}")

    monkeypatch.setattr(validator.importlib.util, "find_spec", broken_find_spec)
    monkeypatch.setattr(validator.importlib, "import_module", missing_root_import)
    source = validator.PythonSource(
        "references/missing-dependency.md#python-fence-1",
        "import hwpx\nimport hwpx.opc.package\n",
        31,
    )

    failures = validator.find_stack_import_failures([source])

    assert len(failures) == 2
    assert (
        "references/missing-dependency.md#python-fence-1:31: "
        "모듈 import 실패 — hwpx: ModuleNotFoundError"
    ) in failures[0]
    assert (
        "references/missing-dependency.md#python-fence-1:32: "
        "모듈 해석 실패 — hwpx.opc.package: KeyError: 'hwpx'"
    ) in failures[1]


@pytest.mark.parametrize(
    "markdown",
    (
        "   ```Python\n   import hwpx.module_that_does_not_exist\n   ```\n",
        "~~~python3\nimport hwpx.module_that_does_not_exist\n~~~\n",
        "```python linenums=\"1\"\nimport hwpx.module_that_does_not_exist\n```\n",
        "```{.python #example}\nimport hwpx.module_that_does_not_exist\n```\n",
        "```language-python\nimport hwpx.module_that_does_not_exist\n```\n",
        (
            "> ```python\n"
            "> import hwpx.module_that_does_not_exist\n"
            "> ```\n"
        ),
        (
            "10. list item\n\n"
            "    ```python\n"
            "    import hwpx.module_that_does_not_exist\n"
            "    ```\n"
        ),
        (
            "-\tlist item\n\n"
            "\t```python\n"
            "\timport hwpx.module_that_does_not_exist\n"
            "\t```\n"
        ),
        (
            "- > ```python\n"
            "  > import hwpx.module_that_does_not_exist\n"
            "  > ```\n"
        ),
        (
            "- - ```python\n"
            "    import hwpx.module_that_does_not_exist\n"
            "    ```\n"
        ),
        (
            "123456789.\n"
            "           ```python\n"
            "           import hwpx.module_that_does_not_exist\n"
            "           ```\n"
        ),
        (
            "> - > ```python\n"
            ">   > import hwpx.module_that_does_not_exist\n"
            ">   > ```\n"
        ),
    ),
    ids=(
        "three-space-indented-uppercase",
        "tilde-python3",
        "annotated-info-string",
        "attribute-info-string",
        "language-prefix",
        "block-quote-container",
        "ordered-list-container",
        "tab-indented-list-container",
        "same-line-list-block-quote",
        "same-line-nested-list",
        "empty-nine-digit-ordered-item",
        "block-quote-list-block-quote",
    ),
)
def test_commonmark_python_fence_forms_fail_closed_on_missing_import(
    tmp_path: Path,
    markdown: str,
) -> None:
    validator = _validator_module()
    path = tmp_path / "mutation.md"
    path.write_text(markdown, encoding="utf-8")

    sources, json_count = validator._markdown_sources(path, root=tmp_path)

    assert len(sources) == 1
    assert json_count == 0
    failures = validator.find_stack_import_failures(sources)
    assert failures
    assert "모듈 없음 — hwpx.module_that_does_not_exist" in failures[0]


def test_commonmark_container_depth_fails_closed(tmp_path: Path) -> None:
    validator = _validator_module()
    path = tmp_path / "mutation.md"
    path.write_text(
        "> " * (validator.MAX_CONTAINER_DEPTH + 1)
        + "```python\n"
        + "> " * (validator.MAX_CONTAINER_DEPTH + 1)
        + "import hwpx\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Markdown container depth exceeds"):
        validator._markdown_sources(path, root=tmp_path)


@pytest.mark.parametrize(
    "markdown",
    (
        "   ~~~JSON\n   {not-json}\n   ~~~\n",
        "```json title=\"invalid\"\n{not-json}\n```\n",
        "```{.json #payload}\n{not-json}\n```\n",
        "> ```JSON\n> {not-json}\n> ```\n",
    ),
    ids=(
        "indented-tilde-uppercase",
        "annotated-info-string",
        "attribute-info-string",
        "block-quote-container",
    ),
)
def test_commonmark_json_fence_forms_fail_closed_on_invalid_json(
    tmp_path: Path,
    markdown: str,
) -> None:
    validator = _validator_module()
    path = tmp_path / "mutation.md"
    path.write_text(markdown, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        validator._markdown_sources(path, root=tmp_path)


def test_unsupported_python_or_json_fence_annotation_fails_closed(
    tmp_path: Path,
) -> None:
    validator = _validator_module()
    path = tmp_path / "mutation.md"
    path.write_text(
        "```python:run\nimport hwpx.module_that_does_not_exist\n```\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported Python/JSON fence info string"):
        validator._markdown_sources(path, root=tmp_path)
