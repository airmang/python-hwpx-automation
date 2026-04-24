#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""새 HWPX 문서를 만들고 저장하는 예제."""

from __future__ import annotations

from pathlib import Path

from hwpx import HwpxDocument


def main() -> None:
    # 예제 결과물은 examples/out 아래에 저장한다.
    output_path = Path(__file__).resolve().parent / "out" / "01_created.hwpx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 새 문서를 만들고 기본 문단을 추가한다.
    doc = HwpxDocument.new()
    doc.add_paragraph("2026학년도 1학기 가정통신문")
    doc.add_paragraph("학부모님께 안내드립니다.")

    # 표를 하나 만들고 셀 텍스트를 채운다.
    table = doc.add_table(3, 2)
    table.set_cell_text(0, 0, "항목")
    table.set_cell_text(0, 1, "내용")
    table.set_cell_text(1, 0, "제출일")
    table.set_cell_text(1, 1, "2026-03-20")
    table.set_cell_text(2, 0, "문의")
    table.set_cell_text(2, 1, "교무실 02-123-4567")

    # 파일로 저장한다.
    doc.save_to_path(str(output_path))
    print(f"[OK] wrote: {output_path}")


if __name__ == "__main__":
    main()
