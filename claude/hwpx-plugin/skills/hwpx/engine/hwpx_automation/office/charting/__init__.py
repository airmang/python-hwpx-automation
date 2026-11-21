# SPDX-License-Identifier: Apache-2.0
"""Deterministic data → ECMA-376 chartML generator (MVP: bar, line, pie).

The grammar mirrors the render-verified probes in
specs/055-chart-authoring/evidence/p0 (workspace): a ``c:chartSpace``
skeleton, per-series ``c:ser`` with string/number caches, and the
type-specific plot element (``c:barChart`` / ``c:lineChart`` + axis pair /
``c:pieChart``). Anything outside the verified set is refused with a typed
error — no silent approximation. Real Hancom draws the output from the
chartML alone (no OLE fallback, no pre-rendered image).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from xml.sax.saxutils import escape

CHART_TYPES = ("bar", "line", "pie")

_CAT_AX_ID = "111111111"
_VAL_AX_ID = "222222222"

_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<c:chartSpace xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
    '<c:date1904 val="0"/><c:roundedCorners val="0"/><c:chart>'
)


class UnsupportedChartError(ValueError):
    """Raised for chart types or shapes outside the render-verified MVP set."""


@dataclass(frozen=True)
class ChartSeries:
    """One data series: a display name and one value per category."""

    name: str
    values: tuple[float, ...]


def _series(index: int, name: str, categories: Sequence[str],
            values: Sequence[float], extra: str = "") -> str:
    cats = "".join(
        f'<c:pt idx="{i}"><c:v>{escape(str(c))}</c:v></c:pt>'
        for i, c in enumerate(categories)
    )
    vals = "".join(
        f'<c:pt idx="{i}"><c:v>{v:g}</c:v></c:pt>' for i, v in enumerate(values)
    )
    column = chr(ord("B") + index)
    return (
        f'<c:ser><c:idx val="{index}"/><c:order val="{index}"/>'
        f"<c:tx><c:strRef><c:f>Sheet1!${column}$1</c:f>"
        f'<c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>{escape(name)}</c:v></c:pt>'
        f"</c:strCache></c:strRef></c:tx>{extra}"
        f"<c:cat><c:strRef><c:f>Sheet1!$A$2:$A${len(categories) + 1}</c:f>"
        f'<c:strCache><c:ptCount val="{len(categories)}"/>{cats}</c:strCache></c:strRef></c:cat>'
        f"<c:val><c:numRef><c:f>Sheet1!${column}$2:${column}${len(values) + 1}</c:f>"
        f"<c:numCache><c:formatCode>General</c:formatCode>"
        f'<c:ptCount val="{len(values)}"/>{vals}</c:numCache></c:numRef></c:val></c:ser>'
    )


def _axes() -> str:
    return (
        f'<c:catAx><c:axId val="{_CAT_AX_ID}"/>'
        '<c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        f'<c:axPos val="b"/><c:crossAx val="{_VAL_AX_ID}"/></c:catAx>'
        f'<c:valAx><c:axId val="{_VAL_AX_ID}"/>'
        '<c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/>'
        f'<c:axPos val="l"/><c:crossAx val="{_CAT_AX_ID}"/></c:valAx>'
    )


def build_chart_ml(
    chart_type: str,
    categories: Sequence[str],
    series: Sequence[ChartSeries],
    *,
    title: str | None = None,
) -> str:
    """Build chartML for one of the render-verified MVP chart types.

    Raises:
        UnsupportedChartError: unknown chart type, empty/mismatched data, or
            a shape outside the verified set (e.g. multi-series pie).
    """

    if chart_type not in CHART_TYPES:
        raise UnsupportedChartError(
            f"unsupported chart type {chart_type!r}; render-verified types: "
            + ", ".join(CHART_TYPES)
        )
    if not categories:
        raise UnsupportedChartError("categories must be non-empty")
    if not series:
        raise UnsupportedChartError("series must be non-empty")
    if chart_type == "pie" and len(series) != 1:
        raise UnsupportedChartError("a pie chart takes exactly one series")
    if len(series) > 25:
        raise UnsupportedChartError("at most 25 series are supported")
    for item in series:
        if not item.name.strip():
            raise UnsupportedChartError("every series needs a non-empty name")
        if len(item.values) != len(categories):
            raise UnsupportedChartError(
                f"series {item.name!r} has {len(item.values)} values for "
                f"{len(categories)} categories"
            )

    parts: list[str] = [_HEAD]
    if title is not None and title.strip():
        parts.append(
            "<c:title><c:tx><c:rich><a:bodyPr/><a:p><a:r><a:t>"
            + escape(title)
            + "</a:t></a:r></a:p></c:rich></c:tx><c:overlay val=\"0\"/></c:title>"
            '<c:autoTitleDeleted val="0"/>'
        )
    parts.append("<c:plotArea><c:layout/>")

    if chart_type == "bar":
        parts.append('<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>')
        for index, item in enumerate(series):
            parts.append(_series(index, item.name, categories, item.values))
        parts.append(
            f'<c:axId val="{_CAT_AX_ID}"/><c:axId val="{_VAL_AX_ID}"/></c:barChart>'
        )
        parts.append(_axes())
    elif chart_type == "line":
        parts.append('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>')
        for index, item in enumerate(series):
            parts.append(
                _series(
                    index, item.name, categories, item.values,
                    '<c:marker><c:symbol val="circle"/><c:size val="5"/></c:marker>',
                )
            )
        parts.append(
            '<c:marker val="1"/>'
            f'<c:axId val="{_CAT_AX_ID}"/><c:axId val="{_VAL_AX_ID}"/></c:lineChart>'
        )
        parts.append(_axes())
    else:  # pie
        parts.append('<c:pieChart><c:varyColors val="1"/>')
        parts.append(_series(0, series[0].name, categories, series[0].values))
        parts.append('<c:firstSliceAng val="0"/></c:pieChart>')

    parts.append("</c:plotArea>")
    parts.append('<c:plotVisOnly val="1"/></c:chart></c:chartSpace>')
    return "".join(parts)


__all__ = [
    "CHART_TYPES",
    "ChartSeries",
    "UnsupportedChartError",
    "build_chart_ml",
]
