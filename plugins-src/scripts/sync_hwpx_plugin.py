from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SKILL = ROOT / "plugins" / "hwpx-plugin" / "skills" / "hwpx"
SYNC_MANIFEST = ROOT / "plugins" / "hwpx-plugin" / "plugin-sync.json"

SYNC_FILES = [
    "SKILL.md",
    "README.md",
    "references/api.md",
    "examples/01_create_and_save.py",
    "examples/02_extract_and_inspect.py",
    "examples/03_template_replace.py",
    "examples/04_create_proposal.py",
    "examples/05_mcp_quality_pipeline.md",
    "examples/06_create_from_document_plan.py",
    "examples/06_mcp_document_plan.md",
    "examples/07_create_operating_plan.py",
    "examples/07_mcp_operating_plan.md",
    "examples/08_template_formfit.py",
    "examples/08_mcp_template_formfit.md",
    "examples/09_visual_review_loop.md",
    "scripts/fix_namespaces.py",
    "scripts/quickcheck.py",
    "scripts/text_extract.py",
    "scripts/visual_review.py",
    "scripts/zip_replace_all.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def destination_for(source: str) -> Path:
    if source == "SKILL.md":
        return PLUGIN_SKILL / "SKILL.md"
    return PLUGIN_SKILL / source


def main() -> int:
    missing = [source for source in SYNC_FILES if not (ROOT / source).is_file()]
    if missing:
        missing_list = ", ".join(missing)
        raise SystemExit(f"missing sync source file(s): {missing_list}")

    records = []
    for source in SYNC_FILES:
        source_path = ROOT / source
        destination_path = destination_for(source)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        records.append(
            {
                "source": source,
                "destination": str(destination_path.relative_to(ROOT)),
                "sha256": sha256(source_path),
            }
        )

    SYNC_MANIFEST.write_text(
        json.dumps(
            {
                "schemaVersion": "hwpx.plugin-sync.v1",
                "plugin": "hwpx-plugin",
                "sourceRoot": ".",
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[OK] synced {len(SYNC_FILES)} files into plugins/hwpx-plugin/skills/hwpx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
