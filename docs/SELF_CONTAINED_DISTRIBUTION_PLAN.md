# Self-contained desktop distribution plan

**Objective:** ship installable Sonara builds for Windows, Linux, and macOS that do not need a source checkout or developer toolchain, while keeping documents and inference local by default.

**Evidence baseline (2026-10-30):** source checkout inspected; no platform release artifacts or installer CI found. The user reports that all supported document formats, narration vocals, and the assistant work as intended in their desktop use. That is user-reported functional feedback, not clean-machine packaging evidence.

## Repository gaps found

- `src-tauri/tauri.conf.json` sets `bundle.active` to `false`; there is no release packaging workflow.
- `resolve_runtime()` in `src-tauri/src/lib.rs` derives the project root from `CARGO_MANIFEST_DIR`, defaults to `.venv/bin/python`, and assumes `sonara.py` plus `models/piper` under a checkout. This is Linux/development-layout-specific and cannot locate a Windows or installed app runtime.
- Rust launches Python scripts by path. `tts_engine.py` launches `piper_worker.py` via `sys.executable`; embedded LLM startup launches `llm_client.py worker`. A packaged runtime must preserve these worker lifecycles and stdout protocols.
- PDF extraction requires the external `pdftotext` executable; scanned-PDF OCR additionally requires `pdftoppm` and Tesseract. Native file pickers also rely on platform facilities.
- `requirements.txt` includes Piper and ONNX Runtime only. Kokoro and `llama-cpp-python` are optional/unbundled, and a compatible, model-backed embedded LLM runtime is not currently present in the tracked environment.
- Voice and model discovery exist, but there is no verified model catalog/download/install/update/remove workflow. There is no integrity-checked asset manager, and model files are not bundled by a release pipeline.
- Third-party licenses and redistribution rights for all binaries, native libraries, runtimes, voices, and models have not been inventoried or cleared for redistribution.
- App-local reading progress already uses Tauri's per-user data directory. Packaging work must keep that data outside install locations and preserve it during upgrades/uninstall by default.

## Phases and exit evidence

### Phase 0 — Audit and packaging contract

**Status: complete.** Inventory existing entry points, resource assumptions, optional inference paths, document tools, persistence, CI, and release gaps. Keep user-reported desktop acceptance separate from automated or clean-install evidence.

### Phase 1 — Relocatable runtime and resource discovery

**Status: partially implemented.** Tauri resource discovery now resolves a `resources/sonara` layout with a per-user writable model directory; development overrides remain available. A PyInstaller builder and frozen dispatch entry points cover Sonara, LLM, Piper worker, and Piper's `-m` invocation. Unit tests cover dispatch and the Rust resource-layout helper. The runtime builder has not been exercised, and Poppler is not staged yet; corrupt runtime detection and clean-machine launch/extraction remain open.

**Exit evidence:** packaged app launches from an unrelated working directory with no system Python or source checkout; extraction and Piper worker complete a smoke document on each CI target.

### Phase 2 — Verified model and voice manager

**Status: not started.** Add a versioned, reviewable catalog containing publisher/source, engine compatibility, language, exact size, SHA-256, license/provenance, and memory estimate. Add explicit download/install/update/remove operations using temporary files, size and hash verification, atomic promotion, progress events, cancellation, safe cleanup, and partial-file resume only when server range/ETag behavior is validated. Store settings and user assets in app-local data. Never execute downloaded model files.

**Exit evidence:** tests cover malformed catalog entries, path traversal, bad hashes, short/oversized responses, cancellation, resume mismatch, install atomicity, and preservation of existing installed assets after a failed update.

### Phase 3 — Self-contained CPU inference baseline

**Status: not started.** Select a supported Python version that intersects Piper, Kokoro, and llama-cpp-python requirements; build per-platform CPU runtimes on native CI runners. Include Python packages and native libraries. Include Poppler executables and runtime dependencies. Include a Piper voice only after artifact and full dependency redistribution review; otherwise provide a first-run guided voice setup. Keep accelerator support optional and report a clear CPU fallback/error when no compatible provider exists.

**Exit evidence:** clean-machine tests run every supported file format, Piper narration, Kokoro when its assets are installed, embedded GGUF inference with a small approved test model, missing accelerator/model errors, cancellation, and data-preserving upgrade/uninstall checks.

### Phase 4 — Installers and automated release builds

**Status: scaffolded, unverified.** Tauri bundle targets and a native CI workflow request Windows NSIS, Linux `.deb`/AppImage, and macOS `.dmg` artifacts. Jobs upload unsigned artifacts for inspection. They do not stage all runtime resources, and have not been run on target runners. Checksums, SBOM/license inventory, signing, notarization, and release publishing are still open.

**Exit evidence:** repeatable tagged build; artifact inspection; clean installation, upgrade, launch, and uninstall checks on fresh supported OS images; persistent user data survives upgrades and is not silently deleted on uninstall.

### Phase 5 — Distribution readiness and support docs

**Status: not started.** Finish legal review for every shipped item and catalog asset; publish platform prerequisites, supported architectures, model download/license guidance, privacy behavior, uninstall/data-retention behavior, and recovery steps. Review logs and local service boundaries; do not expose arbitrary file access or execute downloaded model assets.

**Exit evidence:** signed-off notices/SBOM, release checklist, reproducible build instructions, documented supported platform matrix, and a maintainer-approved release candidate.

## Constraints and risk policy

- Prefer CPU inference as the dependable baseline; GPU libraries are per-platform optional acceleration and never a hidden requirement.
- Treat voices and weights as independent licensed assets. A source dataset or runtime license alone does not establish redistribution permission for a derived model.
- Keep cloud/remote assistant behavior opt-in and disclose that configured providers receive request context.
- Do not advertise an installer or mark a platform supported until its native artifact is installed and exercised on a clean environment.
