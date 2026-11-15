# SPDX-License-Identifier: Apache-2.0
"""HWP(바이너리) 파일의 읽기 전용 텍스트 추출 유틸리티.

python-hwpx 6.6.0부터 본체가 HWP 5.0 문서를 직접 연다(이 패키지의 최소 지원
본체는 그보다 높다). 그래서 여기서는 OLE2 미리보기 글(PrvText)을 긁지 않고
본체가 읽은 문서 모델의 글을 그대로 쓴다. 표 안의 글도 들어오고 1KB 남짓에서
잘리는 미리보기의 한계도 없다. ``olefile``은 더 필요 없다.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(slots=True)
class HwpTextSnapshot:
    """HWP 파일에서 추출한 텍스트 스냅샷."""

    paragraphs: List[str]
    source: str


class HwpBinaryError(RuntimeError):
    """HWP 바이너리 처리 과정에서 발생한 오류."""


#: ``HwpTextSnapshot.source`` for text read through python-hwpx's own HWP 5.0 reader.
CORE_TEXT_SOURCE = "python-hwpx"


def extract_hwp_text(path: Path) -> HwpTextSnapshot:
    """Read the text of an ``.hwp`` document through python-hwpx.

    Each non-blank line of the document's plain text becomes one entry; table
    cells on one row are separated by tabs. Raises :class:`HwpBinaryError` when
    the file is not an ``.hwp`` or python-hwpx cannot open it (distribution or
    password-protected documents, damaged files, HWP 3.0).
    """

    path = Path(path)
    if path.suffix.lower() != ".hwp":
        raise HwpBinaryError(".hwp 파일만 처리할 수 있습니다")

    from hwpx.document import HwpxDocument

    try:
        with warnings.catch_warnings():
            # Unconverted content is reported by the converter, not here.
            warnings.simplefilter("ignore")
            document = HwpxDocument.open(str(path))
            try:
                text = document.text.plain()
            finally:
                document.close()
    except Exception as exc:
        raise HwpBinaryError(f"HWP 문서를 읽지 못했습니다: {exc}") from exc

    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraphs:
        return HwpTextSnapshot(paragraphs=[], source="empty")
    return HwpTextSnapshot(paragraphs=paragraphs, source=CORE_TEXT_SOURCE)
