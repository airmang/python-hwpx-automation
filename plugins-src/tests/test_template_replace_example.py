# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples" / "03_template_replace.py"
spec = importlib.util.spec_from_file_location("template_replace_example", SPEC)
template_replace_example = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(template_replace_example)


def test_template_replace_example_preserves_existing_output_when_fix_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.hwpx"
    output = tmp_path / "output.hwpx"
    source.write_bytes(b"input placeholder archive")
    output.write_bytes(b"existing output")

    def fake_zip_replace_all(_source: str, temp_path: str, _replacements: dict[str, str]) -> dict[str, int]:
        Path(temp_path).write_bytes(b"intermediate output")
        return {"replacements": 1}

    def fail_fix_namespaces(_source: str, _output: str) -> dict[str, int]:
        raise RuntimeError("forced namespace failure")

    monkeypatch.setattr(template_replace_example, "zip_replace_all", fake_zip_replace_all)
    monkeypatch.setattr(template_replace_example, "fix_namespaces", fail_fix_namespaces)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "03_template_replace.py",
            str(source),
            str(output),
            "--replace",
            "OLD=NEW",
        ],
    )

    try:
        template_replace_example.main()
    except RuntimeError as exc:
        assert "forced namespace failure" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("template replace example should propagate failed validation")

    assert output.read_bytes() == b"existing output"
    assert not list(tmp_path.glob("hwpx-example-*.hwpx"))
