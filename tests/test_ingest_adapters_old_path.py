# SPDX-License-Identifier: Apache-2.0
"""``hwpx_automation.ingest_adapters`` (7.x) is the MarkItDown adapter module of the new ingest.

The adapter moved into :mod:`hwpx_automation.ingest`. The old path stays for one major and is
the same module object, so a patch through either path reaches the adapter.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest


def test_the_old_adapter_path_is_the_new_module() -> None:
    from hwpx_automation import ingest, ingest_adapters
    from hwpx_automation.ingest import adapters

    assert ingest_adapters is adapters
    assert ingest_adapters.MarkItDownAdapter is ingest.MarkItDownAdapter
    assert ingest_adapters.MissingMarkItDownDependency is ingest.MissingMarkItDownDependency
    assert issubclass(ingest_adapters.MissingMarkItDownDependency, ingest.DocumentIngestError)
    for name in ("DocumentIngestError", "DocumentIngestResult", "DocumentSourceInfo"):
        assert getattr(ingest_adapters, name) is getattr(ingest, name)


def test_a_patch_through_the_old_path_reaches_the_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hwpx_automation import ingest_adapters
    from hwpx_automation.ingest import DocumentIngestor, DocumentSourceInfo, MarkItDownAdapter

    source = tmp_path / "note.txt"

    class _Fake:
        def convert(self, path: str):
            assert path == str(source)
            return type("R", (), {"text_content": "# 바뀐 글"})()

    monkeypatch.setattr(ingest_adapters, "_load_markitdown_class", lambda: _Fake)
    ingestor = DocumentIngestor.default()
    ingestor.register_converter(MarkItDownAdapter(), priority=100.0)
    info = DocumentSourceInfo(extension=".txt", local_path=str(source))
    result = ingestor.convert(io.BytesIO(b"plain"), source_info=info)

    assert result.markdown == "# 바뀐 글"
    assert result.engine == "markitdown"
    assert [attempt.converter for attempt in result.attempts] == ["HwpxMarkdownConverter", "MarkItDownAdapter"]
