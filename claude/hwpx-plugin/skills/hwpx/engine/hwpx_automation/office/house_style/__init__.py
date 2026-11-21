# SPDX-License-Identifier: Apache-2.0
"""Typed house-style data service owned by the automation application layer."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .composition import SectionChipPlan, compose_section_chip

BANK_SCHEMA_VERSION = "hwpx.house-style-bank/v0"
GENRES_SCHEMA_VERSION = "hwpx.house-style-genres/v0"


class HouseStyleDataError(ValueError):
    """The packaged bank or genre grammar violates its frozen schema."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class HouseStyleBank(_FrozenModel):
    schema_version: str = Field(alias="schemaVersion")
    generated: str
    status: str
    research_doc: str = Field(alias="researchDoc")
    usage: str = Field(alias="_usage")
    font_safety: dict[str, Any] = Field(alias="fontSafety")
    shared_rules: list[str] = Field(alias="sharedRules")
    profiles: dict[str, dict[str, Any]]

    @field_validator("schema_version")
    @classmethod
    def _schema_is_exact(cls, value: str) -> str:
        if value != BANK_SCHEMA_VERSION:
            raise ValueError(f"expected {BANK_SCHEMA_VERSION!r}, got {value!r}")
        return value

    @field_validator("profiles")
    @classmethod
    def _profiles_are_named_objects(
        cls,
        value: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not value or any(not name.strip() or not isinstance(profile, dict) for name, profile in value.items()):
            raise ValueError("profiles must be a non-empty map of named objects")
        return value


class GenreDefinition(_FrozenModel):
    label: str
    when: str
    typography: dict[str, Any]
    grammar: dict[str, Any]


class GenreCatalog(_FrozenModel):
    schema_version: str = Field(alias="schemaVersion")
    generated: str
    usage: str = Field(alias="_usage")
    genres: dict[str, GenreDefinition]

    @field_validator("schema_version")
    @classmethod
    def _schema_is_exact(cls, value: str) -> str:
        if value != GENRES_SCHEMA_VERSION:
            raise ValueError(f"expected {GENRES_SCHEMA_VERSION!r}, got {value!r}")
        return value

    @field_validator("genres")
    @classmethod
    def _genres_are_nonempty(
        cls,
        value: dict[str, GenreDefinition],
    ) -> dict[str, GenreDefinition]:
        if not value:
            raise ValueError("genres must be a non-empty map")
        return value


def validate_bank(payload: dict[str, Any]) -> HouseStyleBank:
    """Validate a decoded bank payload or fail closed with one public error."""

    try:
        return HouseStyleBank.model_validate(payload)
    except ValidationError as exc:
        raise HouseStyleDataError(f"invalid house-style bank: {exc}") from exc


def validate_genres(payload: dict[str, Any]) -> GenreCatalog:
    """Validate a decoded genre payload or fail closed with one public error."""

    try:
        return GenreCatalog.model_validate(payload)
    except ValidationError as exc:
        raise HouseStyleDataError(f"invalid house-style genres: {exc}") from exc


def _load_payload(filename: str) -> dict[str, Any]:
    try:
        text = (
            resources.files("hwpx_automation.office.house_style")
            .joinpath("data")
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise HouseStyleDataError(f"cannot load packaged house-style data {filename!r}") from exc
    if not isinstance(payload, dict):
        raise HouseStyleDataError(f"house-style data {filename!r} must be a JSON object")
    return payload


@lru_cache(maxsize=1)
def load_bank() -> HouseStyleBank:
    return validate_bank(_load_payload("bank.json"))


@lru_cache(maxsize=1)
def load_genres() -> GenreCatalog:
    return validate_genres(_load_payload("genres.json"))


def list_profiles() -> list[str]:
    return sorted(load_bank().profiles)


def get_profile(name: str) -> dict[str, Any]:
    profiles = load_bank().profiles
    if name not in profiles:
        raise KeyError(f"unknown house-style profile: {name!r} (have {sorted(profiles)})")
    return copy.deepcopy(profiles[name])


def list_genres() -> list[str]:
    return sorted(load_genres().genres)


def get_genre(name: str) -> GenreDefinition:
    genres = load_genres().genres
    if name not in genres:
        raise KeyError(f"unknown genre: {name!r} (have {sorted(genres)})")
    return genres[name]


def genre_typography(name: str) -> dict[str, Any]:
    typography = get_genre(name).typography
    base_name = typography.get("inherits")
    roles: dict[str, Any] = {}
    if base_name:
        roles.update(get_profile(str(base_name)).get("roles", {}))
    roles.update(copy.deepcopy(typography.get("roles", {})))
    return {"inherits": base_name, "roles": roles}


def font_policy() -> dict[str, Any]:
    return copy.deepcopy(load_bank().font_safety)


def resolve_font(font: str, *, mode: str = "hancom-native") -> str:
    if mode != "portable":
        return font
    return str(font_policy().get("portableMap", {}).get(font, font))


__all__ = [
    "BANK_SCHEMA_VERSION",
    "GENRES_SCHEMA_VERSION",
    "GenreCatalog",
    "GenreDefinition",
    "HouseStyleBank",
    "HouseStyleDataError",
    "SectionChipPlan",
    "compose_section_chip",
    "font_policy",
    "genre_typography",
    "get_genre",
    "get_profile",
    "list_genres",
    "list_profiles",
    "load_bank",
    "load_genres",
    "resolve_font",
    "validate_bank",
    "validate_genres",
]
