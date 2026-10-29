# Privacy and data handling

Sonara's document reader and default Piper synthesis path are designed to process selected documents locally. This does not mean every optional feature is offline or that the application has undergone an independent privacy audit.

## Local processing

- Document text extraction is performed by local adapters (including Poppler for PDFs and the Python standard library for supported text/ZIP formats).
- Piper inference is invoked locally through the Python worker and installed model files.
- The desktop audio server binds to loopback on an ephemeral port and serves generated audio to the local WebView. It uses a per-launch random token and checks the active generated session.
- Local progress, recent metadata, preferences, generated audio, and caches may be written to application data, WebView storage, output directories, or cache directories as described in [configuration](CONFIGURATION.md).
- Missing models are not silently downloaded by the default workflow.

## Optional external services

The assistant can be configured for an OpenAI-compatible remote endpoint, including providers that operate outside the device. When used, request prompts and document context supplied to that feature may be sent to the configured endpoint under that provider's terms. Local model choices are also optional and depend on the installed runtime/model. Basic document extraction and ordinary local Piper synthesis do not require the assistant.

## Logs and user control

Do not share raw logs without checking for local file paths, document titles, prompts, or other personal information. Remove generated audio and caches using the application's controls or the relevant paths documented in the UI/CLI. Exact cleanup behavior can vary by workflow; inspect the selected output and cache directory before deleting files manually.

This document describes source behavior and is not a guarantee that no information ever leaves the device. Review the current provider configuration before using external services.
