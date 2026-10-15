# SPDX-License-Identifier: Apache-2.0
"""Optional native preview runtime; importing this package loads no native stack."""
from __future__ import annotations

def render_bytes(data, out, **options):
    """Render supported HWPX using the explicitly installed native-preview extra."""
    from .render import render_bytes as render
    return render(data, out, **options)
