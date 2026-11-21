#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Disabled legacy release helper.

The former implementation treated ``hwpx-mcp-server`` as the application
identity and could not atomically update the canonical automation package, its
6.x compatibility shell, exact extras, product identity, and four host bundles.
Git history retains that implementation; keeping mutation code in an
"unreachable" branch would make accidental re-enablement too easy.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "release_stack.py is disabled for the unpublished 5.0/6.0/1.0 "
        "candidate: use the reviewed manifest-driven release checklist; "
        "no release action was performed.",
        file=sys.stderr,
    )
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
