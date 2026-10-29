# Contributing to Sonara

Thank you for considering a contribution. Sonara is an active desktop and CLI prototype; focused fixes, documentation improvements, reproducible bug reports, and tests are all useful.

## Before you start

- Search existing issues before opening a duplicate. Use the repository's GitHub Issues page for bugs and feature proposals.
- For larger changes, open an issue first so the scope and compatibility impact can be discussed.
- Do not include private documents, voice-model weights, credentials, or personal data in issues or pull requests.

## Development setup

Follow [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Fast Python, React, and Rust checks do not download speech models. The opt-in integration suite uses Poppler, Piper, and an already installed local voice model.

## Changes and validation

- Keep pull requests focused and avoid unrelated refactoring.
- Add or update tests for behavior changes.
- Update the relevant user or developer documentation when commands, settings, formats, or behavior change.
- Preserve source text and source mappings; do not add network calls for document contents without an explicit, documented user choice.
- Do not commit secrets, generated audio, local databases, model weights, or build output.
- Run the checks relevant to your change and include the exact commands and results in the pull request.
- Use clear commit messages that describe the change.

## Pull requests

Complete the pull request template. Include reproduction steps for fixes, screenshots for UI changes, and any migration, compatibility, privacy, or licensing implications. A maintainer may ask for narrower scope or additional evidence before merging.

## Reporting security issues

Please follow [SECURITY.md](SECURITY.md). Do not publish exploitable details in a public issue before contacting the project through a private channel, if one is enabled.
