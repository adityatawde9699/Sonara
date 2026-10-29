# Building Sonara

## Current status

The repository supports development builds from source. `src-tauri/tauri.conf.json` sets `bundle.active` to `false`; there are no verified installers or tagged releases in the current checkout. A successful local build is not a supported-platform release.

## Frontend

Requires Node.js 24 and npm, with dependencies fixed by `ui-react/package-lock.json`:

```sh
cd ui-react
npm ci
npm run build
```

The compiled assets are written to `ui-react/dist/`.

## Desktop shell

Requires Rust/Cargo 1.90+ and the native Tauri dependencies for the host platform. On Linux, install GTK 3 and WebKitGTK 4.1 development packages plus the Tauri build prerequisites, and provide Zenity or KDialog for the native file picker.

For Debian/Ubuntu development hosts, the CI environment uses:

```sh
sudo apt-get install build-essential curl file libayatana-appindicator3-dev \
  librsvg2-dev libgtk-3-dev libwebkit2gtk-4.1-dev libssl-dev libxdo-dev patchelf
```

```sh
cargo test --manifest-path src-tauri/Cargo.toml --locked --offline
cargo run --manifest-path src-tauri/Cargo.toml --locked
```

`cargo run` expects the built frontend bundle and the local Python environment/runtime described in [configuration](CONFIGURATION.md). Run `npm run build` first.

## Python engine

Create `.venv` and install `requirements.txt`. PDF text extraction uses Poppler's `pdftotext`. Optional scanned-PDF OCR uses `pdftoppm` and Tesseract. Piper inference requires an installed, compatible voice model and sidecar JSON. The optional embedded llama.cpp dependency is native and has separate requirements; it is not necessary for ordinary document narration.

See [Kokoro setup](KOKORO_SETUP.md) for the optional Kokoro runtime. Availability and packaging are not established for all platforms.

## Packaging limitations

Packaging notes in [PACKAGING.md](PACKAGING.md) are planning material, not tested distribution instructions. Do not distribute a bundle until runtime inclusion, operating-system requirements, signatures, dependencies, voice/model licenses, and compatibility with Sonara's GPL-3.0-only terms have been reviewed. No release pipeline is configured.
