# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, cast
from xml.etree import ElementTree as ET

from ..upstream import (
    ValidationReport,
    create_text_extractor,
    open_package,
    validate_document_path,
)

from .context import DocumentContext

logger = logging.getLogger("hwpx_automation.hwpx_ops")


class PackageValidationService:
    def __init__(self, context: DocumentContext) -> None:
        self._context = context

    def package_parts(self, path: str) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        package = open_package(resolved)
        parts = sorted(package.part_names())
        return {"parts": parts}

    def package_get_text(
        self, path: str, part_name: str, encoding: str | None = None
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        package = open_package(resolved)
        text = package.get_text(part_name, encoding=encoding or "utf-8")
        return {"text": text}

    def repair_hwpx(
        self,
        source: str,
        output: str,
        *,
        recover: bool = False,
        overwrite: bool = False,
        max_entry_size: int = 64 * 1024 * 1024,
        max_total_size: int = 512 * 1024 * 1024,
        max_source_size: int = 512 * 1024 * 1024,
    ) -> Dict[str, Any]:
        try:
            from hwpx.tools.package_validator import validate_editor_open_safety
            from hwpx.tools.package_validator import validate_package
            from hwpx.tools.repair import repair_from_recovered, repair_repack
        except Exception as exc:  # pragma: no cover - depends on installed python-hwpx
            raise self._context._new_error(
                "REPAIR_UNAVAILABLE",
                "python-hwpx repair support is not available; install a python-hwpx build with hwpx.tools.repair",
                hint="Upgrade python-hwpx to a version that includes hwpx.tools.repair and hwpx.tools.recover.",
            ) from exc

        source_path = self._context._resolve_path(source)
        output_path = self._context.storage.resolve_output_path(output)
        if recover:
            result = repair_from_recovered(
                source_path,
                output_path,
                overwrite=overwrite,
                max_entry_size=max_entry_size,
                max_total_size=max_total_size,
                max_source_size=max_source_size,
            )
        else:
            result = repair_repack(
                source_path,
                output_path,
                overwrite=overwrite,
                max_entry_size=max_entry_size,
                max_total_size=max_total_size,
            )
        validation = validate_package(output_path)
        open_safety = validate_editor_open_safety(output_path)
        return {
            "outputPath": self._context._relative_path(output_path),
            "entries": list(result.entries),
            "entryCount": len(result.entries),
            "reordered": result.reordered,
            "crcOk": result.crc_ok,
            "recovered": result.recovered,
            "validatePackage": {
                "ok": validation.ok,
                "errors": [str(issue) for issue in validation.errors],
                "warnings": [str(issue) for issue in validation.warnings],
            },
            "openSafety": open_safety.to_dict(),
        }

    def list_master_pages_histories_versions(self, path: str) -> Dict[str, Any]:
        document, _ = self._context._open_document(path)
        master_pages = [
            getattr(page, "part_name", None) for page in document.parts.master_pages
        ]
        histories = [
            getattr(history, "part_name", None) for history in document.parts.histories
        ]
        version = document.parts.version
        version_info = (
            asdict(cast(Any, version)) if version and dataclasses.is_dataclass(version) else None
        )
        return {
            "masterPages": master_pages,
            "histories": histories,
            "versions": version_info,
        }

    def validate_structure(self, path: str, level: str = "basic") -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        report: ValidationReport = validate_document_path(resolved)
        issues = [
            {"part": issue.part_name, "message": issue.message, "severity": issue.severity}
            for issue in report.issues
        ]
        # python-hwpx's schema warnings do not fail a document; only its errors do.
        return {"ok": report.ok, "issues": issues}

    def lint_text_conventions(
        self,
        path: str,
        *,
        max_line_len: Optional[int] = None,
        forbid_patterns: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        patterns = [re.compile(pat) for pat in (forbid_patterns or [])]
        warnings: List[Dict[str, Any]] = []
        with create_text_extractor(resolved) as extractor:
            for paragraph in extractor.iter_document_paragraphs():
                text = paragraph.text()
                if max_line_len is not None and len(text) > max_line_len:
                    warnings.append(
                        {
                            "paragraphIndex": paragraph.index,
                            "message": f"Paragraph exceeds {max_line_len} characters",
                        }
                    )
                for pattern in patterns:
                    if pattern.search(text):
                        warnings.append(
                            {
                                "paragraphIndex": paragraph.index,
                                "message": f"Pattern '{pattern.pattern}' found",
                            }
                        )
        return {"warnings": warnings}

    def package_get_xml(self, path: str, part_name: str) -> Dict[str, Any]:
        resolved = self._context._resolve_path(path)
        package = open_package(resolved)
        element = package.get_xml(part_name)

        xml_string = ET.tostring(element, encoding="unicode")
        return {"xmlString": xml_string}
