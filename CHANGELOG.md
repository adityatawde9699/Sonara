# Changelog

This file records notable user-facing changes. The `v1.0.0` GitHub release exists but has no installer assets. Historical implementation notes and validation evidence remain in `docs/TESTING.md` and `docs/ROADMAP.md`.

## v1.0.1 - 2026-10-30

### Added

- Added native GitHub Actions packaging, installed-app smoke checks, and release asset publishing for supported Windows, Linux, and macOS targets.
- Added automatic operating-system and architecture detection, manual platform selection, and latest-release asset lookup to the marketing site's download section.

### Fixed

- Prepared the Tauri resource directory during Rust CI so tests work from a clean checkout.

## Unreleased

### Changed

- Added bounded ZIP-member and expanded-text limits for DOCX and EPUB extraction.
- Removed unused remote Google Fonts origins from the desktop Content Security Policy.
- Changed the license for Sonara's original project code and documentation to GPL-3.0-only.
- Added a GitHub Pages workflow that publishes the independent `site/` directory.
- Made the OCR page-count test independent of whether Poppler's `pdfinfo` is installed and prepared Python for Rust worker tests in CI.
- Added contributor, support, security, development, configuration, privacy, testing, and release guidance.

When preparing a release, summarize shipped changes here under the actual version and date. Do not treat this unreleased section as a published release.
