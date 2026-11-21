# SPDX-License-Identifier: Apache-2.0
"""Markdown and HTML in and out of HWPX documents.

python-hwpx 7.0 keeps the engine (reading and writing what the file says);
these conversions moved here from it:

==============================================  ===============================================
python-hwpx 6.x                                 here
==============================================  ===============================================
``hwpx.tools.markdown_import.from_markdown``    :func:`from_markdown`
``hwpx.tools.markdown_import.MarkdownStyle``    :class:`MarkdownStyle`
``doc.text.append_markdown(md, ...)``           :func:`append_markdown` ``(doc, md, ...)``
``doc.text.markdown(...)``                      :func:`to_markdown` ``(doc, ...)``
``doc.text.markdown(rich=True, ...)``           :func:`to_markdown` ``(doc, rich=True, ...)``
``doc.text.html(...)``                          :func:`to_html` ``(doc, ...)``
``hwpx.tools.markdown_export.equation_markdown`` :func:`equation_markdown`
==============================================  ===============================================

The functions take the same arguments and give the same results as before.
This package imports only python-hwpx (no pydantic, no MCP): it is the light
layer of python-hwpx-automation.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hwpx import HwpxDocument

    from ._export import ARABIC_HEAD, ROMAN_HEAD, SHAPE_TAGS, equation_markdown
    from ._import import MarkdownStyle, append_markdown, from_markdown
    from ._plain_export import HEADING_MAX_CHARS, escape_line_starts, escape_markdown

__all__ = [
    "ARABIC_HEAD",
    "HEADING_MAX_CHARS",
    "MarkdownStyle",
    "ROMAN_HEAD",
    "SHAPE_TAGS",
    "append_markdown",
    "equation_markdown",
    "escape_line_starts",
    "escape_markdown",
    "from_markdown",
    "to_html",
    "to_markdown",
]

#: Names served from the submodules on first use, so ``import hwpx_automation.markdown`` stays cheap.
_LAZY = {
    "MarkdownStyle": "._import",
    "append_markdown": "._import",
    "from_markdown": "._import",
    "equation_markdown": "._export",
    "ARABIC_HEAD": "._export",
    "ROMAN_HEAD": "._export",
    "SHAPE_TAGS": "._export",
    "HEADING_MAX_CHARS": "._plain_export",
    "escape_markdown": "._plain_export",
    "escape_line_starts": "._plain_export",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def _option_names(function: Any) -> set[str]:
    import inspect

    return {
        name
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }


def _check_markdown_options(rich: bool, options: dict[str, object]) -> None:
    """``to_markdown()`` 의 옵션이 고른 쪽(rich 여부)에 있는지 본다. 없으면 어느 쪽 옵션인지 알린다."""

    from hwpx.errors import HwpxTypeError

    from ._export import export_markdown as rich_markdown
    from ._plain_export import export_markdown as plain_markdown

    plain_names, rich_names = _option_names(plain_markdown), _option_names(rich_markdown)
    accepted = rich_names if rich else plain_names
    for name in options:
        if name in accepted:
            continue
        other = plain_names if rich else rich_names
        if name in other:
            where = "rich=False" if rich else "rich=True"
            message = f"to_markdown(rich={rich})은 {name!r} 옵션을 받지 않습니다. 이 옵션은 to_markdown({where})의 것입니다."
            suggestion = f"to_markdown(doc, {where}, {name}=...)로 부르세요."
        else:
            message = f"to_markdown()에 없는 옵션입니다: {name!r}"
            suggestion = "받는 옵션: " + ", ".join(sorted(accepted))
        raise HwpxTypeError(
            message,
            context={"argument": name, "rich": rich},
            suggestion=suggestion,
        )


def to_markdown(document: HwpxDocument, *, rich: bool = False, **options: Any) -> str:
    """*document* 의 본문을 Markdown 으로 내보낸다 (6.x ``doc.text.markdown(...)``).

    ``rich=False``(기본)는 글과 표, 문서가 정한 제목(개요 문단·``개요 N`` 스타일)을 싣는
    평이한 변환이다. 옵션: ``include_tables``, ``section_separator``, ``tab_token``,
    ``masking_policy``, ``list_labels``, ``notes``, ``headings``.

    ``rich=True`` 는 런 서식(굵게·기울임·밑줄·색), 병합 표(HTML), 각주·하이퍼링크·그림·
    도형 글을 싣는 확장 변환이다. 옵션: ``image_dir``, ``image_ref_prefix``,
    ``detect_headings``, ``heading_detector``, ``notes_section_separator``,
    ``headers_and_footers``, ``memos``, ``equations``, ``heading_source``, ``list_labels``,
    ``colors``.

    고른 쪽에 없는 옵션은 ``HwpxTypeError`` 다(어느 쪽 옵션인지 알려 준다).
    """

    _check_markdown_options(rich, options)
    if rich:
        from ._export import export_markdown as rich_markdown

        return rich_markdown(document, **options)
    from ._plain_export import export_markdown

    return export_markdown(document, **options)


def to_html(document: HwpxDocument, **options: Any) -> str:
    """*document* 의 본문을 HTML 로 내보낸다 (6.x ``doc.text.html(...)``).

    옵션: ``include_tables``, ``full_document``, ``title``, ``tab_token``,
    ``masking_policy``, ``list_labels``, ``notes``, ``headings``, ``nested_tables``.
    """

    from ._plain_export import export_html

    return export_html(document, **options)

