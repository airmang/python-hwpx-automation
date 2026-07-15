# Contributing

This repository generates four host bundles from one canonical source. Edit the
root skill, references, examples, packaging templates, or host manifest; do not
hand-edit generated files under `plugins/`.

With sibling `python-hwpx` and `hwpx-mcp-server` checkouts available, run:

```bash
python scripts/build_hwpx_plugins.py
python scripts/validate_hwpx_plugin.py
python scripts/check_public_hygiene.py
ruff check --select E9,F .
pytest -q
git diff --exit-code
```

Contract changes must be regenerated and validated across all four hosts. Never
commit local virtual environments, private benchmark routing, real user documents,
credentials, workstation paths, generated evidence, or output documents. Keep
fixtures synthetic and repository-only unless they are explicitly part of the
installed product. Report vulnerabilities through [SECURITY.md](SECURITY.md).
