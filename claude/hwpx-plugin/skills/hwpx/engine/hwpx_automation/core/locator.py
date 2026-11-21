# SPDX-License-Identifier: Apache-2.0
"""Document locator models used across tool schemas."""

from __future__ import annotations

from typing import Annotated, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Literal


_LOCATOR_KEYS = {"type", "path", "uri", "backend", "handleId"}


class _LocatorModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PathLocator(_LocatorModel):
    type: Literal["path"] = Field("path", alias="type")
    path: str
    backend: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _default_type(cls, data: object) -> object:
        if isinstance(data, dict) and "type" not in data and "path" in data:
            enriched = dict(data)
            enriched.setdefault("type", "path")
            return enriched
        return data


class UriLocator(_LocatorModel):
    type: Literal["uri"] = Field("uri", alias="type")
    uri: str
    backend: Optional[str] = None


class HandleLocator(_LocatorModel):
    type: Literal["handle"] = Field("handle", alias="type")
    handle_id: str = Field(alias="handleId")
    backend: Optional[str] = None


class RegisteredHandle(_LocatorModel):
    """서버가 관리하는 등록 핸들의 읽기 전용 직렬화 모델."""

    type: Literal["handle"] = Field("handle", alias="type")
    handle_id: str = Field(alias="handleId")
    path: str
    backend: Optional[str] = None


DocumentLocator = Annotated[
    PathLocator | UriLocator | HandleLocator,
    Field(discriminator="type"),
]


def normalize_locator_payload(data: Dict[str, object], *, field_name: str = "document") -> Dict[str, object]:
    """Return *data* with locator keys grouped under *field_name*.

    The function accepts legacy payloads that specify ``path`` at the top level
    while also supporting fully qualified discriminated union inputs.
    """

    if field_name in data:
        return data

    locator: Dict[str, object] = {}
    remainder: Dict[str, object] = {}
    for key, value in data.items():
        if key in _LOCATOR_KEYS:
            locator[key] = value
        else:
            remainder[key] = value

    if not locator:
        raise ValueError("document locator must include path, uri, or handleId")

    if "type" not in locator:
        if "path" in locator:
            locator["type"] = "path"
        elif "uri" in locator:
            locator["type"] = "uri"
        elif "handleId" in locator:
            locator["type"] = "handle"
        else:  # pragma: no cover - defensive guard
            raise ValueError("document locator requires a discriminator")

    remainder[field_name] = locator
    return remainder


def locator_identifier(locator: DocumentLocator) -> str:
    """Return a stable identifier for *locator*."""

    if isinstance(locator, PathLocator):
        return locator.path
    if isinstance(locator, UriLocator):
        return locator.uri
    if isinstance(locator, HandleLocator):
        return locator.handle_id
    raise TypeError(f"Unsupported locator type: {type(locator)!r}")


def locator_path(locator: DocumentLocator) -> Optional[str]:
    """Return the preferred path-like value for *locator* if available."""

    if isinstance(locator, PathLocator):
        return locator.path
    if isinstance(locator, UriLocator):
        return locator.uri
    return None


def locator_backend(locator: DocumentLocator) -> Optional[str]:
    """Return the backend hint provided by *locator*, if any."""

    return getattr(locator, "backend", None)


def document_locator_schema() -> Dict[str, object]:
    """Return a sanitized JSON schema fragment for document locators."""

    return {
        "type": "object",
        "description": (
            "Discriminated locator supporting legacy paths, HTTP URIs, or opaque handles. "
            "Top-level path/uri/handleId shorthands remain supported for backwards compatibility."
        ),
        "properties": {
            "type": {
                "type": "string",
                "enum": ["path", "uri", "handle"],
                "description": "Locator variant; defaults to 'path' when omitted.",
            },
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Filesystem-relative path resolved by the configured storage backend.",
            },
            "uri": {
                "type": "string",
                "minLength": 1,
                "description": "HTTP or backend-specific URI when using remote storage.",
            },
            "handleId": {
                "type": "string",
                "minLength": 1,
                "description": "Opaque identifier for a previously registered document handle.",
            },
            "backend": {
                "type": "string",
                "minLength": 1,
                "description": "Optional hint describing the storage backend to use (e.g. 'http').",
            },
        },
        "required": ["type"],
        "additionalProperties": False,
    }
