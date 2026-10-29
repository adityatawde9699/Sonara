# Troubleshooting

## App does not start

- Confirm the frontend bundle exists: from `ui-react/`, run `npm ci` and `npm run build`.
- Confirm Rust/Cargo and host Tauri libraries are installed; Linux needs GTK 3 and WebKitGTK 4.1 development/runtime components.
- Interactive desktop startup needs a usable graphical session. Headless CI can compile and test but cannot establish GUI behavior.
- The development runtime expects the checkout, Python environment, and models to be available. Use the `SONARA_*` path overrides in [configuration](CONFIGURATION.md) if necessary.

## PDF extraction fails

- Check `pdftotext -v` and install Poppler using your operating system's package manager.
- Scanned image PDFs require optional `pdftoppm` and Tesseract support. Text extraction can be empty if a document contains only images and OCR dependencies are missing.
- Encrypted, malformed, unusually large, or complex-layout PDFs may not be readable as expected. Preserve the original and test a copy.

## DOCX or EPUB rejected

- Confirm the file is a valid DOCX/EPUB archive rather than a renamed file.
- Sonara enforces a 100 MiB compressed input limit and bounded per-member/total text expansion to avoid excessive resource use. A large valid publication may exceed these defensive limits.
- Password-protected or malformed packages are not guaranteed to work.

## Voice model missing or fails to load

- Confirm the selected model and matching `.onnx.json` are in the configured directory.
- Check the model's provenance, checksum, compatibility, and license using [the model record](../models/piper/README.md).
- Real inference tests are opt-in and need installed model/runtime assets. The default CI does not download voice files.

## Playback fails

- Confirm synthesis completed and that generated session files remain available.
- On Linux WebKitGTK, media decoding may require GStreamer plugins. Review the worker and app logs, but redact document text and paths before sharing.
- If the app reports an unavailable worker, check the Python executable, dependencies, project root, and model directory settings.

## Out of memory or slow synthesis

- Try the `low_resource` profile if the current screen exposes it; this changes resource policy, not the selected voice or model.
- Close other memory-heavy workloads and process a smaller document to isolate the issue.
- Avoid untrusted or unexpectedly large archive documents. DOCX and EPUB expansion has explicit defensive limits.
- Include operating system, CPU/RAM, engine, model, and document size (not the document itself) in a report.

## Optional assistant unavailable

Ordinary local document reading and Piper synthesis do not require the assistant. For an embedded provider, verify the optional `llama-cpp-python` installation and readable GGUF path. For a remote provider, verify the configured endpoint and credentials; request data may be sent to that provider.
