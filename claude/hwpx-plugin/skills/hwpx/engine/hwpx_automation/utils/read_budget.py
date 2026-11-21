# SPDX-License-Identifier: Apache-2.0
"""Bound summary projections without treating previews as complete targets."""

from __future__ import annotations

import json
from typing import Any

SUMMARY_MAX_CHARS = 16000
SUMMARY_MAX_ITEMS = 24
SUMMARY_MAX_TEXT = 256
_IDENTITY_KEYS = {
    "filename",
    "document_revision",
    "revision",
    "path",
    "stableId",
    "id",
    "field_id",
}


def bound_document_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep full counts and identities; explicitly mark every omitted preview.

    Existing full-mode maps are unaffected. A summary is for navigation only;
    selection and expected-count validation belong to revision-bound detail reads.
    """
    truncated = False

    def project(value: Any, key: str = "") -> Any:
        nonlocal truncated
        if isinstance(value, str):
            if key in _IDENTITY_KEYS:
                return value
            if len(value) > SUMMARY_MAX_TEXT:
                truncated = True
                return value[:SUMMARY_MAX_TEXT]
            return value
        if isinstance(value, list):
            if len(value) > SUMMARY_MAX_ITEMS:
                truncated = True
            return [project(item) for item in value[:SUMMARY_MAX_ITEMS]]
        if isinstance(value, dict):
            result = {}
            for name, item in value.items():
                if name.lower() in {
                    "base64",
                    "binary",
                    "datauri",
                    "imagebase64",
                    "styles",
                }:
                    truncated = True
                    continue
                result[name] = project(item, name)
            return result
        return value

    result = project(payload)
    result["summaryCoverage"] = {
        "paragraphs": payload["info"]["paragraphs"],
        "tables": payload["info"]["tables"],
        "sections": payload["info"]["sections"],
        "outlineEntries": len(payload.get("outline", [])),
        "figures": len(payload.get("anchors", {}).get("figures", [])),
        "formFields": len(payload.get("formFields", {}).get("fields", [])),
    }
    result["budget"] = {
        "maxChars": SUMMARY_MAX_CHARS,
        "maxItemsPerList": SUMMARY_MAX_ITEMS,
        "maxPreviewChars": SUMMARY_MAX_TEXT,
        "encoding": "JSON, ensure_ascii=False",
    }
    result["targetSelectionComplete"] = False
    result["continuation"] = {
        "tool": "get_document_node",
        "arguments": {
            "filename": payload["filename"],
            "path": "/",
            "depth": 1,
            "child_limit": SUMMARY_MAX_ITEMS,
            "expected_revision": payload.get("document_revision"),
        },
        "strategy": "Read children by canonical path. For omitted children, use 1-based kind[index] paths up to childCount. Never infer a unique match from a partial preview.",
    }
    result["truncated"] = truncated

    def lists(value: Any):
        if isinstance(value, list):
            if value:
                yield value
            for item in value:
                yield from lists(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from lists(item)

    while len(json.dumps(result, ensure_ascii=False)) > SUMMARY_MAX_CHARS:
        candidates = list(lists(result))
        if not candidates:
            # Real filenames are filesystem bounded. An oversized scalar metadata
            # payload still must not break the budget or masquerade as a full map.
            result["truncated"] = True
            result = {
                k: v
                for k, v in result.items()
                if k
                in {
                    "filename",
                    "document_revision",
                    "info",
                    "summaryCoverage",
                    "budget",
                    "targetSelectionComplete",
                    "continuation",
                    "truncated",
                }
            }
            if len(json.dumps(result, ensure_ascii=False)) > SUMMARY_MAX_CHARS:
                raise ValueError("summary metadata exceeds the response budget")
            break
        largest = max(
            candidates, key=lambda value: len(json.dumps(value, ensure_ascii=False))
        )
        largest.pop()
        result["truncated"] = True
    return result
