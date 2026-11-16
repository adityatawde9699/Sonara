# Privacy and data handling

Sonara's document reader and default Piper synthesis path are designed to process selected documents locally. This does not mean every optional feature is offline or that the application has undergone an independent privacy audit.

## Local processing

- Document text extraction is performed by local adapters (including Poppler for PDFs and the Python standard library for supported text/ZIP formats).
- Piper inference is invoked locally through the Python worker and installed model files.
- The desktop audio server binds to loopback on an ephemeral port and serves generated audio to the local WebView. It uses a per-launch random token and checks the active generated session.
- Local progress, the document library (which includes each prepared document's path on disk), preferences, generated audio, and caches may be written to application data, WebView storage, output directories, or cache directories as described in [configuration](CONFIGURATION.md).
- Missing models are never downloaded silently. Installers ship without voice models, and Settings → Speech models downloads one only when you press its Download button.

## Model downloads

A model download (`model_downloads.py`) requests fixed files over HTTPS: Piper voices from `huggingface.co` (revision `v1.0.0` of `rhasspy/piper-voices`) and Kokoro from the `thewh1teagle/kokoro-onnx` GitHub release `model-files-v1.1`. Those hosts, and any they redirect to (redirects must stay on HTTPS), see an ordinary file request from your IP address with the user agent `Sonara model installer`. No document text, settings or identifiers are sent. Each file must match its published size and a pinned SHA-256 hash before it is installed. Proxy and certificate environment variables are honored.

## Optional external services

The assistant can be configured for an OpenAI-compatible remote endpoint, including providers that operate outside the device. When used, request prompts and document context supplied to that feature may be sent to the configured endpoint under that provider's terms. Passage selection (keyword ranking) runs on the device, so for long documents a remote provider receives the selected passages (up to about 6,000 characters per request) rather than the whole text. A long-document summary sends up to eight such sections, one per request. Local model choices are also optional and depend on the installed runtime/model. Basic document extraction and ordinary local Piper synthesis do not require the assistant.

## Logs and user control

Do not share raw logs without checking for local file paths, document titles, prompts, or other personal information. Remove generated audio and caches using the application's controls or the relevant paths documented in the UI/CLI. Exact cleanup behavior can vary by workflow; inspect the selected output and cache directory before deleting files manually.

This document describes source behavior and is not a guarantee that no information ever leaves the device. Review the current provider configuration before using external services.
