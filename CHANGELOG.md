# Changelog

This file records notable user-facing changes. The `v1.0.0` GitHub release exists but has no installer assets. Historical implementation notes and validation evidence remain in `docs/TESTING.md` and `docs/ROADMAP.md`.

## v1.0.1 - 2026-10-30

### Added

- Added native GitHub Actions packaging, installed-app smoke checks, and release asset publishing for supported Windows, Linux, and macOS targets.
- Added automatic operating-system and architecture detection, manual platform selection, and latest-release asset lookup to the marketing site's download section.

### Fixed

- Prepared the Tauri resource directory during Rust CI so tests work from a clean checkout.

## Unreleased

### Security

- `get_document_text` no longer accepts a file path from the frontend; it reads only the selected document or Sonara's own output, capped at 16 MiB.
- LLM HTTP providers require `https` (plain `http` only to localhost), reject unknown providers, and do not follow redirects.
- The OCR cache moved from a shared temp directory to a private per-user directory, with symlink-safe atomic writes.
- Release signing secrets are scoped to the steps that sign; the Windows PFX password is no longer passed on the `signtool` command line.
- Updated `plist`/`quick-xml`, `time`, and `tokio` in `Cargo.lock` to clear RustSec advisories.
- Removed `diskcache` (CVE-2025-69872 / PYSEC-2026-2447: unsafe pickle loading, no fixed release) from every install path instead of ignoring the advisory. llama-cpp-python is installed with `--no-deps` and its other dependencies are pinned directly. `llama_runtime.py` supplies a disabled stand-in, so a llama.cpp disk cache can never be created. The release build fails if diskcache is present, and the packaged runtime's self-check fails if it is bundled.

### Fixed

- Remote LLM providers can authenticate from the Assistant; the API key is shared in memory with Settings and still never persisted.
- Scanned PDFs are OCRed page by page in packaged builds instead of silently reading only page 1 (`pdfinfo` is not bundled).
- Sentence splitting is linear time; an 80 KB paragraph took about 20 s and now takes 0.03 s.
- An unresponsive LLM worker is stopped after 300 s, and closing the app no longer waits on an in-flight request.
- Keyboard shortcuts ignore Ctrl/Cmd/Alt combinations and focused controls, and do not fire behind open dialogs. Dialogs trap focus, restore it on close, and Escape closes only the topmost one.

### Changed

- Narration reads more text correctly (ruleset `rules-6`):
  - Titles and reference abbreviations ("Dr.", "St.", "Fig. 3", "pp. 10-12", "Jan. 5") no longer make the voice pause mid-sentence.
  - Years and decades are read as years ("the 1990s" was "one thousand nine hundred ninety seconds"), and "ranked 3 in" is no longer "three inches".
  - Currency, times, number and year ranges, fractions, Roman numerals after "Chapter"/"World War"/regnal names, and a small technical-term lexicon are now spoken.
  - Previously generated audio and saved progress are invalidated.
- Synthesized audio is finished before playback. Edge silence is trimmed, speech level is matched across voices (−18 dBFS, peaks capped at −1 dBFS; raw Piper audio peaked at full scale), and chunks fade in and out.
- Pauses and the `less`/`more` variation presets are tuned per voice from measurements (`docs/BENCHMARKS.md` §6). Slower voices get proportionally longer pauses. The exported `speech.wav` now contains the planned pauses between passages.
- OCR is bounded to 500 pages and 30 minutes per document, and oversized pages are rendered at reduced resolution.
- CI runs Python on 3.12 and 3.14, `cargo clippy -D warnings`, and npm/pip/cargo dependency audits. GitHub Actions are pinned to commit SHAs.
- The release workflow defaults to Linux and macOS (`unix`), builds the named tag, and writes per-target checksum files.

- Added bounded ZIP-member and expanded-text limits for DOCX and EPUB extraction.
- Removed unused remote Google Fonts origins from the desktop Content Security Policy.
- Changed the license for Sonara's original project code and documentation to GPL-3.0-only.
- Added a GitHub Pages workflow that publishes the independent `site/` directory.
- Made the OCR page-count test independent of whether Poppler's `pdfinfo` is installed and prepared Python for Rust worker tests in CI.
- Added contributor, support, security, development, configuration, privacy, testing, and release guidance.

When preparing a release, summarize shipped changes here under the actual version and date. Do not treat this unreleased section as a published release.
