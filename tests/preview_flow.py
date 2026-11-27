"""A switch for the engine preview tests: draw every engine-placed table with its rows flowing.

Tests of the flow drawing (cell line pitch, column widths, row heights, flow page advance) use
it for documents whose tables the engine gives every coordinate, which would otherwise be drawn
at coordinates.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from hwpx_automation.preview import layout_preview


@pytest.fixture
def tables_flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(layout_preview, "_drawable_at_coordinates", lambda table, objects=None: False)
    yield
