# SPDX-License-Identifier: Apache-2.0
"""Old path of :mod:`hwpx_automation.ingest.adapters` (kept through 8.x).

The optional MarkItDown adapter moved into :mod:`hwpx_automation.ingest` with
the rest of document ingest. Import it from there::

    from hwpx_automation.ingest import MarkItDownAdapter, MissingMarkItDownDependency

This module *is* the new one under its old name, so every attribute, and a
patch of one, is shared. It goes away in the next major.
"""

from __future__ import annotations

import sys

from .ingest import adapters as _adapters
from .ingest.adapters import (
    MarkItDownAdapter as MarkItDownAdapter,
    MissingMarkItDownDependency as MissingMarkItDownDependency,
)
from .ingest.base import (
    DocumentIngestError as DocumentIngestError,
    DocumentIngestResult as DocumentIngestResult,
    DocumentSourceInfo as DocumentSourceInfo,
)

sys.modules[__name__] = _adapters
