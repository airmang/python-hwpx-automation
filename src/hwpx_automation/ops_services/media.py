# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Dict, Optional

from ..core.transactions import (
    save_dry_run,
)
from ..upstream import (
    HwpxDocument,
)
from hwpx.tools.id_integrity import check_id_integrity

from .context import DocumentContext
from .save_policy import SavePolicy

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class MediaService:
    def __init__(self, context: DocumentContext, save: SavePolicy) -> None:
        self._context = context
        self._save = save

    def _decode_image_base64(self, image_base64: str) -> bytes:
        try:
            payload = base64.b64decode((image_base64 or "").strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid image_base64 payload") from exc
        if not payload:
            raise ValueError("image_base64 decoded to empty payload")
        return payload

    def _id_integrity_payload(self, document: HwpxDocument) -> Dict[str, Any]:
        report = check_id_integrity(document)
        return {
            "ok": report.ok,
            "dangling": [str(item) for item in report.dangling],
            "orphanBinData": [str(item) for item in report.orphan_bin_data],
            "ignored": [str(item) for item in report.ignored],
        }

    def add_shape(
        self,
        path: str,
        *,
        shape_type: str = "RECTANGLE",
        section_index: Optional[int] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        shape = document.shapes.add_raw(shape_type, section=section_index)
        if not dry_run:
            self._save._save_document(document, resolved)
        return {"objectId": shape.element.get("id")}

    def add_control(
        self,
        path: str,
        *,
        control_type: str = "TEXTBOX",
        section_index: Optional[int] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        control = document.shapes.add_control(
            control_type=control_type, section=section_index
        )
        if not dry_run:
            self._save._save_document(document, resolved)
        return {"objectId": control.element.get("id")}

    def insert_picture(
        self,
        path: str,
        image_base64: str,
        *,
        image_format: str = "png",
        width: Optional[int] = None,
        height: Optional[int] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        section_index: Optional[int] = None,
        align: Optional[str] = None,
        output: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        target = (
            self._context._resolve_path(output, must_exist=False)
            if output
            else resolved
        )
        document.add_picture(
            self._decode_image_base64(image_base64),
            image_format,
            width=width,
            height=height,
            width_mm=width_mm,
            height_mm=height_mm,
            section=section_index,
            align=align,
        )
        # media.picture_references now returns tuple[PictureRef, ...] rather
        # than list[dict] (design §2.5) — .to_dict() per entry keeps this
        # service's own dict-shaped response unchanged.
        picture_refs = [ref.to_dict() for ref in document.media.picture_references()]
        result: Dict[str, Any] = {
            "ok": True,
            "dryRun": dry_run,
            "filename": path,
            "outputPath": str(target),
            "picture": picture_refs[-1] if picture_refs else None,
            "pictureReferences": picture_refs,
            "idIntegrity": self._id_integrity_payload(document),
        }
        if dry_run:
            result.update(save_dry_run(document, target))
            return result
        verification = self._save._save_transaction_document(document, target)
        result["verificationReport"] = verification
        result["openSafety"] = verification.get("openSafety")
        if "visualComplete" in verification:
            result["visualComplete"] = verification["visualComplete"]
        if "backup" in verification:
            result["backup"] = verification["backup"]
        if "semanticDiff" in verification:
            result["semanticDiff"] = verification["semanticDiff"]
        return result

    def replace_picture(
        self,
        path: str,
        image_base64: str,
        *,
        image_format: str = "png",
        picture_index: int = 0,
        binary_item_id_ref: Optional[str] = None,
        remove_orphaned: bool = True,
        output: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document, resolved = self._context._open_document(path)
        target = (
            self._context._resolve_path(output, must_exist=False)
            if output
            else resolved
        )
        # media.replace_picture now returns a frozen PictureReplacement
        # (design §2.4: item_id/previous_item_id/removed_orphans/picture)
        # rather than a dict — its own .to_dict() uses different field names
        # (itemId/previousItemId/removedOrphans) than this op's established
        # response contract (old_binaryItemIDRef/new_binaryItemIDRef/
        # removedOldImage/geometryPreserved/picture_index/section_index),
        # which existing callers/tests depend on, so rebuild that exact shape
        # from the new object instead of using PictureReplacement.to_dict().
        replacement = document.media.replace_picture(
            self._decode_image_base64(image_base64),
            image_format,
            picture_index=picture_index,
            binary_item_id_ref=binary_item_id_ref,
            remove_orphaned=remove_orphaned,
        )
        replaced_section_index = next(
            (
                index
                for index, section in enumerate(document.sections)
                if section.element is replacement.picture.paragraph.section.element
            ),
            None,
        )
        replacement_payload = {
            "picture_index": picture_index,
            "section_index": replaced_section_index,
            "old_binaryItemIDRef": replacement.previous_item_id,
            "new_binaryItemIDRef": replacement.item_id,
            "removedOldImage": bool(replacement.removed_orphans),
            "geometryPreserved": True,
        }
        # media.picture_references now returns tuple[PictureRef, ...] rather
        # than list[dict] (design §2.5) — .to_dict() per entry keeps this
        # service's own dict-shaped response unchanged.
        result: Dict[str, Any] = {
            "ok": True,
            "dryRun": dry_run,
            "filename": path,
            "outputPath": str(target),
            "replacement": replacement_payload,
            "pictureReferences": [ref.to_dict() for ref in document.media.picture_references()],
            "idIntegrity": self._id_integrity_payload(document),
        }
        if dry_run:
            result.update(save_dry_run(document, target))
            return result
        verification = self._save._save_transaction_document(document, target)
        result["verificationReport"] = verification
        result["openSafety"] = verification.get("openSafety")
        if "visualComplete" in verification:
            result["visualComplete"] = verification["visualComplete"]
        if "backup" in verification:
            result["backup"] = verification["backup"]
        if "semanticDiff" in verification:
            result["semanticDiff"] = verification["semanticDiff"]
        return result
