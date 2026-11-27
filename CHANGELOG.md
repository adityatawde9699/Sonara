# Changelog

This file records notable user-facing changes. The `v1.0.0` GitHub release exists but has no installer assets. Historical implementation notes and validation evidence remain in `docs/TESTING.md` and `docs/ROADMAP.md`.

## Unreleased (v2.0.0)

### Breaking

- Desktop data moves to a version 2 layout (see docs/CONFIGURATION.md, "Desktop data layout"). The first launch upgrades Sonara 1.x data once: the library is converted and the original kept as `library.json.v1.bak`, the audio cache moves to `audio-cache/`, and the last session is kept if all of its audio is present. The upgrade is one-way: Sonara 1.x shows an empty library on upgraded data.
- The `audio_chunks.json` manifest is schema 2. Every manifest carries `total_units`, `completed_units` and `complete`, and `page_count`.

### Changed

- Each synthesis run writes to its own directory. Cancelling or failing a run no longer leaves a partial manifest behind or leaks the previous session's audio, and the session you were listening to stays intact while a new document is prepared.
- The desktop app no longer writes the combined `speech.wav`, halving the disk used per session. The CLI still writes it; `--no-combined-audio` turns it off, and `--cache-dir` sets the synthesis cache directory.
- Saved positions record the passage's narration unit as well as its number, so a position survives a re-synthesis that renumbers passages.
- A library or reading position saved by a newer Sonara is refused instead of being silently replaced.

## v1.0.10 - 2026-11-17

### Added

- Settings → Speech models downloads the supported Piper voices (Ryan, Lessac, Bryce, John) and Kokoro, which installers do not include. Each file comes over HTTPS from a fixed upstream revision, is capped at its published size, and is installed only after its pinned SHA-256 matches; a download can be cancelled, and a cancelled or failed download leaves nothing behind. The voice list updates when a voice is installed. Downloads happen only when you press Download (see docs/PRIVACY.md).

### Changed

- The desktop interface is redesigned: warm graphite surfaces with one amber accent, plainer wording, a reading view set in Newsreader with the spoken sentence highlighted in amber, and a passage strip that shows progress in the Continue card and the player. Icons now come from one set (lucide) at consistent sizes, and the Inter and Newsreader fonts are bundled with the app. The light theme uses the same palette.
- Short documents show their length in seconds instead of "0 min".

### Fixed

- `models/piper/README.md` listed the wrong size for the Ryan model; it is 63,201,294 bytes.

## v1.0.9 - 2026-11-16

This release ships the v1.0.8 AppImage fixes (no libwayland crash on newer GPU drivers, bundled GStreamer plugins for audio).

### Fixed

- The Linux build installs `desktop-file-utils`, which `appimagetool` needs to repack the AppImage.

## v1.0.8 - 2026-11-16

The v1.0.8 release has no installers; repacking the AppImage failed on the build runner, which lacked `desktop-file-validate`. Fixed in v1.0.9.

### Fixed

- The Linux AppImage crashed at startup on newer systems (seen on Ubuntu 26.04 with an NVIDIA driver under Wayland). It bundled the build machine's `libwayland-client`, which the system GPU driver's EGL library called into. The release build now removes the bundled Wayland libraries so the system's are used, and the install check fails if they come back. The `.deb` was not affected.
- Audio did not play in the Linux AppImage on newer systems ("GStreamer element appsink not found"). The AppImage bundled GStreamer's core libraries but none of its plugins, and the older core cannot load the host's newer plugins. It now bundles the plugins it needs, and the install check verifies they are there.

## v1.0.7 - 2026-11-16

### Fixed

- The release install checks failed on correct installers. On Linux the check looked for the bundled runtime under a `resources/` folder (Tauri installs it at `/usr/lib/Sonara/sonara/`), started the extracted AppImage without its `AppRun` launcher, and removed the package by the wrong name (`sonara`, not `sonara-desktop`); a missing part now fails with a message. On macOS the check installed the app under `/var`, a symlink, and Tauri will not start from a path that contains one.

## v1.0.6 - 2026-11-16

The v1.0.6 release has no installers; its installers built, but the install checks fixed in v1.0.7 failed on them.

### Changed

- macOS installers are built for Apple Silicon only. The Intel (x86_64) target is removed from the release matrix, the asset checks, the CI staging job and the download page; the pinned onnxruntime 1.31.0 has no Intel macOS wheel.

### Fixed

- The macOS build no longer fails in `security import` when no Apple signing secrets are configured. Empty signing variables are no longer passed to Tauri.
- Releases can publish without Apple Developer credentials. The macOS app and its bundled tools are then signed ad hoc (Apple Silicon will not run unsigned code), the install check skips only the Gatekeeper and notarization checks, and the release notes explain how to open the unnotarized app. With the `APPLE_*` secrets set, signing and notarization stay mandatory.

## v1.0.5 - 2026-11-16

The v1.0.5 release has no installers; its macOS builds failed on code signing and on the Intel onnxruntime wheel, both addressed in v1.0.6.

### Fixed

- macOS installer builds no longer hang. Staging Poppler and Tesseract used `dylibbundler`, which could not resolve Homebrew poppler's `@rpath` library and waited on stdin until the job timed out. It now gets Homebrew's library directories to search, and fails at once if a library still cannot be found. A CI job runs this staging on both macOS runners for every push.

## v1.0.4 - 2026-11-16

The v1.0.4 release has no installers; its macOS builds hung on the tool staging fixed in v1.0.5.


### Fixed

- AppImage builds failed because no app icons were configured; the only icon was a 128 px placeholder. Sonara now has a full icon set (PNG sizes, `.icns` for macOS, `.ico` for Windows) made from the sound-wave mark the website uses.

## v1.0.3 - 2026-11-16

The v1.0.3 release has no installers; its AppImage build failed on the missing icons fixed in v1.0.4.


### Fixed

- Installers can be built again: the bundle category `AudioVideo` is not one Tauri accepts, and every installer build stopped with "invalid category". It is now `Productivity` (Linux menus list Sonara under Office).

## v1.0.2 - 2026-11-16

The v1.0.2 release has no installers; its build failed on the bundle category fixed in v1.0.3. Everything below ships in v1.0.7.


### Security

- `get_document_text` no longer accepts a file path from the frontend; it reads only the selected document or Sonara's own output, capped at 16 MiB.
- LLM HTTP providers require `https` (plain `http` only to localhost), reject unknown providers, and do not follow redirects.
- The OCR cache moved from a shared temp directory to a private per-user directory, with symlink-safe atomic writes.
- Release signing secrets are scoped to the steps that sign; the Windows PFX password is no longer passed on the `signtool` command line.
- Updated `plist`/`quick-xml`, `time`, and `tokio` in `Cargo.lock` to clear RustSec advisories.
- The local audio server serves each connection on its own thread (at most 8 at once, then `503`), so a stalled client no longer blocks playback. It streams files instead of buffering up to 64 MiB, keeps running after transient accept errors, and compares the access token in constant time.
- Piper voices whose IDs are in the pinned table (`models/piper/README.md`) are refused if their model or config does not match the published SHA-256. Voice names are validated in Python as well as Rust, so `--voice ../x` cannot reach a path outside the model directory.
- Workers can no longer outlive Sonara. On Windows every Python worker (synthesis, preview, LLM) runs in a Job Object that kills its whole tree when Sonara stops or crashes; Unix already used process groups. Every worker also watches its parent (`parent_watch.py`) and stops its process group if Sonara disappears without cleaning up, for example after a crash under `panic = "abort"`.
- The LLM worker now starts with a cleared environment, like the synthesis worker. Only proxy and CA-bundle variables are passed through, for remote providers.
- Each release target publishes a CycloneDX 1.6 SBOM (`Sonara-<platform>-<arch>.cdx.json`). It lists the Rust crates for that target, the bundled frontend packages, the frozen Python distributions, the pinned Piper voices and the staged Poppler and Tesseract versions. Every release file (installers, SBOMs, checksums) gets a signed GitHub build provenance attestation; check one with `gh attestation verify <file> --repo <owner>/Sonara`. The release fails if a target's SBOM is missing.
- Removed `diskcache` (CVE-2025-69872 / PYSEC-2026-2447: unsafe pickle loading, no fixed release) from every install path instead of ignoring the advisory. llama-cpp-python is installed with `--no-deps` and its other dependencies are pinned directly. `llama_runtime.py` supplies a disabled stand-in, so a llama.cpp disk cache can never be created. The release build fails if diskcache is present, and the packaged runtime's self-check fails if it is bundled.

### Fixed

- Remote LLM providers can authenticate from the Assistant; the API key is shared in memory with Settings and still never persisted.
- Scanned PDFs are OCRed page by page in packaged builds instead of silently reading only page 1 (`pdfinfo` is not bundled).
- Sentence splitting is linear time; an 80 KB paragraph took about 20 s and now takes 0.03 s.
- An unresponsive LLM worker is stopped after 300 s, and closing the app no longer waits on an in-flight request.
- Keyboard shortcuts ignore Ctrl/Cmd/Alt combinations and focused controls, and do not fire behind open dialogs. Dialogs trap focus, restore it on close, and Escape closes only the topmost one.
- A restored passage loads even when the player's audio element mounts after progress is restored. Before, playback could stay empty after reopening the app; the desktop E2E test found it in about one run in six.
- A saved Kokoro voice is no longer replaced by a Piper voice when the Piper voice list loads.

### Added

- The library is kept by the desktop backend (`library.json` in app-local data, up to 50 documents) instead of WebView storage. Library and history rows can reopen a document. Sonara selects the original file again and prepares it, mostly from the audio cache, and saved progress is restored. A moved or deleted file is shown as unavailable. The frontend refers to documents only by hash and never sees or supplies their paths. The old localStorage history had no paths and is discarded.
- DOCX footnotes and endnotes are read after the body. Text inside content controls, tracked insertions, and nested tables is no longer dropped, and hidden (`w:vanish`) text is skipped.
- Markdown files are read with Markdown structure: `#` and underlined headings, list and quote markers, emphasis, inline code, and link syntax are not spoken.
- OCR pages with low recognition confidence (under 60%) are reported in the extraction notes.
- Read-along: the reading view highlights the passage being spoken and turns pages with it (switch off with Follow along). Each paragraph has a button to start listening there. Sessions prepared before this update show the text without highlighting until they are prepared again.
- Kokoro speaks British English, Spanish, French, Hindi, Italian, Brazilian Portuguese and (experimental) Mandarin as well as US English. The voice sets the language; Settings lists 49 voices grouped by language. Japanese voices are not offered, because Kokoro's Japanese needs a G2P that Sonara does not ship.
- The assistant retrieves relevant passages for every provider, not only the HTTP llama.cpp server. Keyword ranking (BM25) runs on the device for all providers; with a local embedding server it is fused with vector ranking. Answers cite passages as `[Passage n]`. Embedded models get a context budget that fits their window.
- Summaries, takeaways and explanations of long documents cover the whole document: sections are summarised and then combined (up to 8 sections within 4 minutes), instead of reading only the first 6,000 characters. When sections had to be skipped, the summary says how much it covers.
- `retrieval_eval.py` measures retrieval quality (recall@k, MRR) on a bundled labelled set or your own document; results are in `docs/BENCHMARKS.md` §7.
- `listening_eval.py` can add a Kokoro arm to the blind listening pack (`--kokoro-dir`), and `listening_eval.py analyze` reads completed rating sheets and reports per-condition scores with listener-level bootstrap intervals, paired differences against the default Piper voice, and preference shares.
- A WebDriver end-to-end test (`e2e/desktop-smoke.mjs`, run in CI) drives the real desktop app. It reopens a document from the library, prepares speech with Piper, plays the first passage from the audio server, and checks the read-along highlight.

### Removed

- The "AI Polish" narration toggle and badge, and the unused `llm_enhance_script` command behind them. Nothing applied its output.
- The `ui/` static prototype, its test, and the unused `@tauri-apps/api` dependency.

### Changed

- EPUB extraction skips `script`, `style`, `head`, `template`, `noscript`, and ruby annotations, and marks `epub:type` footnotes and endnotes as footnotes.
- Plain-text headings need evidence (a numbered heading, title case, or all caps without end punctuation). List items are no longer read as headings.
- Table rows made only of `|` separators no longer fail narration.
- The audio cache computes each chunk's key once and prunes at the start, every tenth of the cache budget, and at the end of a run, instead of scanning the cache after every chunk.
- `src-tauri/src/lib.rs` is split into `audio_server`, `library`, `llm_rpc`, `pickers`, `runtime`, `session`, and `voices` modules. The frontend player and settings moved out of `useSonara` into `useAudioPlayer` and `useSpeechSettings`.
- Narration ruleset `rules-7`: Chinese and Japanese full stops (`。！？`) and the Devanagari danda (`।`) end sentences, and Han and kana characters count as words when bounding a passage. A Chinese paragraph is no longer one passage several minutes long. Audio prepared with `rules-6` is prepared again.
- Narration reads more text correctly (ruleset `rules-6`):
  - Titles and reference abbreviations ("Dr.", "St.", "Fig. 3", "pp. 10-12", "Jan. 5") no longer make the voice pause mid-sentence.
  - Years and decades are read as years ("the 1990s" was "one thousand nine hundred ninety seconds"), and "ranked 3 in" is no longer "three inches".
  - Currency, times, number and year ranges, fractions, Roman numerals after "Chapter"/"World War"/regnal names, and a small technical-term lexicon are now spoken.
  - Previously generated audio and saved progress are invalidated.
- Synthesized audio is finished before playback. Edge silence is trimmed, speech level is matched across voices (−18 dBFS, peaks capped at −1 dBFS; raw Piper audio peaked at full scale), and chunks fade in and out.
- Pauses and the `less`/`more` variation presets are tuned per voice from measurements (`docs/BENCHMARKS.md` §6). Slower voices get proportionally longer pauses. The exported `speech.wav` now contains the planned pauses between passages.
- OCR is bounded to 500 pages and 30 minutes per document, and oversized pages are rendered at reduced resolution.
- CI runs Python on 3.12 and 3.14, `cargo clippy -D warnings`, and npm/pip/cargo dependency audits. GitHub Actions are pinned to commit SHAs.
- The release workflow defaults to Linux and macOS (`unix`), builds the named tag, and writes per-target checksum files.

- Added bounded ZIP-member and expanded-text limits for DOCX and EPUB extraction.
- Removed unused remote Google Fonts origins from the desktop Content Security Policy.
- Changed the license for Sonara's original project code and documentation to GPL-3.0-only.
- Added a GitHub Pages workflow that publishes the independent `site/` directory.
- Made the OCR page-count test independent of whether Poppler's `pdfinfo` is installed and prepared Python for Rust worker tests in CI.
- Added contributor, support, security, development, configuration, privacy, testing, and release guidance.

## v1.0.1 - 2026-10-30

### Added

- Added native GitHub Actions packaging, installed-app smoke checks, and release asset publishing for supported Windows, Linux, and macOS targets.
- Added automatic operating-system and architecture detection, manual platform selection, and latest-release asset lookup to the marketing site's download section.

### Fixed

- Prepared the Tauri resource directory during Rust CI so tests work from a clean checkout.

When preparing a release, summarize shipped changes here under the actual version and date. Do not treat this unreleased section as a published release.
