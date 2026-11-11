# SPDX-License-Identifier: Apache-2.0
"""Application workflow over the generic core merge seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hwpx.tools.mail_merge import (
    inspect_mail_merge_placeholders as inspect_core_placeholders,
)
from hwpx.tools.mail_merge import merge_template_rows

from ..form_fill.fit import FitMode, FitPolicy

if TYPE_CHECKING:
    from hwpx.document import HwpxDocument


def inspect_mail_merge_placeholders(
    source: str | Path | HwpxDocument,
) -> dict[str, Any]:
    """Return placeholders through the generic core document inspector."""

    return inspect_core_placeholders(source)


def build_mail_merge(
    template: str | Path,
    data: str | Path | Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    output_dir: str | Path | None = None,
    filename_pattern: str = "{index:03d}.hwpx",
    zip_path: str | Path | None = None,
    strict: bool = False,
    split_newlines: bool = True,
    fit_mode: str | None = None,
    max_lines: int = 1,
) -> dict[str, Any]:
    """Run mail merge with the automation-owned fit policy.

    Each generated document receives the row values exactly as given. The report
    carries field names and counts, never the values, so nothing in it needs masking.
    """

    fit_policy = None
    if fit_mode:
        valid_modes = set(getattr(FitMode, "__args__", ()))
        if valid_modes and fit_mode not in valid_modes:
            raise ValueError(
                f"unknown fit_mode {fit_mode!r}; expected one of "
                f"{sorted(valid_modes)}"
            )
        fit_policy = FitPolicy(
            mode=cast(FitMode, fit_mode),
            max_lines=max_lines,
        )

    return merge_template_rows(
        template,
        data,
        output_dir=output_dir,
        filename_pattern=filename_pattern,
        zip_path=zip_path,
        strict=strict,
        split_newlines=split_newlines,
        fit_policy=fit_policy,
        max_lines=max_lines,
    )


__all__ = ["build_mail_merge", "inspect_mail_merge_placeholders"]
