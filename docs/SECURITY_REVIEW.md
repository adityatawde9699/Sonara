# Repository security review

**Scope:** targeted source review of document/archive extraction, desktop IPC and local audio delivery, subprocess invocation, frontend configuration storage, and the Tauri Content Security Policy. This is not a penetration test, dependency advisory scan, or security certification.

## Changes made in this review

- DOCX/EPUB use ZIP containers, so the existing 100 MiB compressed input limit did not bound decompressed text. Extraction now rejects archives with more than 10,000 entries, individual text members over 32 MiB, and cumulative EPUB text over 200 MiB. Reads are capped even if an archive member's declared size is misleading. Regression tests cover member, cumulative, and entry-count limits.
- The React UI uses local/system fonts and makes no Google Fonts requests. The desktop CSP no longer grants Google origins access for connections, styles, or fonts. Tauri IPC and the loopback audio `media-src` remain explicitly allowed.
- Existing subprocess execution passes argument arrays rather than constructing shell commands. The primary Piper worker receives text via stdin; the compatibility path uses a temporary text file. Review changes should preserve these boundaries.

## Existing controls observed

- The Rust audio listener binds to `127.0.0.1` on an ephemeral port and checks a per-launch token, request host, active document/passage, canonical path, byte ranges, and response bounds. It shuts down with the application lifecycle.
- The Tauri frontend capability set is limited to `core:default`; document selection and filesystem access are mediated by Rust commands rather than an exposed arbitrary filesystem API.
- API keys are kept by the Rust process in the OS credential store (Keychain, Windows Credential Manager, Secret Service via the `keyring` crate), or in Rust memory for the session when no store exists. The webview sends a key once, to save it, and never holds or reads it afterwards. Rust adds the key to the request for the LLM worker, so it is still passed to the worker process over its stdin.
- The managed `llama-server` program comes from PATH or the native file picker, never from the webview; the webview can only name GGUF model files, which must exist and end in `.gguf`. Servers bind to 127.0.0.1 on a free port.
- Remote AI providers can receive prompts and bounded document context. Users must choose and configure the provider; ordinary extraction and local Piper narration do not need that provider.

## Remaining risks and review work

- Archive parsing remains resource intensive within the stated bounds. The compressed-size limit does not establish a hard process-memory ceiling; malformed or adversarial files should continue to be tested.
- Poppler and optional OCR process files selected by the user. Keep time, input, output, and diagnostic bounds when modifying these adapters.
- Native models, third-party runtimes, Python wheels, Rust crates, and system packages require a separate versioned license/notice inventory before distribution. No complete third-party license audit has been performed here.
- No online vulnerability advisory scan was run. Lockfiles are present, but that alone does not establish dependency safety.
- npm and Cargo have lockfiles; `requirements.txt` pins direct Python dependencies but does not lock all transitive versions. Repeatable Python environments and full dependency audits remain open work.
- No private vulnerability intake was verified. See root [SECURITY.md](../SECURITY.md); maintainers should enable GitHub private reporting or publish a monitored private channel.
- Sonara's original project code and documentation carry GPL-3.0-only. This does not resolve distribution rights for runtimes, models, native tools, or media assets; those need a separate review.

Revisit this review when document parsers, IPC capabilities, provider handling, model acquisition, or packaging changes.
