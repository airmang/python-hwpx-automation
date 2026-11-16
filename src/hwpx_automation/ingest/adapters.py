# SPDX-License-Identifier: Apache-2.0
"""Converters for documents other than HWPX/HWP (optional MarkItDown).

:class:`MarkItDownAdapter` hands a non-HWPX source to Microsoft MarkItDown
(``pip install "python-hwpx-automation[ingest]"``). MarkItDown is imported only
when a conversion runs, so importing this module stays light.

This was ``hwpx_automation.ingest_adapters`` before 8.0; that path still
works for one major (it is this module).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from ._types import (
    DocumentIngestError,
    DocumentIngestResult,
    DocumentSourceInfo,
)

__all__ = ["MarkItDownAdapter", "MissingMarkItDownDependency"]


class MissingMarkItDownDependency(DocumentIngestError):
    """Raised when the optional MarkItDown runtime is not installed."""


class MarkItDownAdapter:
    """Fallback converter that delegates non-HWPX sources to Microsoft MarkItDown."""

    name = "MarkItDownAdapter"

    def accepts(self, file_stream: BinaryIO, source_info: DocumentSourceInfo) -> bool:
        del file_stream
        extension = (source_info.extension or "").lower()
        return extension != ".hwpx"

    def convert(
        self,
        file_stream: BinaryIO,
        source_info: DocumentSourceInfo,
        **kwargs: Any,
    ) -> DocumentIngestResult:
        del kwargs
        markitdown_cls = _load_markitdown_class()
        source_path = _source_path(file_stream, source_info)
        result = markitdown_cls().convert(str(source_path))
        markdown = _extract_markdown(result)
        return DocumentIngestResult(
            markdown=markdown,
            source_info=source_info,
            source_format=(source_info.extension or "unknown").lstrip(".") or "unknown",
            engine="markitdown",
            metadata={"converter": self.name},
            warnings=[
                "Converted by optional MarkItDown adapter; layout fidelity is not claimed.",
            ],
            lossiness="unknown",
        )


def _load_markitdown_class() -> type:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise MissingMarkItDownDependency(
            "install python-hwpx-automation[ingest] (or hwpx-mcp-server[ingest]) "
            "to enable non-HWPX document ingest"
        ) from exc
    return MarkItDown


def _source_path(file_stream: BinaryIO, source_info: DocumentSourceInfo) -> Path:
    if source_info.local_path:
        return Path(source_info.local_path)

    suffix = source_info.extension or ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        start_pos = file_stream.tell()
        tmp.write(file_stream.read())
        file_stream.seek(start_pos)
        return Path(tmp.name)


def _extract_markdown(result: Any) -> str:
    for attr in ("text_content", "markdown", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(result, str):
        return result
    raise ValueError("MarkItDown result did not include Markdown text")
