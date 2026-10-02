# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..errors import HwpDocumentError, hwp5_error_payload
from ..hwp_support import HwpBinaryError, extract_hwp_text
from ..core.locator import RegisteredHandle
from ..core.context import default_session_lifecycle_policy
from ..storage import DocumentStorage, LocalDocumentStorage, require_hwpx_package
from ..workspace import (
    WorkspacePathError,
)
from ..upstream import (
    HwpxDocument,
    HwpxOxmlParagraph,
    HwpxOxmlTable,
    hwpx_view_bytes,
    native_hwp5_supported,
)

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class DocumentContext:
    def __init__(
        self,
        *,
        storage: DocumentStorage,
        paging_paragraph_limit: int,
        error_type: Callable[..., RuntimeError],
        handle_error_type: type[RuntimeError],
    ) -> None:
        self.storage = storage
        self.base_directory = storage.base_directory
        self.paging_limit = max(1, paging_paragraph_limit)
        self._registered_handles: Dict[str, RegisteredHandle] = {}
        self._error_type = error_type
        self._handle_error_type = handle_error_type

    @property
    def registered_handles(self) -> Dict[str, RegisteredHandle]:
        return self._registered_handles

    def _local_storage(self) -> LocalDocumentStorage:
        """Return :attr:`storage` narrowed to the local filesystem backend.

        Guarded exact-sidecar publication (``atomic_publish_bytes`` /
        ``read_guarded_bytes`` / ``remove_guarded_output`` /
        ``materialize_output_guard`` / ``cleanup_owned_parent_directories``) is a
        filesystem-workspace capability only :class:`LocalDocumentStorage`
        provides; non-local backends route through their own fallback paths.
        Every caller reaches these methods only after an ``isinstance`` gate or
        ``_capture_exact_sidecar_guard`` has already established the local
        backend, so this re-expresses that invariant for the type checker and
        fails closed with the same error the sidecar machinery already raises.
        """
        storage = self.storage
        if not isinstance(storage, LocalDocumentStorage):
            raise TypeError("exact sidecar operations require local storage")
        return storage

    def _new_error(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        hint: Optional[str] = None,
    ) -> RuntimeError:
        return self._error_type(message, code=code, details=details, hint=hint)

    def _resolve_path(self, path: str, *, must_exist: bool = True) -> Path:
        try:
            resolved = self.storage.resolve_path(path, must_exist=must_exist)
        except FileNotFoundError as exc:
            raise self._new_error(
                "DOCUMENT_NOT_FOUND",
                "요청한 문서를 허용된 작업공간에서 찾을 수 없습니다.",
                details={"requestedName": Path(path).name},
            ) from exc
        except WorkspacePathError as exc:
            raise self._new_error(
                exc.code,
                "요청한 경로가 허용된 HWPX 작업공간 경계를 벗어났습니다.",
                details=exc.safe_details(),
            ) from exc
        except PermissionError as exc:
            raise self._new_error(
                "PERMISSION_DENIED",
                "요청한 문서에 접근할 권한이 없습니다.",
                details={"requestedName": Path(path).name},
            ) from exc
        self._register_handle(path, resolved)
        return resolved

    def _make_handle_id(self, path: str, backend: Optional[str] = None) -> str:
        seed = f"{backend or 'local'}::{path}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return f"h_{digest}"

    def _register_handle(self, path: str, resolved: Path) -> RegisteredHandle:
        relative = self._relative_path(resolved)
        handle_id = self._make_handle_id(relative)
        handle = RegisteredHandle(type="handle", handleId=handle_id, path=relative)
        self._registered_handles[handle_id] = handle
        return handle

    def list_registered_handles(self) -> List[RegisteredHandle]:
        return sorted(
            self._registered_handles.values(), key=lambda item: item.handle_id
        )

    def open_document_handle(self, path: str) -> Dict[str, Any]:
        resolved = self._resolve_path(path)
        handle = self._register_handle(path, resolved)
        return {"handle": handle.model_dump(by_alias=True)}

    def list_open_documents(self) -> Dict[str, Any]:
        policy = default_session_lifecycle_policy()
        return {
            "documents": [
                handle.model_dump(by_alias=True)
                for handle in self.list_registered_handles()
            ],
            "sessionPolicy": policy.as_dict(),
        }

    def close_document_handle(self, handle_id: str) -> Dict[str, Any]:
        removed = self._registered_handles.pop(handle_id, None)
        return {"closed": removed is not None}

    def get_registered_handle(self, handle_id: str) -> RegisteredHandle:
        handle = self._registered_handles.get(handle_id)
        if handle is None:
            raise self._handle_error_type(f"등록되지 않은 handleId입니다: {handle_id}")
        return handle

    def resolve_document_path(
        self,
        *,
        path: Optional[str] = None,
        handle_id: Optional[str] = None,
    ) -> str:
        if path:
            return path
        if handle_id:
            return self.get_registered_handle(handle_id).path
        raise self._new_error(
            "DOCUMENT_LOCATOR_REQUIRED",
            "path 또는 handleId 중 하나를 제공해야 합니다.",
        )

    def _resolve_output_path(self, path: str) -> Path:
        return self.storage.resolve_output_path(path)

    def _relative_path(self, path: Path) -> str:
        return self.storage.relative_path(path)

    def _is_legacy_hwp(self, resolved: Path) -> bool:
        """An ``.hwp`` the installed core cannot open; only its preview text is readable."""

        return resolved.suffix.lower() == ".hwp" and not native_hwp5_supported()

    def _text_source(self, resolved: Path) -> Path | ZipFile:
        """What the text extractor reads: the HWPX file, or an ``.hwp``'s HWPX model."""

        if resolved.suffix.lower() != ".hwp":
            return resolved
        try:
            return ZipFile(BytesIO(hwpx_view_bytes(resolved)))
        except Exception as exc:
            hwp_error = self._hwp_error(exc)
            if hwp_error is None:
                raise
            raise hwp_error from exc

    def _hwp_error(self, exc: BaseException) -> Optional[RuntimeError]:
        """The operation error for an ``.hwp`` refusal, or None for any other failure."""

        if isinstance(exc, HwpDocumentError):
            return self._new_error(exc.code, exc.message, details=exc.details)
        payload = hwp5_error_payload(exc)
        if payload is None:
            return None
        return self._new_error(
            payload["code"], payload["message"], details=payload.get("details")
        )

    def _require_hwpx_package(self, source: Path, output: Optional[str] = None) -> None:
        """Refuse ``.hwp`` for editors that patch HWPX package bytes."""

        try:
            require_hwpx_package(source, output=output)
        except HwpDocumentError as exc:
            raise self._new_error(exc.code, exc.message, details=exc.details) from exc

    def _open_document(self, path: str) -> Tuple[HwpxDocument, Path]:
        resolved = self._resolve_path(path)
        if self._is_legacy_hwp(resolved):
            raise self._new_error(
                "READ_ONLY_HWP_DOCUMENT",
                "설치된 python-hwpx는 HWP 5.0(.hwp) 문서를 열거나 저장하지 못합니다.",
            )
        try:
            document, resolved = self.storage.open_document(path)
        except FileNotFoundError as exc:
            raise self._new_error(
                "DOCUMENT_NOT_FOUND",
                "요청한 문서를 허용된 작업공간에서 찾을 수 없습니다.",
                details={"requestedName": Path(path).name},
            ) from exc
        except WorkspacePathError as exc:
            raise self._new_error(
                exc.code,
                "요청한 경로가 허용된 HWPX 작업공간 경계를 벗어났습니다.",
                details=exc.safe_details(),
            ) from exc
        except PermissionError as exc:
            raise self._new_error(
                "PERMISSION_DENIED",
                "요청한 문서에 접근할 권한이 없습니다.",
                details={"requestedName": Path(path).name},
            ) from exc
        except Exception as exc:  # pragma: no cover - delegated to backend
            hwp_error = self._hwp_error(exc)
            if hwp_error is not None:
                raise hwp_error from exc
            raise self._new_error(
                "DOCUMENT_OPEN_FAILED",
                f"failed to open '{path}': {exc}",
                details={"path": path},
            ) from exc
        return document, resolved

    def _read_only_hwp_paragraphs(self, path: str) -> Tuple[List[str], Path, str]:
        resolved = self._resolve_path(path)
        try:
            snapshot = extract_hwp_text(resolved)
        except HwpBinaryError as exc:
            raise self._new_error(
                "HWP_TEXT_EXTRACT_FAILED", f"HWP 텍스트 추출 실패: {exc}"
            ) from exc
        return snapshot.paragraphs, resolved, snapshot.source

    def _iter_paragraphs(self, document: HwpxDocument) -> List[HwpxOxmlParagraph]:
        return list(document.paragraphs)

    def _iter_tables(self, document: HwpxDocument) -> List[HwpxOxmlTable]:
        tables: List[HwpxOxmlTable] = []
        for paragraph in document.paragraphs:
            tables.extend(paragraph.tables)
        return tables
