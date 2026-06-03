# Changelog

## [Unreleased]

## [0.1.1] - 2026-06-04
### Fixed
- Remove stale HWPX `lineSegArray` layout caches from XML parts changed by `zip_replace_all.py` so Hancom recalculates text layout after replacements.
- Pin bundled MCP fallback launchers and MCP install docs to `hwpx-mcp-server==2.3.1`, which includes cross-run replacement fixes for overlapping glyphs.

### Changed
- Bump packaged plugin manifests and Codex marketplace entry to `0.1.1`.

## [0.1.0]
### Added
- Added `hwpx.builder` onboarding docs, API reference, example, and quickcheck coverage for the S-013 builder core.

### Changed
- Updated bundled MCP fallback launchers to `hwpx-mcp-server==2.3.0`, which requires `python-hwpx>=2.10.0`.
- License relicensed to Apache-2.0 (sole author, full consent).
- Previous license terms no longer apply to future releases.
