# SPDX-License-Identifier: Apache-2.0
"""Run ``python -m hwpx_automation.office.rendering render-pdf IN OUT``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
