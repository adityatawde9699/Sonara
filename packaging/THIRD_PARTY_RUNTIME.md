# Native document tools inventory

The release workflow stages these tools at build time. This is an acquisition record, not a complete application SBOM or legal approval.

| Component | Windows source | Linux source | macOS source | Runtime files |
| --- | --- | --- | --- | --- |
| Poppler | `oschwartz10612/poppler-windows`, version 26.07.0-0, SHA-256 checked | Ubuntu runner `poppler-utils` and `poppler-data` packages | Homebrew `poppler` formula | `pdftotext`, `pdftoppm`, shared libraries, Poppler data |
| Tesseract | Tesseract 5.5.3.20260724 installer, SHA-256 checked | Ubuntu runner `tesseract-ocr` and `tesseract-ocr-eng` packages | Homebrew `tesseract` formula | Tesseract executable, shared libraries, English trained data, configs |

Each staging script copies license files available from its source package into `packaging/staging/sonara/tools/licenses`. Review that directory and its transitive dependency notices for every release. Linux package license copies are collected from Debian package metadata for the executable dependency closure; Windows and macOS staging currently collect upstream tool notices but do not establish a complete notice set for every linked library.

**Security update required:** upstream Tesseract 5.5.4, released 2026-10-28, fixes security advisories. The pinned Windows installer is 5.5.3. Do not publish a Windows release until a verified 5.5.4-or-newer Windows binary is staged and the checksums and licenses are updated.

All versions are recorded by the CI job logs today; the workflow does not yet emit an SBOM or persist exact Linux/macOS package versions as release assets. The Piper, Python, llama.cpp, Kokoro, frontend, Rust, and model/voice dependency inventory is outside this native-tools table and remains to be completed.
