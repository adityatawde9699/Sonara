# Changelog

This file records notable user-facing changes. The repository has no tagged releases as of 2026-10-29, so there are no published version entries to reproduce here. Historical implementation notes and validation evidence remain in `docs/TESTING.md` and `docs/ROADMAP.md`.

## Unreleased

### Changed

- Added bounded ZIP-member and expanded-text limits for DOCX and EPUB extraction.
- Removed unused remote Google Fonts origins from the desktop Content Security Policy.
- Changed the license for Sonara's original project code and documentation to GPL-3.0-only.
- Added a GitHub Pages workflow that publishes the independent `site/` directory.
- Made the OCR page-count test independent of whether Poppler's `pdfinfo` is installed and prepared Python for Rust worker tests in CI.
- Added contributor, support, security, development, configuration, privacy, testing, and release guidance.

When preparing a release, summarize shipped changes here under the actual version and date. Do not treat this unreleased section as a published release.
