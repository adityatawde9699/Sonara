# Packaging notes

> **Status: packaging and smoke-check workflow implemented, but not yet run on hosted targets.** A Windows Tesseract security update, signing secrets, a successful CI run, and dependency license inventory still block a supported release.

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
- CI stages Poppler and Tesseract for each target OS, including Poppler data and English OCR data. It smoke-tests extraction, PDF rendering, and OCR before bundling, then installs resulting packages on separate hosted runners and tests resources and user-data retention.
- Windows Poppler and Tesseract downloads are pinned with SHA-256 values. The current Windows Tesseract installer is 5.5.3; upstream 5.5.4 was released with security fixes after this pin was selected. Treat Windows packages as blocked for publication until the staging source is updated and reviewed.
- `packaging/build_runtime.py` currently pins a CPU-oriented Python runtime build. GPU acceleration, model catalogs/downloads, default voice redistribution, and voice/model verification are not implemented.
- Windows signing and Apple Developer ID signing/notarization are configured through repository secrets. No signed/notarized release has been built yet. Publication requires all credentials and all clean-runner smoke checks to pass.
- License inventories and an SBOM remain release blockers. The current checks validate hosted CI runners, not every supported end-user system; validate on fresh VMs before declaring platform support.
- Build and manually test each target; a successful frontend or Rust test run is not evidence of a working installer.

## Release artifacts

The workflow targets `.deb`, AppImage, `.dmg`, and Windows NSIS `.exe` installers. Do not advertise them as supported until native jobs pass, the Windows OCR dependency is updated, and license requirements are reviewed. See [the release checklist](RELEASE_PROCESS.md).
