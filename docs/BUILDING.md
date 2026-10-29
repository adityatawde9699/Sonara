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

For developer packaging and release limitations, see [PACKAGING.md](PACKAGING.md) and [RELEASE_PROCESS.md](RELEASE_PROCESS.md). CI stages Poppler and Tesseract and has clean-runner install checks. Those checks have not yet been observed passing on hosted runners, and the Windows Tesseract build needs to move to the latest security-fixed upstream release before publishing.

## Native installer workflow (initial packaging phase)

The native package workflow is defined in `.github/workflows/package.yml`. It builds on Windows x64, Linux x64, and both macOS architectures, then installs each artifact on a separate hosted runner and exercises bundled document tools. Push a `v*` tag to run the release workflow. Publication requires signing secrets documented in [RELEASE_PROCESS.md](RELEASE_PROCESS.md). Install `cargo-tauri` before invoking the build locally:

```sh
cargo install tauri-cli --locked
python3.12 -m pip install -r packaging/requirements-runtime.txt
python3.12 packaging/build_runtime.py --clean
cd ui-react && npm ci && npm run build
cd ..
cargo tauri build --bundles nsis,deb,appimage,dmg
```

`packaging/build_runtime.py` must run on the native target OS and architecture; PyInstaller output is not cross-platform. CI stages Poppler/Tesseract from pinned sources and tests PDF extraction and English OCR. Windows binaries use checksum-verified downloads; Linux and macOS tool versions come from runner package managers. The workflow configures Windows signing and Apple signing/notarization when secrets are available, and gates publication on those credentials and installed-app smoke checks. Complete license notices/SBOM and a successful release run remain required before calling the distribution fully ready. See the [distribution plan](SELF_CONTAINED_DISTRIBUTION_PLAN.md).
