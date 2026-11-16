# SPDX-License-Identifier: Apache-2.0
"""Document ingest: HWPX/HWP (and, optionally, other formats) to Markdown for indexing.

python-hwpx 7.0 keeps the engine (reading and writing what the file says); its
ingest moved here:

======================================  ==========================================
python-hwpx 6.x                         here
======================================  ==========================================
``hwpx.HwpxMarkdownConverter``          :class:`HwpxMarkdownConverter`
``hwpx.ingest.*``                       ``hwpx_automation.ingest.*``
``hwpx.experimental.DocumentIngestor``  :class:`DocumentIngestor` (and the other
                                        six ingest names)
======================================  ==========================================

The converter reads ``.hwpx`` and ``.hwp`` (HWP 5.0, through python-hwpx's
``HwpxDocument.open``) and gives the same Markdown, metadata, warnings and
lossiness as before. :class:`MarkItDownAdapter` (formerly
``hwpx_automation.ingest_adapters``) hands other formats to the optional
MarkItDown (``[ingest]`` extra), which is imported only when it converts.

This package imports only python-hwpx (no pydantic, no MCP): it is the light
layer of python-hwpx-automation.

    from hwpx_automation.ingest import DocumentIngestor

    result = DocumentIngestor.default().convert("계획.hwpx")
    result.markdown, result.flat_metadata()
"""

from __future__ import annotations

from .adapters import MarkItDownAdapter, MissingMarkItDownDependency
from .base import (
    ConversionAttempt,
    DocumentConverter,
    DocumentIngestError,
    DocumentIngestResult,
    DocumentIngestor,
    DocumentSourceInfo,
    UnsupportedDocumentFormat,
    normalize_markdown,
)
from .hwpx_converter import HwpxMarkdownConverter

__all__ = [
    "ConversionAttempt",
    "DocumentConverter",
    "DocumentIngestError",
    "DocumentIngestResult",
    "DocumentIngestor",
    "DocumentSourceInfo",
    "HwpxMarkdownConverter",
    "MarkItDownAdapter",
    "MissingMarkItDownDependency",
    "UnsupportedDocumentFormat",
    "normalize_markdown",
]
