# Development setup

Sonara currently consists of a Python document/narration pipeline, a React + TypeScript frontend, and a Rust/Tauri desktop shell. This guide describes the repository checkout workflow; it is not an end-user installer guide.

## Prerequisites

- Python 3.14 is the recorded baseline for the current direct dependencies. Other Python versions have not been verified in the repository evidence. The Python requirements pin direct packages but do not lock the full transitive environment.
- Node.js 24 and npm for `ui-react`.
- Rust 1.90 or newer compatible with `src-tauri/Cargo.toml` and Cargo for desktop work.
- Poppler (`pdftotext`) for PDF extraction. Scanned-PDF OCR additionally needs `pdftoppm` and Tesseract.
- Linux desktop builds require Tauri's GTK 3 and WebKitGTK 4.1 development libraries; native file selection also uses Zenity with KDialog fallback.
- A local Piper model and matching JSON configuration are needed for real synthesis. Do not commit model weights.

See [BUILDING.md](BUILDING.md) for platform-specific caveats and [the model record](../models/piper/README.md) for recorded provenance and checksums.

## Set up Python

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

Optional embedded llama.cpp support is separate and may require native compilation:

```sh
.venv/bin/python -m pip install -r requirements-llm.txt
```

Do not install this optional dependency unless you need the embedded GGUF provider. Kokoro has a separate setup path; consult [Kokoro setup](KOKORO_SETUP.md) and verify its runtime prerequisites against your checkout.

## Run the desktop app

Build frontend assets, then run Tauri:

```sh
cd ui-react
npm ci
npm run dev
```

The Vite server is useful for frontend-only development. The current Tauri configuration embeds `ui-react/dist/` and does not declare a Tauri `devUrl`; for a desktop run, build the frontend and then start the shell:

```sh
cd ui-react && npm run build
cd ..
cargo run --manifest-path src-tauri/Cargo.toml --locked
```

The Tauri runtime defaults to `.venv/bin/python`, the checkout root, and `models/piper`; see [configuration](CONFIGURATION.md) for overrides. Interactive Tauri development requires a usable desktop display and system WebView libraries.

## Useful checks

```sh
python -m compileall -q benchmark.py document.py listening_eval.py llm_client.py narration.py ocr.py piper_worker.py resource_policy.py sonara.py tts_engine.py tests
.venv/bin/python -m unittest discover -s tests -v
cd ui-react && npm test && npm run lint && npm run build
cd ..
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo test --manifest-path src-tauri/Cargo.toml --locked --offline
```

The full test matrix and opt-in model-backed tests are documented in [TESTING.md](TESTING.md). Optional tests requiring local models or external tools are not ordinary CI prerequisites.
