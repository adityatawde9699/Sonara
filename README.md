# Sonara

Sonara is a local document-to-speech reader with a Python CLI and a Tauri 2 desktop app featuring an accessible React + TypeScript interface. The desktop app and CLI extract PDF, plain text (`.txt`/`.text`), Markdown (`.md`), Word (`.docx`), and e-book (`.epub`) files, then generate mapped WAV chunks with a local Piper TTS worker. Native document selection, speech synthesis lifecycle, real-time chunk progress, audio playback, passage navigation, speed adjustment, keyboard shortcuts, document history, and Rust-owned reading progress are implemented.

> **Project status:** Sonara is an actively developed prototype. Tags `v1.0.0` and `v1.0.1` exist as GitHub releases, but neither has installer assets: the release workflow has not yet completed a run. Native installers are configured for Linux and macOS first; Windows packaging is blocked (see [Release process](docs/RELEASE_PROCESS.md)). Sonara-authored source code and documentation in this repository are licensed under [GPL-3.0-only](LICENSE). Third-party dependencies, runtimes, models, fonts, and media retain their own licenses.

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

The app requires system Poppler separately; it is not a Python package. Installers ship without voice models. In the desktop app, Settings → Speech models downloads the supported Piper voices and Kokoro on request, over HTTPS, and installs a file only after its pinned SHA-256 matches (see [privacy](docs/PRIVACY.md#model-downloads)). Nothing is downloaded without that button press. For other voices, use Piper's documented voice acquisition workflow, review its model card and terms, and verify the provenance before using or redistributing it.

## Read a Document

Sonara accepts PDF, plain text (`.txt`, `.text`), Markdown (`.md`), Word documents (`.docx`), and e-books (`.epub`):

```sh
.venv/bin/python sonara.py read ./document.pdf \
  --voice en_US-john-medium \
  --data-dir ./models/piper \
  --output-dir ./reading
```

The CLI writes one WAV per passage under `./reading/chunks/`, the combined `./reading/speech.wav` (skip it with `--no-combined-audio`), and `./reading/audio_chunks.json`, which maps each passage to its source text, pause and duration. To listen with read-along highlighting and saved progress, open the document in the desktop app. Sonara 2.0 removed the CLI's standalone browser player. The content-addressed synthesis cache is stored in `./reading/.sonara-audio-cache` (override with `--cache-dir`) and pruned using a 512 MiB inactive-cache budget.

The default `--piper piper` path uses a persistent worker when `piper-tts` is installed in the active Python environment. It loads the selected model once per reading session and keeps document text out of process arguments. An explicit executable override (or PATH fallback when the Python package is absent) retains the compatible one-shot CLI path and passes text through a short-lived UTF-8 input file. Run `.venv/bin/python sonara.py read --help` for all options.

By default, the Python worker leaves Piper's `noise_scale` and `noise_w_scale` unset so each voice uses its own model configuration. `--variation less|more` applies a small experimental adjustment relative to those voice defaults; `voice_default` remains the default. These controls change generator noise and phoneme-width variation, not pitch or emotional acting. Compare them by listening before choosing a different default.

The narration planner preserves source text and source offsets while creating a separate spoken-text layer. English rules fix readings the voice would otherwise get wrong. These cover titles and reference abbreviations ("Dr.", "Fig. 3", "pp. 10–12"), units, currency, years and decades in context, times, fractions, Roman numerals after words such as "Chapter", and a small lexicon of technical terms. ISO dates and numeric bracket citations remain unchanged unless enabled with `--expand-dates` or `--expand-citations`. In the desktop app, use **Preview narration** on a selected document to review the original and spoken versions before starting synthesis.

## Desktop application

The desktop application is a single-window Tauri 2 app with an accessible React + TypeScript frontend in `ui-react/`. It uses native file picking (Zenity with Kdialog fallback on Linux, AppleScript on macOS, PowerShell on Windows), starts the local Python Piper synthesis pipeline with real-time passage progress events, and stores generated audio plus versioned progress under Tauri's per-user local application data directory. For WebView media playback, Rust starts an ephemeral loopback HTTP listener bound only to `127.0.0.1`; a random per-launch token, exact Host check, active document hash/index, and canonical chunk-directory check restrict it strictly to generated passage WAVs. Byte ranges support seamless seeking. The frontend receives no arbitrary filesystem access.

The desktop app accepts **PDF, TXT/TEXT, Markdown (`.md`), Word (`.docx`), and EPUB** documents. Extraction and speech generation run locally with the Python document adapters and Piper.

Piper is the default, locally exercised engine. An optional Kokoro ONNX adapter is also implemented and exposed in the CLI and desktop UI, but it requires a separate compatible Python environment and model assets; Sonara does not download those assets automatically. The current development host has a Kokoro setup, but desktop playback and cross-platform packaging have not been verified. See [Kokoro setup](docs/KOKORO_SETUP.md) and the [roadmap evaluation status](docs/ROADMAP.md).

Kokoro voices cover US and British English, Spanish, French, Hindi, Italian, Brazilian Portuguese and (experimental) Mandarin; the chosen voice sets the language. Japanese Kokoro voices are not offered. English normalization rules (dates, units, abbreviations) apply only to English voices; other languages are spoken as written.

When a prepared desktop session is active, the reading view shows its locally extracted text and highlights the passage being spoken. It follows playback across pages until you turn a page yourself. Each paragraph has a button that starts listening there. Highlighting is per passage (a sentence or a few sentences), not per word, because neither engine reports word timings to Sonara. The view also has in-document search and adjustable text size. It does not reproduce the original page layout or offer heading navigation.

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

The default runtime expects `.venv/bin/python`, `sonara.py`, and a Piper voice in `models/piper/` in this checkout (the desktop default is `en_US-ryan-medium`). Override those locations with `SONARA_PROJECT_ROOT`, `SONARA_PYTHON`, and `SONARA_MODEL_DIR` when needed.

### Embedded llama.cpp assistant

Sonara can run a local GGUF directly through the optional `llama-cpp-python` runtime. It does not start or contact `llama-server`. Install the pinned optional dependency into the Python environment selected by `SONARA_PYTHON`, in two steps:

```sh
.venv/bin/python -m pip install -r requirements-llm.txt
.venv/bin/python -m pip install --no-deps -r requirements-llm-nodeps.txt
```

The second step uses `--no-deps` on purpose. llama-cpp-python declares a dependency on `diskcache`, and every diskcache release unpickles its cache files (CVE-2025-69872); there is no fixed version. Sonara never uses a llama.cpp disk cache, so diskcache is not installed. `llama_runtime.py` gives llama.cpp a disabled stand-in that refuses to create a disk cache. If an older install left diskcache behind, remove it with `.venv/bin/python -m pip uninstall diskcache`.

In **Settings → AI Assistant**, choose **llama.cpp embedded**, browse to a readable `.gguf` model, and use **Test Connection**. That test loads the model and runs a short completion. The model is loaded lazily, reused by subsequent requests, and unloaded after the configured idle timeout (five minutes by default). Context size, CPU threads, batch size, temperature, token limit, and idle timeout are configurable there. `0` CPU threads delegates thread selection to llama.cpp; `0` idle timeout keeps the model until the app closes.

The **llama.cpp server** provider talks to an OpenAI-compatible `llama-server` over loopback HTTP. Sonara can run that server for you with the GGUF you choose ("Let Sonara run llama-server" in Settings); `llama-server` itself is not bundled. Assistant answers cite the passages they use, and each citation opens the reading view at that passage. Existing `llama_cpp` settings are not migrated to embedded mode. Embedded chat does not assume that its generation model provides embeddings: without vector retrieval configured, Sonara passes a bounded document excerpt directly to the model. No model weights are downloaded or bundled; review model and runtime licenses before redistribution. The optional native binding and app bundle have not been validated across Windows, macOS, and Linux.

## Performance Benchmarks & Packaging

- **Performance Benchmarks**: See [Benchmark Report](docs/BENCHMARKS.md) for multi-voice latency, Time to First Audio (TTFA), and Real-Time Factor (RTF) figures on CPU execution.
- **Packaging:** The Tauri bundle is enabled and `.github/workflows/package.yml` builds, smoke-tests, and publishes installers. It has not yet completed a successful run, so no installer has been published. See [Packaging notes](docs/PACKAGING.md) and [Release process](docs/RELEASE_PROCESS.md).

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
- The CLI synthesizes and exports audio only; listening, seeking, speed and saved progress are in the desktop app.
- Piper advertises speed control only. It does not provide the current adapter with emotion or phrase-emphasis controls, diarization, or GPU selection. The explicit executable override remains one-shot.
- Optional WAV caching is enabled by the default CLI, with LRU cleanup of inactive content-addressed WAVs at a 512 MiB budget; entries for the active synthesis plan are protected and can temporarily exceed it.
- A blinded listening-pack generator is available as `.venv/bin/python listening_eval.py --voice en_US-john-medium --output-dir /tmp/sonara-listening-evaluation`. It generates randomized, RMS-level-matched samples for voice-default/less/more variation and separates participant sheets from the facilitator key. A pack was generated successfully, but no human listening result is claimed until participants rate the samples.
- The Tauri UI has compiled but has not been opened interactively here: GTK initialization fails because this environment has no usable display. Historical performance benchmark results are documented separately; they are not human listening results.
- The installed model and config have recorded hashes and upstream revision; runtime, model, phonemizer, and application licensing must be assessed separately before distribution.
- Tags `v1.0.0` and `v1.0.1` exist but their GitHub releases have no installer assets. Build and test evidence is recorded in [docs/TESTING.md](docs/TESTING.md); see the dated entries there for environment-specific limitations.

Sonara has a desktop development prototype, not a distributable desktop release. See [the roadmap](docs/ROADMAP.md) for the staged plan.

## License status

Sonara-authored source code and documentation in this repository are licensed under the [GNU General Public License version 3 only](LICENSE) (SPDX: `GPL-3.0-only`), without the “or later” option. This covers Sonara's own work; it does not change the licenses for third-party dependencies, runtimes, system tools, voice models, fonts, media, or separately owned material that may appear in screenshots. Check the relevant notices and terms before bundling or redistributing those components. The Rust package metadata uses the same `GPL-3.0-only` identifier.

## Community

- [Report a bug or propose a feature](https://github.com/adityatawde9699/Sonara/issues)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Security reporting](SECURITY.md)
- [Marketing site and GitHub Pages deployment](site/README.md)
- [Repository](https://github.com/adityatawde9699/Sonara)

No release download link is shown because no installer has been published yet.
