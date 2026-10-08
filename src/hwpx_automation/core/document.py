# SPDX-License-Identifier: Apache-2.0
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from ..configuration import env_value
from ..storage import LocalDocumentStorage, open_local_document
from ..upstream import HwpxDocument, blank_document_template_bytes, open_document


def _local_storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(
        auto_backup=env_value("AUTOBACKUP", "1") == "1",
    )


def open_doc(path: str) -> HwpxDocument:
    if not os.path.exists(path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    return open_local_document(Path(path), role="local HWPX open")


def save_doc(doc: HwpxDocument, path: str, *, quality: Any = None) -> dict[str, Any]:
    storage = _local_storage()
    target = storage.resolve_output_path(path)
    return storage.save_document(doc, target, quality=quality)


def create_blank(path: str, title=None, author=None) -> dict[str, Any]:
    source = BytesIO(blank_document_template_bytes())
    doc = open_document(source)
    try:
        return save_doc(doc, path)
    finally:
        doc.close()
