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
- The current desktop synthesis outputs and versioned reading progress are stored under Tauri's per-user application data directory. Temporary synthesis working files are created by the worker and cleaned up along the normal lifecycle.
- The CLI writes generated WAV chunks, a manifest, and an HTML player under `--output-dir`; the default cache directory is `.sonara-audio-cache` below the current working directory.
- UI preferences and recent-document metadata are stored in WebView `localStorage`; the API key is intentionally blanked before LLM configuration is persisted. Treat recent metadata and local progress as local application data.

## AI providers

The optional assistant can use the embedded llama.cpp binding with a user-selected GGUF or configured OpenAI-compatible endpoints. Remote endpoints may receive the prompts and bounded document context used for a request. Do not configure an external endpoint if you do not want that data sent to it. See [privacy notes](PRIVACY.md).

## Secrets

Do not put API keys in source code, `.env` files committed to Git, screenshots, logs, or issue reports. The React UI clears the key from persisted local configuration, but the application currently requires the user to provide it for a configured provider session. Review current storage behavior before making security claims.
