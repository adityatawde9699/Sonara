# Configuration

Sonara's settings are split between command-line arguments, environment variables used by the desktop shell/worker, the UI's local WebView storage, and per-user application data. Paths and behavior below are taken from the current source; this is a development prototype, not a stable configuration compatibility promise.

## Desktop runtime environment

| Variable | Purpose | Default / behavior |
|---|---|---|
| `SONARA_PROJECT_ROOT` | Select the checkout containing `sonara.py` and runtime assets. | Application's discovered project root. |
| `SONARA_PYTHON` | Select the Python executable for the primary engine. | `<project root>/.venv/bin/python` on the current implementation. |
| `SONARA_KOKORO_PYTHON` | Select a separate Python executable for Kokoro. | `<project root>/.cache/kokoro-venv/bin/python`; see [KOKORO_SETUP.md](KOKORO_SETUP.md). |
| `SONARA_MODEL_DIR` | Override the Piper voice directory. | `<project root>/models/piper`. |
| `SONARA_CACHE_DIR` | Override the local LLM/embedding cache root. | `~/.cache/sonara` on platforms following the current default. |
| `SONARA_EMBEDDING_CACHE_MAX_BYTES` | Set the embedding cache byte budget. | 268435456 bytes (256 MiB); invalid values fall back to the default and values below one byte are clamped to one byte. |

The shell also has CLI defaults and engine-specific flags. Run `.venv/bin/python sonara.py read --help` for the exact options available in the current checkout. Important arguments include document path, `--engine`, `--voice`, `--data-dir`, `--output-dir`, resource profile, and Kokoro model directory.

## Models and storage

- Piper model weights and adjacent `.onnx.json` files are read from the selected model directory. Sonara does not fetch missing voice weights automatically.
- The desktop app keeps its data under Tauri's per-user app-local data directory (on Linux, `~/.local/share/com.sonara.reader/`). See [Desktop data layout](#desktop-data-layout).
- The CLI writes generated WAV chunks, a manifest, and an HTML player under `--output-dir`; the default cache directory is `.sonara-audio-cache` below the current working directory.
- UI preferences and favorites are stored in WebView `localStorage`; the API key is intentionally blanked before LLM configuration is persisted.
- The document library is `library.json` in the app-local data directory. It records up to 50 prepared documents: name, hash, voice, duration, last-prepared time, and the document's absolute path, so the document can be reopened. The path stays in the backend and is never sent to the WebView. Clear history removes the file. Treat the library and local progress as local application data.

## Desktop data layout

Sonara 2.0 stores desktop data as data version 2:

| Path | Contents |
|---|---|
| `data-version` | `2`. Written last by the one-time upgrade from 1.x. |
| `library.json` | Library, version 2: adds `createdAt`, `pageCount`, `language` and `complete` to each entry. |
| `progress/<sha256>.json` | Reading position, version 2: adds `unitId`, the narration unit of the saved passage, so a position survives a re-synthesis that renumbers passages. Version 1 files are still read. |
| `audio-cache/` | Content-addressed synthesis cache shared by every run, pruned to the resource profile's budget. |
| `sessions/<run-id>/` | One directory per synthesis run: `audio_chunks.json` (manifest schema 2), `chunks/`, `extracted_document.json`, `document_text.txt` and `session.json` (version 2). The desktop app does not write the combined `speech.wav`. |
| `current-session` | The run id of the session reopened at launch. |
| `worker.log` | Output of the most recent synthesis run. |

Each run writes only inside its own directory. A cancelled or failed run is deleted whole, and the session that was open before it is left alone. When a run finishes, it becomes the current session and every other run directory is deleted; launch removes any left by a crash.

**Upgrading from 1.x** happens once, at the first launch of 2.0:
- `library.json` is converted to version 2, and the original is kept as `library.json.v1.bak`.
- `reader-output/.sonara-audio-cache` moves to `audio-cache/`.
- The last session moves to `sessions/migrated-v1/` if all of its passages are present; otherwise it is dropped, and reopening the document re-synthesizes it, mostly from the cache.
- `reader-output/` is then removed.

Every step can be repeated, so an upgrade interrupted by a crash finishes on the next launch. The upgrade is one-way: Sonara 1.x reading version 2 data shows an empty library, and `library.json.v1.bak` restores it by hand. A library, progress file or `data-version` from a newer Sonara is refused rather than overwritten.

## AI providers

The optional assistant can use the embedded llama.cpp binding with a user-selected GGUF or configured OpenAI-compatible endpoints. Remote endpoints may receive the prompts and bounded document context used for a request. Do not configure an external endpoint if you do not want that data sent to it. See [privacy notes](PRIVACY.md).

## Secrets

Do not put API keys in source code, `.env` files committed to Git, screenshots, logs, or issue reports. The React UI clears the key from persisted local configuration, but the application currently requires the user to provide it for a configured provider session. Review current storage behavior before making security claims.
