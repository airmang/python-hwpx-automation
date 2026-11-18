#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Give the packaged design profiles' XML parts Hangul's XML declaration, once, on disk.

The four packaged profiles (``template.hwpx``, ``fragments.hwpx``) were saved by a python-hwpx that
wrote lxml's declaration (``<?xml version='1.0' encoding='utf-8'?>`` and a line break). python-hwpx
keeps a part's declaration as read when it writes the part again (#791), so a document composed from
a profile kept it. This rewrites only the XML parts of these files this repository ships (``.xml``
and ``.hpf`` entries whose first bytes are lxml's declaration), keeping every other entry's bytes,
the entry order, compression and the archive comment. A user's own profile is never touched: the
composer reads profiles as they are.

    python scripts/normalize_profile_declarations.py           # rewrite
    python scripts/normalize_profile_declarations.py --check   # exit 1 if a file would change
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "src" / "hwpx_automation" / "office" / "authoring" / "design" / "profiles"
HANGUL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
LXML = re.compile(rb"\A<\?xml version='1\.0'[^?]*\?>\s*")


def normalized(data: bytes) -> bytes | None:
    """*data* (a profile .hwpx) with Hangul declarations, or None when nothing changes."""

    changed = False
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename.endswith((".xml", ".hpf")):
                match = LXML.match(payload)
                if match is not None:
                    payload = HANGUL + payload[match.end():]
                    changed = True
            target.writestr(info, payload, compress_type=info.compress_type)
        target.comment = source.comment
    return out.getvalue() if changed else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pending = []
    for path in sorted(PROFILES.glob("*/*.hwpx")):
        data = normalized(path.read_bytes())
        if data is None:
            continue
        pending.append(path)
        if not args.check:
            path.write_bytes(data)
    for path in pending:
        print(("would rewrite " if args.check else "rewrote ") + str(path.relative_to(ROOT)))
    return 1 if args.check and pending else 0


if __name__ == "__main__":
    sys.exit(main())
