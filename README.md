# Sonara

Sonara is a local document-to-speech reader with a Python CLI and a Tauri 2 desktop app featuring an accessible React + TypeScript interface. The desktop app and CLI extract PDF, plain text (`.txt`/`.text`), Markdown (`.md`), Word (`.docx`), and e-book (`.epub`) files, then generate mapped WAV chunks with a local Piper TTS worker. Native document selection, speech synthesis lifecycle, real-time chunk progress, audio playback, passage navigation, speed adjustment, keyboard shortcuts, document history, and Rust-owned reading progress are implemented.

> **Project status:** Sonara is an actively developed prototype. The Tauri bundle is disabled, no tagged application releases are recorded, and cross-platform installers are not available. The repository currently has **no confirmed project license**; public source availability alone does not grant permission to reuse or redistribute it. See [license status](#license-status) before contributing code for redistribution or packaging.

## Screenshots

These are captures of the current application, not marketing mockups:

<p>
  <img src="Screenshots/Screenshot%20From%202026-10-29%2017-15-51.png" alt="Sonara desktop home screen in dark mode" width="720">
</p>

<p>
  <img src="Screenshots/Screenshot%20From%202026-10-29%2017-16-00.png" alt="Sonara desktop My Library view with search, favorites, and prepared documents" width="720">
</p>

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development setup](docs/DEVELOPMENT.md)
- [Build status and prerequisites](docs/BUILDING.md)
- [Configuration](docs/CONFIGURATION.md)
- [Testing and current evidence](docs/TESTING.md)
- [Privacy and data handling](docs/PRIVACY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Prerequisites

- Python with versions matching the available `piper-tts` and ONNX Runtime wheels. Python 3.14.4 is the environment tested for this baseline; other Python versions are not verified here.
- Poppler's `pdftotext` command. On Debian/Ubuntu: `sudo apt install poppler-utils`; verify with `pdftotext -v`.
- The local Piper voice model and adjacent JSON configuration in `models/piper/` (or an explicitly installed voice in another data directory). See [the model record](models/piper/README.md).
- For the desktop application: Rust stable/Cargo, GTK 3, WebKitGTK 4.1 development packages, Zenity or Kdialog for Linux's native document picker, and `gstreamer1.0-plugins-bad` for WebKitGTK media decoding. Rust crates are pinned and locked in `src-tauri/Cargo.lock`.

## Environment setup

Create an isolated environment and install the declared default Python dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

The app requires system Poppler separately; it is not a Python package. Sonara does not download voice files automatically. If obtaining a voice, use Piper's documented voice acquisition workflow, review its model card and terms, and verify the provenance before using or redistributing it.

## Read a Document

Sonara accepts PDF, plain text (`.txt`, `.text`), Markdown (`.md`), Word documents (`.docx`), and e-books (`.epub`):

```sh
.venv/bin/python sonara.py read ./document.pdf \
  --voice en_US-john-medium \
  --data-dir ./models/piper \
  --output-dir ./reading
```

Open `./reading/index.html` in a browser. The page offers play/pause, document-wide seeking across sentence chunks, a 0.7–1.5× speed slider, pause timing between chunks, retry/skip controls for failed chunks, and an attempt to save segment/time/rate in browser local storage. Generated chunk WAVs and `audio_chunks.json` are stored under `./reading`; the optional content-addressed synthesis cache is stored in `./.sonara-audio-cache` and pruned using a 512 MiB inactive-cache budget.

The default `--piper piper` path uses a persistent worker when `piper-tts` is installed in the active Python environment. It loads the selected model once per reading session and keeps document text out of process arguments. An explicit executable override (or PATH fallback when the Python package is absent) retains the compatible one-shot CLI path and passes text through a short-lived UTF-8 input file. Run `.venv/bin/python sonara.py read --help` for all options.

By default, the Python worker leaves Piper's `noise_scale` and `noise_w_scale` unset so each voice uses its own model configuration. `--variation less|more` applies a small experimental adjustment relative to those voice defaults; `voice_default` remains the default. These controls change generator noise and phoneme-width variation, not pitch or emotional acting. Compare them by listening before choosing a different default.

The narration planner preserves source text and source offsets while creating a separate spoken-text layer. English rules expand a conservative set of abbreviations and common units. ISO dates and numeric bracket citations remain unchanged unless enabled with `--expand-dates` or `--expand-citations`. In the desktop app, use **Preview narration** on a selected document to review the original and spoken versions before starting synthesis.

## Desktop application

The desktop application is a single-window Tauri 2 app with an accessible React + TypeScript frontend in `ui-react/`. It uses native file picking (Zenity with Kdialog fallback on Linux, AppleScript on macOS, PowerShell on Windows), starts the local Python Piper synthesis pipeline with real-time passage progress events, and stores generated audio plus versioned progress under Tauri's per-user local application data directory. For WebView media playback, Rust starts an ephemeral loopback HTTP listener bound only to `127.0.0.1`; a random per-launch token, exact Host check, active document hash/index, and canonical chunk-directory check restrict it strictly to generated passage WAVs. Byte ranges support seamless seeking. The frontend receives no arbitrary filesystem access.

The desktop app accepts **PDF, TXT/TEXT, Markdown (`.md`), Word (`.docx`), and EPUB** documents. Extraction and speech generation run locally with the Python document adapters and Piper.

Piper is the default, locally exercised engine. An optional Kokoro ONNX adapter is also implemented and exposed in the CLI and desktop UI, but it requires a separate compatible Python environment and model assets; Sonara does not download those assets automatically. The current development host has a Kokoro setup, but desktop playback and cross-platform packaging have not been verified. See [Kokoro setup](docs/KOKORO_SETUP.md) and the [roadmap evaluation status](docs/ROADMAP.md).

When a prepared desktop session is active, the listening workspace also shows its locally extracted text. The reading view supports paragraph-based paging, in-document search, and adjustable text size. It is limited to the active session: original document page layout, heading navigation, durable library reopening, and synchronized text/audio highlighting are not currently provided by the backend.

### Run the desktop app

1. Build the React frontend bundle:
   ```sh
   cd ui-react && npm run build && cd ..
   ```

2. Run the desktop application:
   ```sh
   cargo run --manifest-path src-tauri/Cargo.toml --locked
   ```

The application embeds the production frontend assets from `ui-react/dist/`, so ordinary development builds do not need an external frontend server. Optional assistant providers may make local or remote network requests according to the provider configuration; document extraction and ordinary local Piper narration do not require a remote service.

For frontend development with live hot-reloading:
```sh
cd ui-react && npm run dev
```

The default runtime expects `.venv/bin/python`, `sonara.py`, and `models/piper/en_US-john-medium.onnx` in this checkout. Override those locations with `SONARA_PROJECT_ROOT`, `SONARA_PYTHON`, and `SONARA_MODEL_DIR` when needed.

### Embedded llama.cpp assistant

Sonara can run a local GGUF directly through the optional `llama-cpp-python` runtime. It does not start or contact `llama-server`. Install the pinned optional dependency into the Python environment selected by `SONARA_PYTHON`:

```sh
.venv/bin/python -m pip install -r requirements-llm.txt
```

In **Settings → AI Assistant & Smart Narration**, choose **llama.cpp embedded**, browse to a readable `.gguf` model, and use **Test Connection**. That test loads the model and runs a short completion. The model is loaded lazily, reused by subsequent requests, and unloaded after the configured idle timeout (five minutes by default). Context size, CPU threads, batch size, temperature, token limit, and idle timeout are configurable there. `0` CPU threads delegates thread selection to llama.cpp; `0` idle timeout keeps the model until the app closes.

The legacy **llama.cpp server** provider remains an HTTP integration and still requires its configured local service. Existing `llama_cpp` settings are not migrated to embedded mode. Embedded chat does not assume that its generation model provides embeddings: without vector retrieval configured, Sonara passes a bounded document excerpt directly to the model. No model weights are downloaded or bundled; review model and runtime licenses before redistribution. The optional native binding and app bundle have not been validated across Windows, macOS, and Linux.

## Performance Benchmarks & Packaging

- **Performance Benchmarks**: See [Benchmark Report](docs/BENCHMARKS.md) for multi-voice latency, Time to First Audio (TTFA), and Real-Time Factor (RTF) figures on CPU execution.
- **Packaging:** [Packaging notes](docs/PACKAGING.md) describe exploratory options only. The Tauri bundle is currently disabled; no installer workflow is verified.

```sh
# Benchmark single voice
.venv/bin/python benchmark.py --voice en_US-john-medium

# Benchmark all installed voices
.venv/bin/python benchmark.py --all
```

## Tests

Frontend checks from `ui-react/`:

```sh
npm test
npm run build
npm run lint
```

Fast tests do not load a model or require Poppler:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The opt-in integration suite generates its own PDFs and compares structured Poppler output to the existing `-layout` text extraction. It tests the real PDF-to-CLI path, direct Piper Python API chunk generation and source mapping, cancellation, and corrupt-model errors using only the existing local model. Generated fixture/output files live inside temporary directories:

```sh
SONARA_RUN_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -p 'test_integration_*.py' -v
```

See [testing instructions and current evidence](docs/TESTING.md). Node.js syntax-checks the generated player script when available, but this is not browser playback verification.

## Current limitations

- Searchable PDF text is extracted directly via Poppler. Scanned PDFs are supported via pluggable Tesseract OCR (`ocr.py`) with `pdftoppm` rendering, coordinate translation, and disk caching when `tesseract-ocr` is installed on the host system.
- The canonical extracted representation retains page, block, and bounding-box locations. Headings/list labels are visual/text heuristics; tables remain text blocks, and complex columns can require review. A machine-readable document schema exists in code but is not yet a persisted UI format.
- Narration boundaries are deterministic heuristics with a finite English abbreviation list. Equations, citations, code, unusual abbreviations, and non-English punctuation may need review.
- Date and numeric citation expansions are opt-in; the current English abbreviation/unit rules are conservative and do not alter source documents. A preview is available in the desktop interface and with `sonara.py read --preview`.
- The CLI generates the complete document before the HTML player is opened; playback then loads one persisted sentence WAV at a time. Pause/resume, cross-chunk seeking, speed, pause timing, per-document segment/time progress, and retry/skip UI are implemented in the player, but actual browser behavior and progress persistence remain unverified. Pausing browser playback does not cancel or pause synthesis because synthesis completes first.
- Piper advertises speed control only. It does not provide the current adapter with emotion or phrase-emphasis controls, diarization, or GPU selection. The explicit executable override remains one-shot.
- Optional WAV caching is enabled by the default CLI, with LRU cleanup of inactive content-addressed WAVs at a 512 MiB budget; entries for the active synthesis plan are protected and can temporarily exceed it.
- A blinded listening-pack generator is available as `.venv/bin/python listening_eval.py --voice en_US-john-medium --output-dir /tmp/sonara-listening-evaluation`. It generates randomized, RMS-level-matched samples for voice-default/less/more variation and separates participant sheets from the facilitator key. A pack was generated successfully, but no human listening result is claimed until participants rate the samples.
- The Tauri UI has compiled but has not been opened interactively here: GTK initialization fails because this environment has no usable display. The earlier generated HTML player also remains without browser verification. Historical performance benchmark results are documented separately; they are not human listening results.
- The installed model and config have recorded hashes and upstream revision; runtime, model, phonemizer, and application licensing must be assessed separately before distribution.
- This repository has no tagged application releases in the current history. Build and test evidence is recorded in [docs/TESTING.md](docs/TESTING.md); see the dated entries there for environment-specific limitations.

Sonara has a desktop development prototype, not a distributable desktop release. See [the roadmap](docs/ROADMAP.md) for the staged plan.

## License status

No root `LICENSE` file or confirmed project license is present. Do not infer a license from dependency licenses, the public GitHub repository, or an old packaging note. The maintainer must choose a license and add its required text before describing Sonara itself as open source or authorizing redistribution. Third-party dependencies, native tools, and voice models have separate terms.

## Community

- [Report a bug or propose a feature](https://github.com/adityatawde9699/Sonara/issues)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Security reporting](SECURITY.md)
- [Repository](https://github.com/adityatawde9699/Sonara)

No release download link is shown because no published application release has been verified.
