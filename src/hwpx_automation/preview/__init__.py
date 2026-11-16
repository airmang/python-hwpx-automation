# SPDX-License-Identifier: Apache-2.0
"""HTML preview of HWPX documents (moved from python-hwpx 6.x).

python-hwpx 7.0 keeps reading and writing the file; drawing a preview moved
here. The names are the ones ``hwpx.experimental`` exported (layout preview,
document viewer) plus the equation renderer of ``hwpx.equation``:

* ``hwpx.experimental.render_layout_preview`` / ``LayoutPreview`` /
  ``PreviewPage`` → :func:`render_layout_preview`, :class:`LayoutPreview`,
  :class:`PreviewPage`
* ``hwpx.experimental.render_document_viewer`` / ``DocumentViewer`` →
  :func:`render_document_viewer`, :class:`DocumentViewer`
* ``hwpx.equation.render_equation`` and the MathML helpers →
  :func:`render_equation`, :func:`latex_to_mathml`, ...

MathML needs the optional ``latex2mathml`` package; without it equations
fall back to a LaTeX code block, never to nothing.

This module is part of the light layer: importing it loads python-hwpx and
the standard library only.
"""

from __future__ import annotations

from .document_viewer import FIDELITY_BADGE, DocumentViewer, render_document_viewer
from .equation_render import (
    LABEL_LATEX_ERROR,
    LABEL_LATEX_NO_LIB,
    LABEL_MATHML,
    LABEL_SCRIPT,
    EquationRender,
    render_equation,
)
from .layout_preview import LayoutPreview, PreviewPage, render_layout_preview
from .mathml import (
    MathMLUnavailableError,
    eqedit_latex_to_mathml,
    latex2mathml_available,
    latex_to_mathml,
)

__all__ = [
    "FIDELITY_BADGE",
    "LABEL_LATEX_ERROR",
    "LABEL_LATEX_NO_LIB",
    "LABEL_MATHML",
    "LABEL_SCRIPT",
    "DocumentViewer",
    "EquationRender",
    "LayoutPreview",
    "MathMLUnavailableError",
    "PreviewPage",
    "eqedit_latex_to_mathml",
    "latex2mathml_available",
    "latex_to_mathml",
    "render_document_viewer",
    "render_equation",
    "render_layout_preview",
]
