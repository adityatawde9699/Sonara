# Release process

There are no tagged releases, release assets, or automated publishing workflows in the current repository history. The Tauri bundle is disabled. Treat the following as a readiness checklist, not evidence that Sonara is release-ready.

## Before proposing a release

1. Resolve the project's license and document third-party runtime, voice, and model obligations.
2. Define the supported operating systems and test a clean install/build on each one.
3. Verify the Python runtime, external Poppler/OCR requirements, Piper/Kokoro runtime and model acquisition path, and cleanup/uninstall behavior.
4. Build the frontend and desktop shell from a clean checkout; run Python, React, Rust, and relevant integration tests.
5. Verify privacy wording, model provenance, dependency notices, and any external-service behavior.
6. Prepare release notes and update `CHANGELOG.md` with the actual shipped changes.
7. If artifacts are distributed, produce and publish checksums; evaluate signing/notarization requirements for each platform.
8. Manually test installation and ordinary use on the target OS. A CI build alone does not establish a working desktop release.

## Versioning and publishing

The Rust package and Tauri configuration currently report `0.1.0`; this does not by itself imply a release. If maintainers adopt Semantic Versioning, coordinate version changes across package metadata and user-facing release notes, create a reviewed tag, and publish artifacts only after explicit maintainer approval. Do not publish from ordinary pull-request CI.

## After publishing

Verify release page links and checksums, test downloads on a clean machine, monitor reported issues, and correct or withdraw artifacts if a material defect or licensing problem is found. No rollback automation is currently configured.
