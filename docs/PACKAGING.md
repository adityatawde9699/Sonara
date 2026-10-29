# Packaging notes

> **Status: exploratory.** The Tauri configuration currently sets `bundle.active` to `false`. No installer, cross-platform artifact, or release workflow has been verified. The proposals below are not supported installation instructions.

## Current development layout

Sonara consists of:

1. React + TypeScript assets built into `ui-react/dist/`.
2. A Tauri 2 desktop shell in `src-tauri/`.
3. A Python worker for document processing and speech synthesis.
4. External or separately installed tools/models, including Poppler, Piper runtime/model assets, and optional OCR or AI components.

The current checkout is run from source; it relies on local Python, Rust, Node for frontend development, native platform libraries, and configured models. See [BUILDING.md](BUILDING.md).

## Work required before distribution

- Sonara's original project code and documentation use GPL-3.0-only. This does not grant redistribution rights to third-party runtimes, native tools, voice models, screenshot content, or other separately licensed assets.
- Inventory and preserve notices for Rust, Python, Node, native, and system dependencies.
- Review the Piper runtime license and each voice/model card separately. Do not infer model redistribution rights from runtime licensing or source-audio provenance.
- Decide how Python runtimes, native libraries, Poppler, Tesseract, and model files will be acquired or bundled for each target operating system.
- Verify update integrity, artifact signing/notarization, uninstall behavior, cache/data retention, and clean-machine installation.
- Build and manually test each target; a successful frontend or Rust test run is not evidence of a working installer.

## Release artifacts

No target formats are committed as supported. Do not advertise `.deb`, AppImage, `.dmg`, `.exe`, or `.msi` availability until a repeatable build and install test exists for the target platform and all licensing requirements are reviewed. See [the release checklist](RELEASE_PROCESS.md).
