# SPDX-License-Identifier: Apache-2.0
"""Process-wide serialization for public document mutations."""

from __future__ import annotations

import threading


# FastMCP can execute independent tool calls concurrently.  Every catalog entry
# marked ``mutates`` shares this re-entrant lock so a verifier/rollback window
# cannot race another public writer in the same server process.
PUBLIC_MUTATION_LOCK = threading.RLock()


__all__ = ["PUBLIC_MUTATION_LOCK"]
