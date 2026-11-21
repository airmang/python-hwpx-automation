# SPDX-License-Identifier: Apache-2.0
"""외부 라이브러리 호환성 패치."""

from __future__ import annotations

import builtins
from typing import Any
from xml.etree import ElementTree as _ET


_SUBELEMENT_PATCHED = False


def _patch_sub_element_for_lxml_parent() -> None:
    global _SUBELEMENT_PATCHED
    if _SUBELEMENT_PATCHED:
        return

    original_sub_element = _ET.SubElement

    def _safe_sub_element(parent: Any, tag: str, attrib: Any = None, **extra: Any):
        attrs = {} if attrib is None else dict(attrib)
        attrs.update(extra)
        try:
            return original_sub_element(parent, tag, attrs)
        except TypeError as exc:
            message = str(exc)
            if "lxml.etree._Element" not in message or not hasattr(parent, "makeelement"):
                raise
            child = parent.makeelement(tag, attrs)
            parent.append(child)
            return child

    _ET.SubElement = _safe_sub_element  # type: ignore[assignment]
    _SUBELEMENT_PATCHED = True


def patch_python_hwpx() -> None:
    """python-hwpx의 ET 누락/혼합 파서 호환 이슈를 보정합니다.

    python-hwpx 2.9.1부터 id 생성기는 업스트림에서 signed int32 범위로 정리됐기 때문에
    해당 사용자별 shim은 제거됐습니다. ``document.py`` 내에 남은 stdlib ``ET.SubElement``
    호출 경로에는 여전히 본 shim을 적용해 혼합 파서로 인한 ``TypeError``를 피합니다.
    """

    if not hasattr(builtins, "ET"):
        builtins.ET = _ET
    _patch_sub_element_for_lxml_parent()
