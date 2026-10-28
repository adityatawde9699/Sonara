# Technology decisions

## Validated starting points

- Rust stable and Cargo are installed (`rustc 1.98.0`, `cargo 1.98.0`). A small Tauri 2.10.3 desktop crate now owns process lifecycle, selected-document state, local progress, and a scoped audio protocol. Direct Tokio use remains unnecessary for this one child process and background monitor.
- The Tauri app compiled against GTK 3 and WebKitGTK 4.1, both present in the environment. GTK could not initialize a display during an app launch attempt, so UI runtime behavior is not yet verified. The Tauri CLI is not installed; `cargo run` is the documented development entry point.
- Node.js 24 and npm are installed; Vite builds the current React + TypeScript frontend in `ui-react/`.
- Tauri dependencies are exact-versioned in `src-tauri/Cargo.toml` and pinned in `src-tauri/Cargo.lock`. Native file-picker branches exist for Linux, macOS, and Windows without a dialog plugin; the current environment has only been validated on Linux. Rust, Python, and model packaging on other platforms remain unverified.
- Python 3.14 is available. The orchestrator uses only its standard library; the local speech environment has `piper-tts==1.8.0` and `onnxruntime==1.31.0` in `.venv`. Keep model/inference environments isolated and pin versions before integrating them.
- Poppler `pdftotext` is available and used for the PDF extraction path. The source-mapped adapter now uses `-bbox-layout`, which emits page, block, line, and word bounding boxes; the previous `-layout` mode remains the measured text-order comparison and compatibility baseline. Neither mode guarantees logical reading order for all multi-column or table layouts; Sonara adds a review note when side-by-side regions are detected.
- PyMuPDF's `Page.get_text("dict")` is a plausible alternative with block/line/span and font metadata, but it is not installed or part of the runtime. Its official documentation describes AGPL or commercial licensing. Revisit only if representative extraction tests show that Poppler's available geometry cannot meet a concrete need.

## Speech engine selection status

No comparable quality or performance benchmark has been run, so no winner is claimed. The default implementation now uses Piper 1.8.0's Python API in a persistent local worker that loads one voice and synthesizes narration units to WAV files. The CLI combines these chunks; it does not yet play them incrementally. Piper is a baseline integration, not a quality conclusion. The maintained upstream is `OHF-Voice/piper1-gpl`, which is GPL-3.0-or-later; review redistribution implications before bundling it. Each voice pack has a separate model card/licence and must be checked individually. The John medium voice is installed for local testing; its card identifies LibriVox recordings as public domain.

Kokoro is the next benchmark candidate: the upstream `hexgrad/Kokoro-82M` card declares Apache-2.0 weights and the official `kokoro.js` documents local WASM/WebGPU/CPU execution and speed/voice inputs. Runtime, frontend packaging, pronunciation dependencies, and each ONNX export/voice asset still require review. XTTS-v2 is deferred until a multilingual/reference-voice requirement warrants its heavier runtime and model-specific licence review.

## Current desktop boundary

The Tauri frontend exposes only typed `invoke` commands and a Tauri event. The Python process is started with safe argument boundaries, a minimal environment, and a dedicated process group; cancellation/window close signals the worker group. Audio bytes are not returned through JSON: an ephemeral, token-protected listener bound to `127.0.0.1` serves only active-manifest chunk indexes and supports range requests. The server validates the Host header and canonical chunk path, and is restricted by the frontend CSP to media requests. Session metadata and per-document progress use versioned JSON under app-local data. No arbitrary filesystem plugin or shell command capability is granted to the frontend.

Python, Piper, voice files, and optional LLM runtime/model files are external prerequisites; bundling is disabled. This app has compiled, but could not be opened in the headless environment.

## Embedded local LLM runtime

The optional `requirements-llm.txt` pins `llama-cpp-python==0.3.36`, which embeds llama.cpp bindings into the controlled Python worker. The default Piper dependency set remains small; install the LLM requirements into the same Python environment used by `SONARA_PYTHON` only when embedded inference is needed. Native compilation, accelerator build options, and wheel availability vary by Python version and OS. The Python 3.14 environment used for the Piper baseline has not been validated with this runtime. The current repository does not package the runtime or GGUF weights, and cross-platform packaging has not been validated.

The Rust Tauri process owns one persistent `llm_client.py worker`, started lazily at the first LLM IPC request and shut down with the window. The Python worker imports llama-cpp-python only for an embedded model request. `EmbeddedModelManager` owns model loading/reuse/idle unloading and runs inference serially; local GGUF/model errors are surfaced through structured Tauri responses. Python logs only event names and exception types to the Sonara cache directory, never prompt contents, generated text, or API keys.

`embedded_llama_cpp` performs direct inference and does not open a port or require a server. `llama_cpp` remains the pre-existing HTTP llama.cpp integration. Ollama is also HTTP-based; OpenAI, Gemini, and custom providers retain their OpenAI-compatible HTTP path. Model discovery checks only the selected model directory and a few explicit Sonara model folders, not the whole filesystem. Embedded chat currently has no vector retrieval; it supplies bounded extracted document text directly. HTTP embeddings remain available only through the legacy server configuration.

## Deliberately deferred

SQLx/SQLite, CPAL, Symphonia, Rubato, PyO3, FFmpeg, and spaCy remain deferred. Re-evaluate each against a concrete feature and measured need. The desktop WebView schedules generated passage WAVs through a range-capable local URI protocol, but synthesis still completes before playback; add native audio only if browser/WebView testing shows a real device or interruption problem.

## Primary references

- [Amadeus-chat direct local LLM design](https://github.com/adityatawde9699/Amadeus-chat) (one-shot load/use/release pattern)
- [Amadeus-AI llama.cpp adapter](https://github.com/adityatawde9699/Amadeus-AI/blob/main/src/infra/llm/llama_cpp_adapter.py) (direct GGUF loading and off-event-loop initialization)
- [llama-cpp-python chat completion API](https://github.com/abetlen/llama-cpp-python#chat-completion) (chat template selection and direct inference API)
- [Tauri 2 Linux prerequisites](https://v2.tauri.app/start/prerequisites/)
- [Tauri Rust commands](https://v2.tauri.app/develop/calling-rust/) and [custom URI scheme protocol API](https://docs.rs/tauri/2.10.3/tauri/struct.Builder.html#method.register_uri_scheme_protocol)
- [Tauri Content Security Policy](https://v2.tauri.app/security/csp/)
- [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M)
- [Kokoro.js official usage](https://github.com/hexgrad/kokoro/blob/main/kokoro.js/README.md)
- [Piper CLI documentation](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/CLI.md)
- [Piper upstream and licence](https://github.com/OHF-Voice/piper1-gpl)
- [Original Piper archive notice](https://github.com/rhasspy/piper)
- [Poppler pdftotext options and bbox-layout output](https://manpages.debian.org/unstable/poppler-utils/pdftotext.1.en.html)
- [PyMuPDF structured text extraction](https://pymupdf.readthedocs.io/en/latest/faq/index.html) and [license terms](https://pymupdf.readthedocs.io/en/latest/about.html)
