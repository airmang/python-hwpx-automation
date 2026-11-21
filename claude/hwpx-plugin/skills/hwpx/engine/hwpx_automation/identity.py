# SPDX-License-Identifier: Apache-2.0
"""Load the installed product-identity contract."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def product_identity() -> dict[str, Any]:
    """Return a detached copy of the installed identity manifest."""

    resource = files("hwpx_automation").joinpath("identity.json")
    return json.loads(resource.read_text(encoding="utf-8"))


__all__ = ["product_identity"]
