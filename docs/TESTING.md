# Testing Sonara

## Implementation checks (2026-10-27)

- `.venv/bin/python -m unittest discover -s tests -v` — 77 passed, 6 opt-in integration tests skipped.
- `cd ui-react && npm test` — 46 passed across 11 test files.
- `cd ui-react && npm run build` — passed (`tsc -b` and Vite production build).
- `cd ui-react && npm run lint` — completed with four React hook/ref warnings in `App.tsx` and `hooks/useSonara.ts`; no lint errors.
- `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline` — 10 Rust tests passed, including persistent LLM worker reuse without model startup loading.
- `cargo fmt --manifest-path src-tauri/Cargo.toml -- --check` — passed.
- `.venv/bin/python listening_eval.py --voice en_US-john-medium --output-dir /tmp/sonara-listening-evaluation --seed 20261027` — generated 24 WAV clips for 8 passages × 3 variation profiles.

These checks validate planner behavior, command wiring, builds, and pack generation. They do not provide participant judgments of naturalness or intelligibility. The GUI itself was not launched in this restricted display environment.

## Narration variation listening evaluation

The repeatable comparison generator synthesizes the expanded corpus using Piper voice defaults, `less`, and `more` variation settings. Randomized clip IDs and row order are placed in a participant pack; the mapping and synthesis metadata are kept under a separate `facilitator-only/` directory. Do not share the facilitator key with listeners during rating. Whole-clip RMS is matched to a target with a peak ceiling; this is a practical level match, not perceptual LUFS normalization.

Generate a pack with the installed local voice:

```sh
.venv/bin/python listening_eval.py --voice en_US-john-medium \
  --output-dir /tmp/sonara-listening-evaluation --seed 20261027
```

The pack includes randomized participant clips and a CSV with naturalness/intelligibility ratings. Collect ratings before unblinding, then compare variation profiles by passage and rating dimension. Generation itself does not establish that any profile sounds more human. For raw synthesis latency/runtime benchmarks, continue to use `benchmark.py`; previously recorded measurements use the historical four-passage corpus. Kokoro numbers are estimates until a corresponding Sonara run and listening evaluation are recorded.

Fast tests cover corpus coverage, level matching, spoken-text/source-offset preservation, opt-in date/citation rules, pause policy, and variation request handling. They do not judge subjective voice quality.

## Test layers

Run fast unit tests from the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

They test the versioned document schema, deterministic block IDs, mocked Poppler process outcomes, extraction time/size/output limits, CLI help, HTML generation, temporary-file CLI override behavior, narration coverage/overrides, and fake-engine stream/cache/error behavior. These unit tests do not load the neural model or require Poppler.

The real end-to-end test is opt-in:

```sh
SONARA_RUN_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -p 'test_integration_*.py' -v
```

It generates a deterministic PDF corpus with the Python standard library and runs actual Poppler. The corpus covers single-column prose, two columns, heading/list/table/footnote layout, line-end hyphenation, a mixed searchable/image-only document, and duplicate passages. Each supported fixture has expected text/order/page count; tests compare structured Poppler output with the legacy `-layout` tokens, verify source boxes and stable IDs, and assert ambiguity/duplicate/scan warnings. Additional opt-in tests use actual `PiperVoice` through the persistent worker, validate chunk mappings and PCM with Python's `wave` module, cancel an active worker process, verify corrupt-model errors, and run the PDF-to-CLI path which writes `speech.wav`, per-passage WAV files, `index.html`, and `audio_chunks.json`. No test needs audio hardware or network access. All generated fixtures and output use temporary directories and are removed on exit.

The Phase 0 baseline generator is `tests/fixtures/pdf_fixture.py`; its expected extracted text is:

```text
Sonara reads local documents aloud. It keeps punctuation, too!

Can the reader preserve paragraph boundaries? We will verify it.

Numbers stay visible: 3.14, 22050 Hz, and one final sentence.
```

With opt-in enabled, tests skip clearly if Poppler, the active environment's `piper-tts`, or local voice/config files are unavailable. If a required tool/model is present but extraction or synthesis fails, the relevant integration test fails. Regular discovery skips all external-tool/model integration cases unless opted in.

Corpus definitions, expected content, and warning expectations are in `tests/fixtures/pdf_corpus.py`. PyMuPDF's official structured text API was reviewed but not installed or run: it is absent locally and the package index was unreachable. The executable comparison in this phase is Poppler `-bbox-layout` versus Poppler `-layout`, not an independent-engine benchmark.

## Prerequisites and environment

- The tested environment is Python 3.14.4 in `.venv`, `piper-tts==1.8.0`, and `onnxruntime==1.31.0`. NumPy 2.5.4 is installed transitively and is not imported directly by Sonara.
- System Poppler: `pdftotext -v` should succeed. Debian/Ubuntu package: `poppler-utils`.
- Local voice and configuration: `models/piper/en_US-john-medium.onnx` and `models/piper/en_US-john-medium.onnx.json`; model identity and hashes are in [the model record](../models/piper/README.md).
- Recreate/check Python dependencies with `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, and `.venv/bin/python -m pip check`.

## Browser acceptance checklist

Browser behavior is currently **unverified**. Cached Chromium binaries (revisions 1228, 1243, and 1247), their headless shells, and a Playwright Node package were found, but every binary failed to launch in this execution environment. Standard Chromium exited with `SIGTRAP` after Crashpad reported `setsockopt: Operation not permitted`; headless shells exited with `sandbox_host_linux ... Operation not permitted`. Firefox and Brave also refuse to start because Snap confinement reports elevated permissions. A system WebKitGTK 4.1 installation was tested as an alternative, but GTK could not connect to the available display and Xvfb could not establish its display. The Playwright wrapper could not resolve package metadata offline. Do not interpret the static HTML assertions as playback verification.

When a supported browser is available, generate a reader using the fixture and test the page directly:

```sh
.venv/bin/python tests/fixtures/pdf_fixture.py /tmp/sonara-known-text.pdf
.venv/bin/python sonara.py read /tmp/sonara-known-text.pdf \
  --voice en_US-john-medium --data-dir ./models/piper --output-dir /tmp/sonara-browser-check
```

Open `/tmp/sonara-browser-check/index.html` as a local `file://` page and verify each item. Use browser devtools to inspect audio state and local storage. Do not infer audible playback from `audio.paused` alone; listen to confirm audio is audible.

1. Confirm the audio loads (`readyState`, finite `duration`, no media error); click Play and listen, then Pause and Resume.
2. Seek to a different position and confirm `currentTime` changes and playback resumes there.
3. Change the speed slider; confirm `playbackRate` follows the selected rate and the audible rate changes.
4. Play/seek long enough to save progress, reload the page, and confirm position and speed restore. Repeat in the target browser because `file:` storage behavior differs by engine/profile.
5. Temporarily rename one `audio_file` referenced in `audio_chunks.json`, reload the page, and confirm the visible chunk error and Retry/Skip controls appear; restore the file afterward. Also test a malformed WAV.
6. With network disabled, repeat load/play to confirm the page makes no cloud request. If storage is denied for local files, confirm the page displays its warning and document that resume is unavailable in that browser.

Player HTML structure and JavaScript parsing have unit-level assertions only. The checklist has not yet been performed. Real browser playback, seek, speed, storage persistence, missing-media rendering, audible output, and file-origin restrictions remain outstanding. Playwright's headless browser also mutes audio by default, so audible output needs a usable headed browser/audio device even after the launch restriction is resolved.

## Evidence from Phase 0 and Phase 1 work (2026-10-25)

- Fast suite: `.venv/bin/python -m unittest discover -s tests -v` — 15 tests run, 13 passed, 2 expected opt-in integration skips.
- Complete suite with integrations enabled: `SONARA_RUN_INTEGRATION=1 .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v` — 15 passed, no failures, skips, or resource warnings. This includes the generated extraction corpus and real Piper synthesis/WAV validation.
- CLI smoke after structured extraction was introduced: `sonara.py read` created `index.html` and mono, 16-bit PCM, 22,050 Hz WAV with 340,224 frames in a temporary directory.
- Extraction limits are 100 MiB input, 32 MiB captured bbox-layout output, 1 MiB diagnostic output, and 60 seconds. Unit tests verify input rejection, captured-output cap, and timeout termination.
- All six text-bearing fixtures matched expected content/order and the existing `pdftotext -layout` token order. The mixed document reports its image-only second page; an image-only PDF and malformed PDF fail clearly. Multi-column/table-like layouts receive a review note.
- PyMuPDF was reviewed from its official docs but not installed or benchmarked because it is absent and the package index was unreachable. See the evaluation note above.
- `pip check` reported no broken requirements; `compileall` completed successfully.
- Phase 0 browser verification remains blocked as described above; no audible playback, seeking, speed, or saved-progress behavior is claimed.
- At the Phase 0 baseline, Piper was one-shot with text in process arguments and had no timeout/cancellation. Phase 3 replaces the default path with a supervised persistent worker; the explicit executable override remains one-shot but uses a temporary input file. The Poppler bounds do not establish Piper long-document reliability.

## Phase 2 narration planner evidence (2026-10-25)

- Phase 2 first added `narration.py` as a standalone deterministic planner; Phase 3 now connects it to the default Piper path. It retains each block's original text across contiguous unit spans; `spoken_text` is separate and may collapse safe whitespace or apply explicitly recorded pronunciation substitutions.
- Current rules cover a finite set of English abbreviations, decimals, URLs/email addresses, terminal punctuation including Unicode ellipsis, quoted speech with common attribution, list markers, and closing punctuation. Headings stay whole; structural labels and pause durations are heuristic metadata.
- Scope warnings identify equations, citations, code, URLs, and uncommon abbreviations as cases requiring review. This ruleset is not claimed to support correct linguistic segmentation for every language or technical document.
- Phase 2 snapshot: focused narration module had 15 passing tests; the current totals are recorded in the Phase 3 section below.
- No browser verification was added by Phase 2; Phase 0 browser status remains open.

## Phase 3 TTS adapter evidence (2026-10-25)

- Verified `piper-tts==1.8.0` Python API (`PiperVoice.load`, `synthesize_wav`, and `SynthesisConfig.length_scale`) locally; no dependencies or model files were downloaded for this phase.
- Default CLI uses `PiperEngine` and `piper_worker.py`: model/config paths are process arguments, document text is sent through worker stdin JSON, and audio bytes stay in temporary WAV files. One model load serves each stream; sentence-like WAV chunks carry narration unit ID, source block ID, exclusive offsets, source text, spoken text, PCM format, and duration.
- Prefetch uses a bounded queue. Cancellation terminates the worker process, including in-flight inference. Model-load and per-unit synthesis timeouts are enforced. The current CLI combines chunks using bounded PCM reads and emits `audio_chunks.json`; it still waits for all chunks before browser playback.
- Piper capabilities report CPU, one configured model voice/language, mono PCM16 at the model sample rate, and speed range 0.5–2.0. Speed maps to reciprocal Piper `length_scale`. Emotion, phrase emphasis, speaker diarization, and GPU choice are explicitly unsupported by this adapter.
- Optional cache is caller-configured and keyed by document SHA-256, narration schema/ruleset, Piper runtime/model/config hashes, voice, speed, and unit source/spoken data. Cache corruption causes regeneration. No cache eviction policy is implemented yet.
- Cache/stream/error unit tests use a fake engine; real integration uses the local John medium model for chunk/WAV mapping, one model load, worker cancellation, corrupt-model error handling, and end-to-end PDF CLI output.
- Fast discovery: 41 tests run, 36 passed, and 5 opt-in integration tests skipped. Opt-in full suite: all 41 passed with `ResourceWarning` treated as an error. `compileall` passed. `pip check` passed with no broken requirements.
- CLI smoke: `.venv/bin/python sonara.py read /tmp/sonara-phase3-known-text.pdf --voice en_US-john-medium --data-dir ./models/piper --output-dir /tmp/sonara-phase3-reader` generated `speech.wav`, `index.html`, and `audio_chunks.json`. The WAV is mono PCM16 at 22,050 Hz, 333,056 frames (15.105 seconds); the manifest contains 5 source-mapped chunks. The test output was removed after inspection.
- The explicit `--piper` executable override and PATH fallback remain compatible, but use the legacy one-shot interface. Text is supplied through a short-lived UTF-8 file, never the process argument list.

## Phase 4 playback and cache evidence (2026-10-25)

- The player is generated with the document's chunk manifest. It keeps one `<audio>` element and changes its source per passage; global seeking maps to a passage index and local timestamp. The code handles play/pause/resume, playback rate 0.7–1.5, passage pause timers, retry/skip after media errors, and progress keyed to source SHA-256 plus narration ruleset. A storage-policy failure is displayed rather than treated as successful persistence.
- The CLI writes each generated chunk to `chunks/<document-sha256>/<run-id>/chunk-NNNNNN.wav` using atomic replacement, then writes the combined `speech.wav`, manifest and HTML player. When regenerating an output directory it removes only chunk paths named by the prior manifest and constrained beneath its `chunks/` directory. Tests cover that stale cleanup does not remove unrelated or outside paths.
- TTS prefetch remains bounded to two chunks in the CLI. The audio cache removes least-recently-used Sonara hash WAVs toward a 512 MiB budget at stream start and after cache writes. Current plan cache entries are protected to avoid evicting files needed by the active plan; that plan can therefore temporarily exceed the limit. This is a disk-cache bound for inactive entries, not a hard cap on active-plan disk use.
- Fast suite: `.venv/bin/python -m unittest discover -s tests -v` — 46 tests run, 41 passed, 5 opt-in integration tests skipped. `node --check` runs against the player script when Node is present and passed here.
- Opt-in real suite: `SONARA_RUN_INTEGRATION=1 .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -p 'test_integration_*.py' -v` — 5 tests passed, no failures or skips. This includes actual Poppler extraction, actual local Piper synthesis, worker cancellation/corrupt-model checks, audio format/mapping validation, and a generated player referencing each persisted chunk.
- Separate CLI smoke used `tests/fixtures/pdf_fixture.py` and the real installed Poppler/Piper path. Extraction exactly matched the expected text; CLI exited 0; five persisted chunks were present and referenced by the player; combined WAV was mono PCM16 at 22,050 Hz with 352,000 frames. Temporary smoke outputs were removed on process exit.
- `.venv/bin/python -m pip check` passed. CLI help describes the persistent active-Python worker and the executable/PATH fallback. Git status cannot be inspected because this workspace has an empty/unavailable Git repository; no Git metadata was changed.
- Browser verification remains blocked. A bounded `timeout 12s /usr/bin/firefox --headless --screenshot /tmp/sonara-firefox-check.png about:blank` attempt exited 1 with Snap's `snap-confine ... Refusing to continue` error. Therefore actual playback, pause/resume, seeking, rate behavior, storage round-trip/reload, missing-media recovery, and audible output remain unverified. The Playwright wrapper also remains unavailable in this environment. The existing manual checklist above is still required; Node syntax parsing does not substitute for a browser test.

### Phase 4 manual browser checklist

Use a generated `index.html` with the `audio_chunks.json` and chunk paths intact. In a named browser/profile, verify:

1. The first chunk loads and emits audible sound; then Pause stops sound and Play resumes.
2. Seek to the middle of a chunk and across a chunk boundary; verify the passage and local time are correct.
3. Change the speed control at several values and confirm audible rate changes.
4. Pause during a configured inter-passage delay and resume; verify the delay resumes without skipping a passage.
5. Let playback save progress, reload, and verify passage, offset, and rate restoration. Repeat from `file://` and record whether the browser permits local storage.
6. Rename a manifest-referenced WAV, reload, and verify the visible error; test Retry after restoring it and Skip when more passages remain.
7. Confirm final passage completion and that the page makes no network requests.

No browser checks above have been performed in this environment.

## Phase 5 Tauri desktop checks

The Tauri app is in `src-tauri/`; its plain HTML/CSS/JavaScript frontend is in `ui/`. It uses the locked Rust dependencies and does not need an npm package installation. The tested Linux environment has Rust/Cargo 1.98.0, GTK 3, WebKitGTK 4.1, Node 24, and Zenity 4.2.1. See the [official Tauri Linux prerequisites](https://v2.tauri.app/start/prerequisites/) before building on another machine.

Run these checks from the repository root:

```sh
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo check --manifest-path src-tauri/Cargo.toml --locked --offline
cargo test --manifest-path src-tauri/Cargo.toml --locked --offline
cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings
node --check ui/app.js
cargo run --manifest-path src-tauri/Cargo.toml --locked
```

The desktop runtime expects the repository's `.venv/bin/python`, `sonara.py`, and the John medium Piper model. Configure `SONARA_PROJECT_ROOT`, `SONARA_PYTHON`, and `SONARA_MODEL_DIR` to override them. The Linux file picker requires Zenity. Generated WAVs, session metadata, and progress are placed in Tauri's app-local-data directory. A random-token HTTP listener binds only to `127.0.0.1`; it serves only passage indexes from the active validated session, checks Host and canonical chunk-directory containment, supports byte ranges, caps each response at 64 MiB, and shuts down with the window. The app does not provide filesystem APIs or local paths to the frontend.

Evidence on 2026-10-25:

- `cargo check --manifest-path src-tauri/Cargo.toml --locked --offline` — passed; Tauri 2.10.3 and the full GTK/WebKitGTK dependency tree compiled. Cargo locked 452 packages; `src-tauri/Cargo.lock` pins the resolved graph.
- `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline` — 6 Rust tests passed, including token/path validation and byte-range handling for the loopback audio route.
- `cargo fmt --manifest-path src-tauri/Cargo.toml --check`, `cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings`, `node --check ui/app.js`, and JSON parsing of both Tauri configuration/capability files — passed.
- `timeout 15s cargo run --manifest-path src-tauri/Cargo.toml --offline` and the same command under `xvfb-run -a` — the binary compiled, then exited 101 because GTK could not initialize in this restricted session. The session advertises X11 and Wayland sockets, but direct Unix-socket connection probes to both X11 sockets and `wayland-0` returned `EPERM` (`Operation not permitted`) from the execution sandbox. The native window, Zenity interaction, playback, cancellation in the running app, and restart/resume were therefore not exercised. This is a host execution-boundary restriction, not a missing GTK/WebKitGTK dependency or a Sonara runtime setting.
- The real worker test originally failed because runtime discovery canonicalized `.venv/bin/python` to the system interpreter, which could not import Piper. Runtime discovery now preserves the venv Python symlink. The same integration test passed after the correction.
- A user smoke test then exposed WebKit media error 4 when loading the custom URI scheme. The Tauri player now uses an ephemeral token-authenticated loopback HTTP media URL instead. Static checks pass; a graphical retest is still required to confirm that the WebView can decode and play audio through this path.
- Loopback listener tests could not be run in this execution environment: even a local `127.0.0.1` bind returns `EPERM` here. The listener implementation is compile/lint tested, and route-token/range logic has Rust unit coverage; run the graphical smoke test outside this restricted environment.
- A user-launched desktop smoke test opened the window and completed synthesis. The resulting session had 33 nonempty WAV chunks with valid 22,050 Hz, mono, 16-bit PCM headers. The user reported that clicking Play produced no audio and no visible error. The player now reports media/network/ready-state details, signals loading/playing/waiting, times out stalled loads and play requests, and matches events by passage path if WebKit normalizes the URL. These diagnostics compile and pass the fast unit assertion, but playback itself still needs a user retest in the graphical application.
- Tauri bundling is disabled. The Python runtime, Piper runtime, and model are not bundled. Linux uses Zenity for native file selection; other operating systems are not supported by this first prototype.
- The Python CLI remains independently tested by the fast and opt-in suites above. No desktop end-to-end claim is made from that integration evidence.

## Phase 6 React interface and usability evidence (2026-10-25)

Phase 6 replaces the static prototype frontend with a modern, accessible React + TypeScript + Vite reader in `ui-react/`. It connects to the Tauri Rust core via typed IPC wrappers and includes keyboard navigation, audio specifications modal, speed presets, interactive passage dots, and document history.

### Testing commands

Run frontend tests from `ui-react/`:

```sh
cd ui-react
npm test              # Run all 31 Vitest unit/component tests across 8 test suites
npm run build         # Validate strict TypeScript compilation and Vite production bundle
npx tsc -b --noEmit   # Typecheck without emitting files
```

Run Rust core and backend checks from the project root:

```sh
cargo test --manifest-path src-tauri/Cargo.toml --locked --offline
cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings
```

Run Python test suite:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

### Evidence and test coverage

- **Vitest component & unit tests:** 10 test files, 42 tests passed in about 1 second.
  - `src/App.test.tsx`: 3 tests covering the honest first-run state, disabled browser-preview import, History navigation and Escape dismissal, Settings, and keyboard shortcuts.
  - `src/lib/history.test.ts`: 5 tests covering recent document persistence, deduplication by SHA-256, max history limit, corrupt data recovery, and clear history.
  - `src/lib/tauri.test.ts`: 5 tests covering API detection, missing-API errors, generic `pick_document`, `start_reading`, `cancel_reading`, `current_session`, `load_progress`, `save_progress`, and typed `synthesis-finished` event subscription/unsubscription.
  - `src/components/TopBar.test.tsx`: 3 tests covering branding, history counter badge, and navigation modal triggers.
  - `src/components/DocumentCard.test.tsx`: 4 tests covering idle, selected, synthesizing with progress track/cancel, and error states.
  - `src/components/PlayerCard.test.tsx`: 4 tests covering transport controls (Play/Pause), interactive passage dots with direct seek and tooltips, seek and speed sliders with ARIA range attributes (`aria-valuenow`, `aria-valuetext`), and error recovery buttons (Retry/Skip).
  - `src/components/ShortcutsModal.test.tsx`: 4 tests covering shortcuts cheatsheet, Escape key dismissal, backdrop click, and button click.
  - `src/components/SettingsModal.test.tsx`: 3 tests covering audio pipeline specifications (Piper ONNX CPU, 22.05 kHz 16-bit Mono PCM, ruleset v1, bearer-auth loopback), and speed presets (0.8×, 1.0×, 1.2×, 1.5×).
  - `src/components/HistoryDrawer.test.tsx`: 3 tests covering empty state, recent items with relative timestamps/durations, and clear history.
- **Strict TypeScript & Build:** `tsc -b --noEmit` and `npm run build` pass with 0 errors, outputting production bundle in `ui-react/dist/`.
- **Tauri Integration:** `src-tauri/tauri.conf.json` points `frontendDist` to `../ui-react/dist`, `devUrl` to `http://localhost:1420`, with `beforeBuildCommand: "cd ui-react && npm run build"` and `beforeDevCommand: "cd ui-react && npm run dev"`.
- **Accessibility & Design:** The React app uses a tokenized mineral light theme, system dark theme, responsive navigation rail, visible focus states, restrained transitions, reduced-motion support, and semantic labels. Existing playback shortcuts and modal behavior remain in place. No TailwindCSS was added.
- **Playwright/browser check:** Attempted against the built frontend. Chromium exits with `SIGTRAP` after Crashpad reports `setsockopt: Operation not permitted`; starting the Vite server also fails with `listen EPERM`. The browser could not render the app, so no implementation screenshot or Playwright interaction result is claimed. Native Tauri interaction still requires a graphical desktop session.

## Future benchmark protocol

No performance results have been established. For later benchmarks, record machine/OS, model revision, runtime/provider, precision, input text length, generated duration, and cold/warm state. Measure process/model startup, time to first audio, RTF (`synthesis wall time / generated audio duration`), peak RSS and VRAM if available, CPU/GPU utilization, chunk-latency variation, and interruptions during extended playback. Re-run the same fixed corpus and report measurements rather than estimates.

## Embedded llama.cpp validation (2026-10-28)

The embedded provider has mock-backed unit coverage for provider distinction, direct rather than HTTP dispatch, model-path checks, lazy construction, instance reuse, serialized concurrent first use, idle release/reload, missing runtime, inference failure recovery, and bounded document-context fallback without the HTTP embeddings path. The Settings component covers GGUF selection fields, model parameters, state display, and absence of a server endpoint.

Opt in to a real GGUF smoke test only when a small compatible chat model and `llama-cpp-python` are already available:

```sh
SONARA_LLM_TEST_MODEL=/path/to/small-chat-model.gguf \
  .venv/bin/python -m unittest \
  tests.test_llm_client.LlmClientTests.test_real_embedded_gguf_inference_reuses_and_reloads_without_server -v
```

This test does not download weights. It checks direct chat, loaded-instance reuse, idle expiration, and reload. The ordinary suite skips it unless `SONARA_LLM_TEST_MODEL` is set. Embedding-based retrieval is not enabled for the embedded provider; the no-server fallback is direct bounded context.

### Results observed during implementation

- `python3 -m py_compile llm_client.py tests/test_llm_client.py` — passed.
- `python3 -m unittest discover -s tests -v` — 87 tests run, 80 passed and 7 opt-in tests skipped.
- `cargo fmt --manifest-path src-tauri/Cargo.toml -- --check` — passed.
- `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline` — 9 Rust tests passed.
- From `ui-react/`, `npm test -- --run` — 47 tests passed; `npm run build` — strict TypeScript and Vite build passed.
- `cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings` — did not pass because the existing `spawn_sonara_worker` function triggers `clippy::too_many_arguments` (10 arguments). No clippy warning was attributed to the new LLM code.
- `llama-cpp-python` is not installed in either the system Python or project `.venv`, and no `SONARA_LLM_TEST_MODEL` was supplied. Therefore, actual GGUF loading, inference, RSS, cold load, latency, and memory release have not been verified in this environment. The opt-in real-model test remains to be run after installing `requirements-llm.txt` and selecting a local model.
- The GUI and system model file-picker interaction were not run in this headless session. Cross-platform Python runtime/model packaging is not validated.
