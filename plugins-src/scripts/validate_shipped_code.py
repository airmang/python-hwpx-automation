#!/usr/bin/env python3
"""Parse shipped code and resolve HWPX-stack imports in every host bundle."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
FENCE_OPEN = re.compile(
    r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)"
    r"(?:\r?\n)?$"
)
BLOCK_QUOTE_PREFIX = re.compile(r"^ {0,3}>[ \t]?")
LIST_ITEM_OPEN = re.compile(
    r"^(?P<indent> {0,3})(?:[*+-]|\d{1,9}[.)])"
    r"(?P<spacing>[ \t]+)(?P<rest>.*?)(?:\r?\n)?$"
)
SUPPORTED_FENCE_LANGUAGES = frozenset({"python", "py", "python3", "json"})
STACK_ROOTS = frozenset({"hwpx", "hwpx_automation", "hwpx_mcp_server"})


class PythonSource(NamedTuple):
    """One Python file or Markdown Python fence with an exact source location."""

    label: str
    code: str
    first_line: int = 1


class MarkdownFence(NamedTuple):
    """One CommonMark fenced code block relevant to validation."""

    language: str
    code: str
    first_line: int


class StackImport(NamedTuple):
    """One stack-owned import and whether its local binding is called directly."""

    label: str
    line: int
    module: str
    name: str
    used_as_call: bool


class StackAttributeUse(NamedTuple):
    """One attribute chain rooted at an imported stack-module alias."""

    label: str
    line: int
    module: str
    attributes: tuple[str, ...]
    used_as_call: bool


def _skill_roots(root: Path = ROOT) -> list[Path]:
    """Return the canonical skill root followed by all generated host skill roots."""

    config = json.loads((root / "packaging" / "hosts.json").read_text(encoding="utf-8"))
    roots = [root]
    for host in config["hosts"]:
        output = root / host["outputDir"]
        skill_root = (
            output if host["skillSubdir"] == "." else output / host["skillSubdir"]
        )
        roots.append(skill_root)
    return roots


def _markdown_paths(skill_root: Path) -> list[Path]:
    paths = [skill_root / "README.md", skill_root / "SKILL.md"]
    paths.extend(sorted((skill_root / "references").rglob("*.md")))
    paths.extend(sorted((skill_root / "examples").rglob("*.md")))
    return [path for path in paths if path.is_file()]


def _python_paths(skill_root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in ("examples", "scripts"):
        paths.extend(sorted((skill_root / directory).rglob("*.py")))
    return paths


def _relative_label(path: Path, root: Path = ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _fence_language(info: str) -> str | None:
    """Normalize common CommonMark info-string spellings for supported code."""

    normalized = info.strip().casefold()
    if not normalized:
        return None

    attribute_language = re.search(
        r"(?:^|[\s{])\.(python3?|py|json)(?=[\s}#.]|$)",
        normalized,
    )
    if attribute_language:
        return attribute_language.group(1)

    token = normalized.split(maxsplit=1)[0].strip("{}")
    token = token.removeprefix(".")
    if token.startswith("language-"):
        token = token.removeprefix("language-")
    if token in SUPPORTED_FENCE_LANGUAGES:
        return token

    # Do not silently ignore a fence that plainly claims to contain one of the
    # languages this gate owns but uses an unsupported annotation spelling.
    if re.search(
        r"(?:^|[\s{.])(?:python3?|py|json)(?=$|[\s}:#.;,+/-])",
        normalized,
    ):
        raise ValueError(f"unsupported Python/JSON fence info string: {info.strip()}")
    return None


def _strip_fence_indent(line: str, indent: int) -> str:
    """Apply CommonMark's up-to-opening-indent removal to a content line."""

    leading_spaces = len(line) - len(line.lstrip(" "))
    return line[min(indent, leading_spaces) :]


def _visual_columns(text: str) -> int:
    """Return CommonMark-style columns, expanding tabs to four-column stops."""

    column = 0
    for character in text:
        column = (
            column + (4 - column % 4)
            if character == "\t"
            else column + 1
        )
    return column


def _strip_indent_columns(line: str, required: int) -> str | None:
    """Remove required leading columns while preserving tab overshoot."""

    column = 0
    offset = 0
    while offset < len(line) and column < required:
        character = line[offset]
        if character == " ":
            column += 1
        elif character == "\t":
            column += 4 - column % 4
        else:
            return None
        offset += 1
    if column < required:
        return None
    return " " * (column - required) + line[offset:]


def _strip_all_block_quotes(line: str) -> tuple[str, int]:
    """Strip consecutive CommonMark block-quote markers from one line."""

    depth = 0
    while (match := BLOCK_QUOTE_PREFIX.match(line)) is not None:
        line = line[match.end() :]
        depth += 1
    return line, depth


def _strip_block_quote_depth(line: str, depth: int) -> str | None:
    """Strip exactly the opener's block-quote depth or report container end."""

    for _ in range(depth):
        match = BLOCK_QUOTE_PREFIX.match(line)
        if match is None:
            return None
        line = line[match.end() :]
    return line


def _container_content_line(
    line: str,
    *,
    quote_depth: int,
    list_indent: int | None,
) -> str | None:
    """Normalize one line inside the opener's quote/list container."""

    line = _strip_block_quote_depth(line, quote_depth)
    if line is None:
        return None
    if list_indent is None or not line.strip(" \t\r\n"):
        return line
    return _strip_indent_columns(line, list_indent)


def _markdown_fences(text: str) -> Iterator[MarkdownFence]:
    """Yield supported CommonMark fenced code blocks with exact source lines."""

    lines = text.splitlines(keepends=True)
    active_list_indents: dict[int, int] = {}
    line_index = 0
    while line_index < len(lines):
        logical_line, quote_depth = _strip_all_block_quotes(lines[line_index])
        list_indent = active_list_indents.get(quote_depth)
        if logical_line.strip(" \t\r\n"):
            list_item = LIST_ITEM_OPEN.match(logical_line)
            if list_item is not None:
                list_indent = _visual_columns(
                    logical_line[: list_item.start("rest")]
                )
                active_list_indents[quote_depth] = list_indent
                logical_line = list_item.group("rest")
            elif list_indent is not None:
                continuation = _strip_indent_columns(
                    logical_line,
                    list_indent,
                )
                if continuation is None:
                    active_list_indents.pop(quote_depth, None)
                    list_indent = None
                else:
                    logical_line = continuation

        opener = FENCE_OPEN.match(logical_line)
        if opener is None:
            line_index += 1
            continue

        fence = opener.group("fence")
        info = opener.group("info")
        if fence[0] == "`" and "`" in info:
            line_index += 1
            continue

        language = _fence_language(info)
        indent = len(opener.group("indent"))
        closing = re.compile(
            rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*(?:\r?\n)?$"
        )
        content_start = line_index + 1
        cursor = content_start
        content_lines: list[str] = []
        closed = False
        while cursor < len(lines):
            content_line = _container_content_line(
                lines[cursor],
                quote_depth=quote_depth,
                list_indent=list_indent,
            )
            if content_line is None:
                break
            if closing.match(content_line) is not None:
                closed = True
                break
            content_lines.append(content_line)
            cursor += 1

        if language is not None:
            code = "".join(
                _strip_fence_indent(line, indent)
                for line in content_lines
            )
            yield MarkdownFence(
                language=language,
                code=code,
                first_line=content_start + 1,
            )

        # A top-level unclosed fence consumes the rest of the document. A
        # quote/list fence ends when its container ends, and that outside line
        # must be processed normally.
        if closed:
            line_index = cursor + 1
        elif cursor < len(lines):
            line_index = cursor
        else:
            line_index = len(lines)


def _markdown_sources(
    path: Path,
    *,
    root: Path = ROOT,
) -> tuple[list[PythonSource], int]:
    """Return Python-fence sources and validate JSON fences in one Markdown file."""

    text = path.read_text(encoding="utf-8")
    label = _relative_label(path, root)
    python_sources: list[PythonSource] = []
    python_count = 0
    json_count = 0
    for fence in _markdown_fences(text):
        if fence.language in {"python", "python3", "py"}:
            python_count += 1
            python_sources.append(
                PythonSource(
                    label=f"{label}#python-fence-{python_count}",
                    code=fence.code,
                    first_line=fence.first_line,
                )
            )
        elif fence.language == "json":
            json_count += 1
            try:
                json.loads(fence.code)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{label}#json-fence-{json_count}: invalid JSON: {exc}"
                ) from exc
    return python_sources, json_count


def _attribute_chain(node: ast.Attribute) -> tuple[str, tuple[str, ...]] | None:
    """Return the root name and ordered attributes for a plain attribute chain."""

    attributes: list[str] = []
    cursor: ast.expr = node
    while isinstance(cursor, ast.Attribute):
        attributes.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    return cursor.id, tuple(reversed(attributes))


def _stack_references(
    source: PythonSource,
) -> tuple[list[StackImport], list[StackAttributeUse]]:
    """Extract stack imports and module-alias attribute uses from one source."""

    tree = ast.parse(source.code, filename=source.label)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imports: list[StackImport] = []
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            line = source.first_line + node.lineno - 1
            if not node.module or node.module.split(".")[0] not in STACK_ROOTS:
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                imports.append(
                    StackImport(
                        source.label,
                        line,
                        node.module,
                        alias.name,
                        local_name in called_names,
                    )
                )
        elif isinstance(node, ast.Import):
            line = source.first_line + node.lineno - 1
            for alias in node.names:
                if alias.name.split(".")[0] in STACK_ROOTS:
                    local_name = alias.asname or alias.name.split(".")[0]
                    bound_module = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
                    module_aliases[local_name] = bound_module
                    imports.append(
                        StackImport(
                            source.label,
                            line,
                            alias.name,
                            "",
                            local_name in called_names,
                        )
                    )

    attribute_uses: list[StackAttributeUse] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.value is node:
            continue
        chain = _attribute_chain(node)
        if chain is None:
            continue
        local_name, attributes = chain
        module = module_aliases.get(local_name)
        if module is None:
            continue
        attribute_uses.append(
            StackAttributeUse(
                source.label,
                source.first_line + node.lineno - 1,
                module,
                attributes,
                isinstance(parent, ast.Call) and parent.func is node,
            )
        )
    return imports, attribute_uses


def find_stack_import_failures(sources: list[PythonSource]) -> list[str]:
    """Resolve module, imported name, and relevant direct-call contracts."""

    failures: list[str] = []
    for source in sources:
        try:
            imports, attribute_uses = _stack_references(source)
        except SyntaxError as exc:
            line = source.first_line + (exc.lineno or 1) - 1
            failures.append(f"{source.label}:{line}: 문법 오류 — {exc.msg}")
            continue

        for item in imports:
            location = f"{item.label}:{item.line}"
            try:
                spec = importlib.util.find_spec(item.module)
            except (ImportError, KeyError, ModuleNotFoundError, ValueError) as exc:
                failures.append(
                    f"{location}: 모듈 해석 실패 — {item.module}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if spec is None:
                failures.append(f"{location}: 모듈 없음 — {item.module}")
                continue

            try:
                imported = importlib.import_module(item.module)
            except Exception as exc:  # noqa: BLE001 - fail closed on candidate
                failures.append(
                    f"{location}: 모듈 import 실패 — {item.module}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if not item.name or item.name == "*":
                if item.name == "*":
                    failures.append(
                        f"{location}: wildcard stack import 금지 — {item.module}"
                    )
                continue
            try:
                value = getattr(imported, item.name)
            except AttributeError:
                failures.append(f"{location}: {item.module}에 {item.name} 없음")
                continue
            except Exception as exc:  # noqa: BLE001 - fail closed on exports
                failures.append(
                    f"{location}: {item.module}.{item.name} 해석 실패 — "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if item.used_as_call and not callable(value):
                failures.append(f"{location}: {item.module}.{item.name}은 호출 불가")

        for item in attribute_uses:
            location = f"{item.label}:{item.line}"
            try:
                value = importlib.import_module(item.module)
            except Exception:  # noqa: BLE001, S112 - already reported above
                continue
            resolved: list[str] = []
            for attribute in item.attributes:
                resolved.append(attribute)
                qualified = f"{item.module}.{'.'.join(resolved)}"
                try:
                    value = getattr(value, attribute)
                except AttributeError:
                    failures.append(f"{location}: 속성 없음 — {qualified}")
                    break
                except Exception as exc:  # noqa: BLE001 - fail closed on exports
                    failures.append(
                        f"{location}: 속성 해석 실패 — {qualified}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    break
            else:
                if item.used_as_call and not callable(value):
                    qualified = f"{item.module}.{'.'.join(item.attributes)}"
                    failures.append(f"{location}: {qualified}은 호출 불가")
    return failures


def _all_sources(root: Path = ROOT) -> tuple[list[PythonSource], int, int]:
    """Collect Python assets/fences from canonical and four generated bundles."""

    sources: list[PythonSource] = []
    fence_count = 0
    json_fence_count = 0
    for skill_root in _skill_roots(root):
        for path in _python_paths(skill_root):
            sources.append(
                PythonSource(
                    label=_relative_label(path, root),
                    code=path.read_text(encoding="utf-8"),
                )
            )
        for path in _markdown_paths(skill_root):
            markdown_sources, json_count = _markdown_sources(path, root=root)
            sources.extend(markdown_sources)
            fence_count += len(markdown_sources)
            json_fence_count += json_count
    return sources, fence_count, json_fence_count


def validate(root: Path = ROOT) -> tuple[int, int, int]:
    sources, fence_count, json_fence_count = _all_sources(root)
    failures = find_stack_import_failures(sources)
    if failures:
        raise RuntimeError(
            f"shipped stack import validation failed ({len(failures)}):\n  "
            + "\n  ".join(failures)
        )
    if fence_count == 0:
        raise RuntimeError("no shipped Python Markdown fences were discovered")
    if json_fence_count == 0:
        raise RuntimeError("no shipped JSON Markdown fences were discovered")
    return len(sources) - fence_count, fence_count, json_fence_count


def main() -> int:
    try:
        python_files, fences, json_fences = validate()
    except (OSError, RuntimeError, SyntaxError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(
        f"[OK] parsed and resolved {python_files} shipped Python assets and "
        f"{fences} Python / {json_fences} JSON Markdown fences "
        f"across {len(_skill_roots())} skill roots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
