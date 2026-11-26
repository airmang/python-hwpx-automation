"""pageNumberCount counts a page number however the file writes it.

Hancom puts only an automatic number (``hp:autoNum numType="PAGE"``) in a footer; python-hwpx up
to 7.x also adds a page-number control (``hp:pageNum``) beside it, and older files may hold only
the control. Each of these is one page number.
"""

from __future__ import annotations

from hwpx import HwpxDocument
from hwpx.oxml.namespaces import HP

from hwpx_automation.core.content import page_number_count


def _footer_with_page_number(format: str = "page"):
    document = HwpxDocument.new()
    footer = document.page.set_page_number(target="footer", format=format)
    return document, footer


def _footer_element(footer):
    return footer.element


def _drop(footer, local_name: str) -> None:
    root = _footer_element(footer)
    for ctrl in list(root.iter(f"{HP}ctrl")):
        for child in list(ctrl):
            if child.tag == f"{HP}{local_name}":
                ctrl.remove(child)


def _controls(footer, local_name: str) -> list:
    return list(_footer_element(footer).iter(f"{HP}{local_name}"))


def test_the_engines_footer_counts_one_page_number() -> None:
    _document, footer = _footer_with_page_number()

    assert len(_controls(footer, "pageNum")) == 1  # python-hwpx 7.x writes both forms
    assert page_number_count(footer) == 1


def test_hancoms_form_without_the_control_counts_one_page_number() -> None:
    _document, footer = _footer_with_page_number()
    _drop(footer, "pageNum")

    assert _controls(footer, "pageNum") == []
    assert page_number_count(footer) == 1


def test_a_control_alone_still_counts_one_page_number() -> None:
    _document, footer = _footer_with_page_number()
    _drop(footer, "autoNum")

    assert page_number_count(footer) == 1


def test_the_total_page_count_is_not_a_page_number() -> None:
    _document, footer = _footer_with_page_number(format="page/total")

    assert {node.get("numType") for node in _controls(footer, "autoNum")} == {"PAGE", "TOTAL_PAGE"}
    assert page_number_count(footer) == 1


def test_a_footer_without_a_page_number_counts_none() -> None:
    document = HwpxDocument.new()
    footer = document.page.set_footer(text="바닥글")

    assert page_number_count(footer) == 0
