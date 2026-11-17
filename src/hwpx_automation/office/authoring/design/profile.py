# SPDX-License-Identifier: Apache-2.0
"""Profile loader + registry (plan §2 Phase E, task 1).

A :class:`Profile` bundles a verified Hancom-saved skeleton ``template.hwpx`` with the
harvested fragments keyed by role. The default registry loads the profiles committed
under ``profiles/``.

Profile format ``hwpx.design.profile.v2`` keeps the fragments in a document of their
own, ``fragments.hwpx``: the skeleton with the fragment paragraphs after its first
(page-setup) paragraph, and ``"fragments": {role: {"start": i, "count": n}}`` naming
each role's paragraphs by their place in that document's first section. The composer
copies them into the new document with python-hwpx's ``paragraph.copy_to``, which brings
the character and paragraph shapes they use along.

A ``hwpx.design.profile.v1`` profile (fragments as ``<hp:p>`` XML files) still loads: its
fragments are put into such a document in memory (:func:`_v1_fragments_document`); the
files on disk are not changed. That bridge is for the 8.x releases.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]

PROFILES_DIRNAME = "profiles"
PROFILE_SCHEMA_V1 = "hwpx.design.profile.v1"
PROFILE_SCHEMA_V2 = "hwpx.design.profile.v2"
FRAGMENTS_DOCUMENT = "fragments.hwpx"
# Wrapper for a multi-paragraph v1 fragment file (marked profiles); never in a document.
_V1_FRAGMENT_WRAPPER_TAG = "fragment"


@dataclass(slots=True)
class Profile:
    """A verified template skeleton + its harvested fragments."""

    id: str
    root: Path
    manifest: dict[str, Any]
    template_bytes: bytes
    fragments_bytes: bytes = b""
    #: role -> (index of its first paragraph in the fragments document's first section, paragraph count)
    _places: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def style_coverage_threshold(self) -> float:
        return float(self.manifest.get("style_coverage_threshold", 0.98))

    @property
    def schema(self) -> str:
        return str(self.manifest.get("schemaVersion", PROFILE_SCHEMA_V1))

    @property
    def roles(self) -> list[str]:
        return list(self._places)

    def has_role(self, role: str) -> bool:
        return role in self._places

    def fragment_place(self, role: str) -> tuple[int, int]:
        """``(start, count)`` of the *role*'s paragraphs in the fragments document's first section."""

        if role not in self._places:
            raise KeyError(f"profile {self.id!r} has no fragment for role {role!r}")
        return self._places[role]

    def fragment(self, role: str) -> etree._Element:
        """A detached XML copy of the *role* fragment, as v1 profiles kept it: its ``<hp:p>``, or a
        ``<fragment>`` wrapper around several. Kept for 8.x callers; compose copies paragraphs
        (:meth:`fragment_paragraphs`) instead."""

        from copy import deepcopy

        from hwpx.document import HwpxDocument

        with HwpxDocument.open(self.fragments_bytes) as document:
            elements = [deepcopy(p.element) for p in self.fragment_paragraphs(document, role)]
        if len(elements) == 1:
            return elements[0]
        wrapper = etree.Element(_V1_FRAGMENT_WRAPPER_TAG)
        wrapper.extend(elements)
        return wrapper

    def fragment_paragraphs(self, fragments_document: Any, role: str) -> list[Any]:
        """The *role*'s paragraphs in *fragments_document* (``HwpxDocument.open(profile.fragments_bytes)``)."""

        start, count = self.fragment_place(role)
        return list(fragments_document.sections[0].paragraphs[start : start + count])

    @classmethod
    def load(cls, root: str | Path) -> "Profile":
        root = Path(root)
        manifest = json.loads((root / "profile.json").read_text(encoding="utf-8"))
        template_bytes = (root / manifest["template"]).read_bytes()
        schema = manifest.get("schemaVersion", PROFILE_SCHEMA_V1)
        if schema == PROFILE_SCHEMA_V2:
            fragments_bytes = (root / manifest.get("fragments_document", FRAGMENTS_DOCUMENT)).read_bytes()
            places = {
                role: (int(place["start"]), int(place["count"]))
                for role, place in manifest.get("fragments", {}).items()
            }
        elif schema == PROFILE_SCHEMA_V1:
            v1 = {role: (root / rel).read_bytes() for role, rel in manifest.get("fragments", {}).items()}
            template_bytes = _v1_template(template_bytes)
            fragments_bytes, places = _v1_fragments_document(template_bytes, v1)
        else:
            raise ValueError(f"profile {manifest.get('id')!r}: unknown schemaVersion {schema!r}")
        return cls(
            id=manifest["id"],
            root=root,
            manifest=manifest,
            template_bytes=template_bytes,
            fragments_bytes=fragments_bytes,
            _places=places,
        )


_HS = "{http://www.hancom.co.kr/hwpml/2011/section}"
_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_CARRIER_ATTRIBUTES = {
    "id": "0", "paraPrIDRef": "0", "styleIDRef": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0",
}


def _v1_template(template_bytes: bytes) -> bytes:
    """A v1 skeleton whose page-setup paragraph is a paragraph Hancom reads.

    Skeletons harvested before 8.0 wrote that paragraph in the section namespace
    (``<hs:p><hs:run><hp:secPr/>…<hs:t/></hs:run></hs:p>``). The v1 composer dropped it,
    so it did no harm there; v2 hands its section settings to the first composed
    paragraph, so it is rewritten as ``hp:p``/``hp:run``/``hp:t`` here (in memory; the
    profile on disk is not changed). A skeleton that is already right comes back as it is.
    """

    from hwpx.document import HwpxDocument

    with HwpxDocument.open(template_bytes) as document:
        section = document.sections[0]
        carriers = [child for child in section.element if child.tag == f"{_HS}p"]
        if not carriers:
            return template_bytes
        for carrier in carriers:
            for node in carrier.iter():
                if isinstance(node.tag, str) and node.tag.startswith(_HS) and node.tag[len(_HS):] in ("p", "run", "t"):
                    node.tag = _HP + node.tag[len(_HS):]
            for name, value in _CARRIER_ATTRIBUTES.items():
                if carrier.get(name) is None:
                    carrier.set(name, value)
        section.mark_dirty()
        buffer = io.BytesIO()
        document.save(buffer)
    return buffer.getvalue()


def _v1_fragments_document(
    template_bytes: bytes, fragments: dict[str, bytes]
) -> tuple[bytes, dict[str, tuple[int, int]]]:
    """A v2 fragments document made in memory from v1 fragment XML (the 8.x bridge).

    The v1 fragments are ``<hp:p>`` elements of the skeleton's own source, so their
    shape ids are the skeleton's: they go after the skeleton's page-setup paragraph as
    they are. This is the one place the design package still writes XML into a
    document, and it goes when v1 profiles stop being read.
    """

    from hwpx.document import HwpxDocument

    places: dict[str, tuple[int, int]] = {}
    with HwpxDocument.open(template_bytes) as document:
        section = document.sections[0]
        container = section.element
        next_index = len(section.paragraphs)
        for role, data in fragments.items():
            element = etree.fromstring(data)
            paragraphs = list(element) if element.tag == _V1_FRAGMENT_WRAPPER_TAG else [element]
            for paragraph in paragraphs:
                container.append(paragraph)
            places[role] = (next_index, len(paragraphs))
            next_index += len(paragraphs)
        section.mark_dirty()
        buffer = io.BytesIO()
        document.save(buffer)
    return buffer.getvalue(), places


@lru_cache(maxsize=1)
def _registry_root() -> Path:
    return Path(__file__).resolve().parent / PROFILES_DIRNAME


def available_profiles() -> list[str]:
    root = _registry_root()
    return sorted(p.name for p in root.iterdir() if (p / "profile.json").exists())


@lru_cache(maxsize=None)
def load_profile(profile_id: str) -> Profile:
    """Load a committed profile by id (cached)."""

    root = _registry_root() / profile_id
    if not (root / "profile.json").exists():
        raise KeyError(
            f"unknown profile {profile_id!r}; available: {available_profiles()}"
        )
    return Profile.load(root)


__all__ = [
    "FRAGMENTS_DOCUMENT",
    "PROFILES_DIRNAME",
    "PROFILE_SCHEMA_V1",
    "PROFILE_SCHEMA_V2",
    "Profile",
    "available_profiles",
    "load_profile",
]
