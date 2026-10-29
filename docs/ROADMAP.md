# Sonara — Repository Audit and Development Roadmap

**Planning status:** updated 2026-10-27 from repository inspection and checks recorded in `docs/TESTING.md`. This file is the project roadmap. It distinguishes implemented behavior from pending desktop acceptance and subjective listening evidence.

**Resource-efficiency update (2026-10-29):** a measured local baseline, bounded TTS profile selection, embedding-cache cap, and child-RSS-aware benchmark reporting are now implemented. The broader adaptive resource objective remains partial: custom profile controls, shared LLM/TTS workload arbitration, resource-monitoring UI, and concurrent/cancellation/shutdown workload measurements remain open. See `docs/BENCHMARKS.md` and `docs/TESTING.md`.

## A. Product objective

Sonara is intended to turn a document into a listenable, navigable reading session while preserving the document's wording, order, and structure. The long-term product may support PDF, DOCX, EPUB, and TXT; OCR; pronunciation overrides; multiple languages and voices; narration styles; sentence-level synchronization; local progress; and CPU or compatible GPU inference.

The first product should be narrower: a local desktop reader for searchable PDFs, with one verified local voice, reliable play/pause/seek/speed controls, saved progress, understandable errors, and no network dependency for document content or synthesis. It does not need OCR, voice acting, an LLM, a model marketplace, or every document format to be useful.

The application should favor extraction and audio correctness over advanced narration. Keep source text immutable. Any pronunciation or delivery change belongs in a separate, validated narration plan. Local processing is the default; model downloads must be explicit, attributable, and license-checked.

## B. Current implementation audit

### Repository and runtime evidence

- The workspace contains the Python CLI, React + TypeScript frontend (`ui-react/`), Tauri 2 core, tests, documentation, and local Piper models. There is no Python `pyproject.toml`; Python dependencies are in `requirements.txt`.
- Git metadata is present and `git status` works. The repository currently contains a mix of tracked and untracked files; use Git status/diff when making further changes.
- Host: Ubuntu Linux, x86_64, Intel Core i7-13620H (10 cores/16 threads reported), approximately 23.7 GB RAM. `rustc`/Cargo 1.98.0, C++ 15.2, CMake 4.2.3, Python 3.14.4, Node 24.20.0, npm 11.19.0, Poppler `pdftotext`, `ffplay`, and Zenity 4.2.1 are present. GTK 3 and WebKitGTK 4.1 are discoverable through pkg-config. Tauri compilation succeeds, but launch fails because GTK cannot initialize a display. Tauri CLI, pnpm, and Tesseract are unavailable; interactive browser behavior is not verified.
- NVIDIA driver communication fails, `/dev/nvidia*` and `/dev/dri` are absent, and this environment's ONNX Runtime reports `AzureExecutionProvider` and `CPUExecutionProvider`, not CUDA. CPU inference is verified; GPU inference is unavailable here and must not be claimed.
- The active `.venv` contains `piper-tts==1.8.0`, `onnxruntime==1.31.0`, and NumPy 2.5.4. `.venv`, Node dependencies, build output, model weights, generated audio, caches, Python bytecode, and local skill installations are covered by `.gitignore`; the Piper provenance README remains includable.

### Component status

| Component | Current status | Evidence inspected | Known limitations | Next required action |
|---|---|---|---|---|
| CLI and orchestration | **Implemented and verified** for the current narrow path | `sonara.py`; opt-in real PDF-to-Piper integration generates combined WAV, persisted passage WAVs, HTML player, and source-span chunk manifest | Default Python path synthesizes paragraph-sized passages with sentence pauses; explicit executable override remains one-shot; generation completes before player opens; output artifacts use fixed names | Verify player in a supported browser; later decide whether synthesis/playback overlap is required |
| PDF text extraction | **Implemented and verified** against deterministic corpus | `extract_pdf_document()` uses `pdftotext -bbox-layout`; six text-bearing generated fixtures match expected text/order and legacy `-layout` token order | Synthetic fixtures only; headings/lists are heuristics; tables remain text blocks; complex real layouts can be ambiguous and flagged for review | Add real, licensed user-like PDFs before claiming broader accuracy; compare PyMuPDF only if Poppler gaps justify its extra dependency/license |
| Shared document representation | **Implemented and verified** (schema v1) | `document.py`: `Document`, `DocumentBlock`, `SourceBox`, `ExtractionNote`; stable IDs, source hash, tool version, one-based page and PDF-point coordinates; JSON serialization | Default CLI passes blocks through narration planning and stores generated chunk offsets, but does not persist the complete extracted document; block kind labels are heuristic | Persist/render the full document when the reader UI is introduced |
| Piper inference | **Implemented and verified** on CPU | Persistent Piper Python worker; fast suite and listening-pack generation with local John medium voice; historical performance trial in `docs/BENCHMARKS.md` | CPU only; browser waits until synthesis completes; subjective quality has not been rated; executable override stays legacy | Complete blinded listener ratings; verify desktop playback; benchmark other engines only on this hardware |
| Voice files | **Present, hash-identified, and locally exercised; licensing review incomplete** | 63,531,379-byte `en_US-john-medium.onnx`; adjacent 4,965-byte JSON says `en_US`, one speaker, 22,050 Hz, medium; local SHA-256 matches upstream at revision `e70533d22ac02da609b7427dd1a8bd5349295e98`; model record at `models/piper/README.md` | Model card identifies LibriVox/public-domain source audio, but this does not settle artifact/runtime/phonemizer redistribution rights; original acquisition event is unknown | Review notices for the full shipped dependency/model stack before redistribution |
| Audio output | **Chunk output and WAV mapping implemented and verified** | Real output opened with Python `wave`: mono, 16-bit PCM, 22,050 Hz; integration verifies persisted per-unit WAVs and manifest mapping | Browser queue/underrun behavior not tested; generation completes before playback; cache protects active-plan entries and may temporarily exceed its inactive 512 MiB budget | Browser verification; assess synthesis/playback overlap only if latency/use requires it |
| Browser player | **Implemented; browser acceptance blocked** | `player_html()` schedules persisted chunks, maps global seek to passage/time, provides pause/resume/rate/pause timing/retry/skip, and stores per-document progress; Node parses generated JS; Firefox launch fails under Snap confinement | No real browser has verified playback, file-origin storage, seek/rate, restore, audible output, or media-error recovery | Complete manual/browser checklist in `docs/TESTING.md` in a usable browser/profile |
| Error handling and privacy | **Partially implemented** | Poppler limits; worker timeouts, structured failures, worker termination on cancellation; explicit text travels over stdin; stale-chunk cleanup is manifest-scoped | Fixed output names are atomically replaced; no full privacy audit; pause cannot stop synthesis because synthesis is completed before playback | Keep browser/output issues in scope for acceptance; broader privacy review later |
| Automated tests | **Fast suite and real PDF/Piper integrations pass; browser not tested** | Current fast and opt-in results in `docs/TESTING.md`; includes fake-engine bounded stream/cache tests and actual Piper chunk, cancellation, corrupt-model, WAV and CLI checks | Corpus is synthetic; no browser-level interaction or long-session playback/underrun test; audio output hardware is not exercised | Run outstanding browser checklist for Phase 0/4; add representative licensed PDFs when available |
| Narration and normalization | **Implemented and unit-tested; consumed by default CLI and desktop flow** | `narration.py` preserves source spans, applies reversible English abbreviation/unit rules, supports opt-in ISO date/citation expansion, emits structure-aware pause hints, and provides a spoken-text preview | English-focused finite rules; boundaries and pause durations are heuristics; equations/code and other languages need review; transformations are not quality-validated by listeners | Collect blind ratings, then tune rules only where ratings and pronunciation review justify changes |
| Blind listening evaluation | **Pack generator implemented; subjective evaluation pending** | `listening_eval.py` generated 24 randomized, RMS-matched clips (8 passages × voice-default/less/more) with separate participant and facilitator files | No listener ratings collected; RMS match is approximate, not LUFS; results depend on voice, playback equipment, and participants | Collect naturalness and intelligibility ratings before changing the default variation profile |
| Rust core, persistence, desktop backend | **Implemented in source; GUI playback retest pending** | `src-tauri/` Tauri 2 app; typed commands/events; Rust child supervision, token-authenticated loopback WAV server, and progress JSON; 9 Rust tests pass | A user observed media error 4 on the old custom URI; replacement HTTP transport has not been retested in the graphical app; bundling disabled | Relaunch on graphical Linux; verify media loading/playback and full controls/progress before package work |
| React desktop UI (Phase 6) | **Implemented and tested in source** | `ui-react/`: React 19 + TypeScript + Vite; typed Tauri IPC; 46 Vitest tests pass; production build passes; reader, narration preview, variation and normalization settings | Graphical desktop acceptance pending outside restricted sandbox; lint reports four React hook/ref warnings | Perform manual end-to-end user verification on graphical desktop and address lint warnings |
| GPU/native path | **Not yet evaluated on supported hardware** | No GPU devices/driver; installed ORT exposes CPU and Azure providers only | CUDA/DirectML/WebGPU support cannot be inferred from an ONNX model or package name | Baseline CPU first; separately test a real supported GPU/runtime pair before adding a backend |
| Git workflow | **Available** | `.git/` is initialized; `.gitignore` excludes local runtimes, build output, models, caches, audio, credentials, and installed local skills | Existing workspace has many untracked source files; do not assume they are committed | Review `git status` and stage intentionally when preparing a commit |

### What the current CLI actually does

`sonara.py` and `document.py` use Python standard-library code around the external tools. The PDF adapter runs Poppler `pdftotext -bbox-layout`, parses page/block/line/word boxes into schema-v1 `Document` objects, applies conservative block-kind hints, and emits notes for side-by-side order, repeated blocks, line-end hyphenation, and pages without selectable text. Input, output, diagnostics, and runtime are bounded. The CLI makes a deterministic narration plan, then the default Piper Python path uses a persistent worker to synthesize each plan unit into a temporary WAV chunk. It persists mapped chunk WAVs, also combines PCM into `speech.wav`, writes source offsets/durations to `audio_chunks.json`, then creates a static player that schedules the chunks sequentially. An explicit `--piper` executable override remains one-shot and receives a temporary text-file path.

Inference is not simulated: the installed Piper/ONNX Runtime loaded the included ONNX voice and emitted real WAV chunks in the current integration tests. The model option resolves to `<data-dir>/<voice>.onnx` and its adjacent JSON configuration. The worker keeps one `PiperVoice` loaded for the session; the main CLI supervises it and validates the returned PCM files.

The CLI does **not** overlap synthesis and playback or persist the complete extracted document object. The desktop shell opens documents via native selection and stores progress in app-local data. Desktop media playback still requires graphical retest; the standalone browser player also remains unverified in a supported browser.

### Known gaps carried forward

- Phase 0 remains open because browser playback/progress checks could not run in the restricted environment; see `docs/TESTING.md`.
- The corpus is deterministic and self-authored, not a substitute for real research papers, complex tables, or multi-column publisher PDFs.
- PyMuPDF's official API/license were reviewed, but local installation and head-to-head measurement were blocked by unavailable package index access. It is not a runtime dependency; Poppler bbox output was compared to Poppler layout mode.
- Human listening ratings have not yet been collected for the generated variation comparison pack.

## C. Minimum viable product

### Release choice

Treat the current CLI plus generated HTML as a **developer alpha and pipeline harness**, not the MVP product. The first usable release should be a **small local desktop prototype**, not a complete library/history application. Sonara is intended as a document reader; a browser file page is useful for validating synthesis but does not yet establish reliable document opening, progress restoration, scoped file access, or an installable user experience.

Build that small desktop shell only after a repeatable integration test proves the Python/Piper PDF path and the playback behavior. Keep the CLI as a fast diagnostic and regression interface rather than rewriting it away.

### MVP capability and completion bar

1. User opens a searchable PDF through an application-controlled picker.
2. Extraction produces ordered text blocks and retains page/source locations for synchronization.
3. The app uses one locally installed, license-reviewed Piper voice to generate actual speech.
4. Audio plays with play/pause, seek, and adjustable playback speed.
5. Reading position is saved and restored after closing/reopening the document and app.
6. Missing tools/model, malformed/unsupported PDFs, empty/scanned PDFs, synthesis failures, and cancellation show recoverable messages.
7. Text and audio stay local; there is no automatic upload or document-content logging.
8. Setup, model acquisition, deletion, supported platforms, and known limitations are documented.

For the MVP, “preserving content” means passage coverage can be checked against the extracted source and no summarization or rewriting occurs. Sentence highlighting, OCR, DOCX/EPUB/TXT, multi-voice dialogue, cloud services, and emotion controls are intentionally outside MVP scope.

## D. Development phases

There are no calendar estimates. Follow the dependency order and finish each phase's acceptance checks before treating its output as stable.

### Phase 0 — Verified baseline and reproducible test harness

**Priority:** first. **Objective:** turn the PDF-to-Piper smoke path into repeatable evidence and verify browser/audio behavior. **Status: partially complete; browser acceptance remains outstanding.**

- **Tasks:** preserve the existing simple PDF-to-Piper command; create a small generated PDF fixture with known text; add opt-in tests using installed Poppler/Piper and the local model; assert extracted text, WAV encoding/duration, generated player contents, and recoverable failures. **Done:** generated fixture and opt-in real extraction/synthesis test pass; WAV structure is checked; CLI help now matches module/fallback/override behavior; pinned dependencies and model hashes/upstream revision are recorded; setup/testing docs and actionable player failure messages are present. **Outstanding:** run the HTML player in a real browser to verify actual playback, seeking, speed, progress save/restore, missing-audio error, and local-file storage behavior.
- **Prerequisites:** installed Poppler, `.venv`, Piper 1.8.0, John medium voice, browser with WAV support. Browser automation dependency is not currently verified.
- **Deliverables:** fast unit suite; opt-in integration test; deterministic stdlib PDF generator and expected text; dependency manifest; model provenance/hash record; environment and browser test instructions.
- **Acceptance:** **passed:** fast tests pass without model loading; opt-in integration invokes real Poppler/Piper and verifies exact text and nonempty valid WAV; missing prerequisites skip with actionable reasons; CLI help and pinned environment are checked. **Not yet passed:** a real browser verifies audible playback, seek/rate changes, progress save/restore, and missing-media/local-storage failure behavior. Phase 0 is not complete until the latter checks are run.
- **Tests:** `python -m unittest discover -s tests -v`; opt-in `SONARA_RUN_INTEGRATION=1 python -m unittest discover -s tests -p 'test_integration_*.py' -v`; browser checklist in `docs/TESTING.md`.
- **Risks:** audio hardware may be unavailable in CI; browser `file:` storage differs by engine; synthetic PDFs do not represent complex layouts.
- **Definition of done:** anyone with documented prerequisites can reproduce extraction and synthesis without implicit downloads, and actual browser behavior is verified in at least one named browser/profile. A documented blocker keeps this phase open; it does not substitute for the browser acceptance test.

### Phase 1 — PDF correctness and shared document representation

**Priority:** before UI synchronization or multi-format work. **Objective:** stop treating a document as one unlocated string. **Status: complete for the Poppler-backed baseline and generated acceptance corpus.** Phase 0 browser checks remain separately open.

- **Tasks completed:** defined schema-v1 `Document`, `DocumentBlock`, `SourceBox`, and `ExtractionNote`; added Poppler `-bbox-layout` parsing with stable IDs, page dimensions and point boxes; kept `extract_pdf()` as the plain-text compatibility path; added conservative heading/list/quote/footnote labels with `kind_source`; reported possible columns/tables, repeated passages, line-end hyphenation, and textless pages; bounded PDF size, extractor output/diagnostics, and runtime; built a deterministic corpus; compared `-bbox-layout` against old `-layout` text order. Reviewed PyMuPDF's structured API and license; it is absent locally and PyPI access failed, so no independent-engine run was possible or needed to retain Poppler for this baseline.
- **Prerequisites:** the Phase 0 generated fixture and real Poppler integration exist. Browser acceptance for Phase 0 remains open but is not required for source extraction.
- **Deliverables:** `document.py` schema/parser; corpus manifest/generator in `tests/fixtures/pdf_corpus.py`; exact expected content and warning checks; extraction notes and resource bounds.
- **Acceptance:** **passed for the generated corpus:** each of six text-bearing fixtures matches expected text/order/page count, source page boxes, and deterministic IDs; token order matches legacy `-layout`; repeated text remains intact with a warning; columns/table-like side-by-side content is flagged; mixed text/image page reports page 2; image-only and malformed PDFs fail clearly; configured size/output/time caps have tests. **Scope limit:** synthetic fixtures do not establish accuracy on arbitrary publisher PDFs; PyMuPDF was not installed/executed.
- **Tests:** fast suite, real Poppler corpus integration, real Poppler/Piper/WAV integration, malformed/image-only cases, and unit limit tests. See the exact commands and results in `docs/TESTING.md`.
- **Risks:** PDF structure is visual rather than semantic; tables/headings can be misclassified; reading order cannot be guaranteed; Poppler bbox and layout share an extraction engine so their comparison is not independent. Real-world corpora and an independent parser remain possible follow-up experiments.
- **Definition of done:** a versioned source-mapped document object is produced for the tested PDF corpus, extraction issues are visible, limits fail safely, and the existing simple PDF-to-Piper CLI continues to work. This criterion has passed on the named generated corpus.

### Phase 2 — Deterministic narration plan

**Priority:** after block schema; before chunked generation. **Objective:** make pauses and transformations traceable without changing meaning. **Status: implementation complete for the current English rules; listening validation remains open.**

- **Tasks completed:** added `narration.py` with versioned plan/unit schemas, stable IDs, ordered source-block IDs, and exclusive source offsets; normalizes safe whitespace only in spoken text; segments punctuation with abbreviation, decimal/URL, list, closer, and dialogue-attribution handling; preserves original source and offsets. Conservative English rules cover common abbreviations and units; ISO dates and numeric citations are opt-in. Every transformation records its original substring and offsets. The desktop app previews source and spoken versions. Pause hints now account for punctuation, block kind, and block boundaries. No LLM or new NLP dependency was added.
- **Prerequisites:** Phase 1 source locations and stable block IDs.
- **Deliverables:** versioned narration-unit schema and deterministic planner in `narration.py`; behavioral contract in `docs/ARCHITECTURE.md`; unit fixtures in `tests/test_narration.py`.
- **Acceptance:** **passed in unit tests:** source coverage remains contiguous and exact; source text is unchanged; transformations and opt-ins are tested; preview is bounded; unsupported languages do not receive English rules; explicit invalid/overlapping overrides fail. Pause policy is tested as deterministic metadata. **Listening quality remains unverified.**
- **Tests:** abbreviation/decimal/URL/email/punctuation/ellipsis/closing quote cases; heading/list/quote/dialogue hints; Unicode and multilingual text preservation; multi-block exact coverage and deterministic boundary-case coverage; whitespace/hyphenation; override case, boundaries, collisions, and serialization. Fast full suite passes with opt-in integrations skipped; real Poppler/Piper verification is separate and does not exercise this planner.
- **Risks and limits:** this is deterministic punctuation and normalization logic, not robust linguistic parsing. It can mis-handle equations, code, initials, unfamiliar abbreviations, dates/citations outside the opt-in patterns, and non-English text. Dialogue labels and pauses are hints, not voice or emotion direction. Human listeners must assess pronunciation and cadence.
- **Definition of done:** an inspectable, deterministic plan exists with contiguous source coverage, unchanged source, separate reversible pronunciation text, and tests for declared boundaries and unsupported cases. This criterion has passed for the listed unit cases; it does not establish listening quality.

### Phase 3 — Replaceable, persistent TTS adapter and chunk synthesis

**Priority:** after narration boundaries; before continuous playback. **Objective:** replace one-shot command generation with reusable model state and bounded audio chunks. **Status: complete for the default local Piper Python path; streaming is available to callers, while live browser playback remains Phase 4.**

- **Tasks completed:** added the engine/audio/chunk contract and `PiperEngine`; the persistent worker loads the selected Piper voice once and accepts text over stdin JSON lines. It now leaves `noise_scale` and `noise_w_scale` unset for the default profile so voice-specific config values apply. Optional `less` and `more` profiles scale those values relative to voice defaults; they are experimental and do not control pitch or emotion. Speed maps to `length_scale`; unsupported controls remain explicit. Bounded mapped WAV chunks, cancellation/timeouts, and source/runtime/model-aware cache remain in place.
- **Prerequisites:** Phase 2 chunks, Phase 0 integration coverage, license record.
- **Deliverables:** `tts_engine.py` contract/stream/cache, `piper_worker.py` persistent model worker, default CLI integration, PCM/source mapping manifest, and opt-in real-model tests.
- **Acceptance:** **passed:** real Piper integration verifies one model load per stream, one-to-one source mapping, bounded first-chunk availability, process termination on cancellation, actionable corrupt-model failure, cache hit/invalidation/corrupt-cache recovery, WAV format, and end-to-end PDF CLI manifest.
- **Tests:** fake-engine stream/error/cache tests; local Piper API tests for chunk audio/source mapping, cancellation, and corrupt model; existing real PDF/Poppler/Piper CLI integration. Exact commands/results are in `docs/TESTING.md`.
- **Risks and limits:** CPU only. Historical performance measurements exist, but they do not establish subjective speech quality. The HTML/desktop flow waits for synthesis to complete before playback. Piper runtime and voice terms affect redistribution.
- **Definition of done:** the default CLI uses narration units through a replaceable contract; real Piper reuses one model per session, yields bounded/mapped chunks with explicit capabilities and format, and demonstrates error/cancellation behavior. This criterion passed on the local CPU and included voice.

### Phase 4 — Playback, seeking, cache, and durable progress

**Priority:** after the Phase 3 chunk contract. **Objective:** make generated chunks a reliable listening session. **Status: implementation and automated evidence added; acceptance remains open because browser behavior and listening have not been verified.**

- **Tasks completed in current implementation:** static HTML player schedules one persisted WAV per passage; global seek maps through manifest durations to passage/time; play/pause/resume and rate controls; pause timers use manifest metadata; load failures expose retry/skip; progress and rate save by source hash/ruleset; manifest-owned stale chunks are removed safely; cache LRU pruning targets a 512 MiB inactive-cache budget; JS syntax and generated chunk references are checked.
- **Prerequisites:** Phase 3 chunk/audio contract passed. Phase 0 real-browser acceptance remains open and is also required evidence for this phase.
- **Deliverables:** generated-chunk browser player, recoverable passage state, source-mapped progress, bounded synthesis prefetch, inactive audio-cache cleanup.
- **Acceptance:** **automated/code checks passed:** generated JS parses; real Poppler/Piper CLI creates valid persisted mapped chunks; control/error/progress code paths are present; fake-engine tests cover bounded prefetch, cache/error/cancellation; manifest cleanup is constrained. **Still unverified:** actual playback, seek target, pause/resume timing, speed audibility, failed-media retry/skip, storage save/reload across app restart, and long-session browser memory/interruptions. The CLI synthesizes the whole document before opening the player, so browser pause does not halt synthesis queue growth; synthesis/playback overlap is not implemented.
- **Tests:** current commands/results in `docs/TESTING.md`; Node script syntax, fake-engine queue/cache/errors/cancellation, real WAV/manifest integration; remaining: browser interaction, actual progress round-trip, missing-media recovery, extended playback soak, manual listening.
- **Risks:** browser restriction blocks acceptance; file-origin storage differs by browser; autoplay policy and audio clock drift; pause is not coupled to synthesis; long-duration memory/interruptions not measured.
- **Definition of done:** **not yet met.** A named supported browser must demonstrate continuous audible chunk playback, correct seek/rate, pause and recovery, saved progress after reload, and acceptable long-session behavior. Document whether playback should overlap synthesis before Phase 5.

### Phase 5 — Rust/Tauri application core and narrow desktop MVP

**Priority:** after the data/audio contracts stabilize. **Objective:** provide a secure local desktop application without rewriting functioning Python inference. **Status: desktop source and worker integration implemented; acceptance remains open because GUI launch and end-to-end desktop interaction could not be verified in this headless environment.**

- **Tasks implemented:** added a Tauri 2.10.3 app and React/TypeScript frontend; Rust commands/events for PDF, TXT/TEXT, Markdown, DOCX, and EPUB selection, synthesis start/cancel, current session, and validated progress save/load; Python process supervision with Unix process-group shutdown; app-local audio/session/progress storage; manifest-index validation; token-authenticated HTTP audio serving on an ephemeral `127.0.0.1` port with Host/path validation, range support and a 64 MiB cap; restrictive frontend CSP/capabilities and no filesystem API; pinned Cargo manifest/lock. The UI offers document selection, prepare/cancel, play/pause, seek, speed, pause timing, retry/skip, and saved progress.
- **Prerequisites:** phases 1–4 contracts are available, but Phase 4's real-browser acceptance remains open. Rust 1.98, GTK3, WebKitGTK 4.1, Node 24, and Zenity 4.2.1 are available. Native picker commands are implemented for Linux, macOS, and Windows; only Linux has been compiled and exercised here.
- **Deliverables:** source-level one-window desktop prototype and locked, offline-resolvable Rust dependencies. Bundling is disabled; Python, Piper, and voice model are external.
- **Acceptance:** **passed:** offline Rust tests (9 tests on 2026-10-27), formatting, and automated Python worker/CLI checks; no frontend filesystem API; the loopback server restricts access to a random token, exact Host, active session hash/index, and canonical chunk directory. **Not verified:** replacement HTTP transport in Tauri WebView, actual playback/seek/rate, cancellation/window-close during a desktop job, restart progress restore in the app, and a clean packaged install. User reported media error 4 before the transport change; graphical retest is pending.
- **Tests:** `cargo fmt --manifest-path src-tauri/Cargo.toml --check`; `cargo check --manifest-path src-tauri/Cargo.toml --locked --offline`; `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline`; `cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings`; `node --check ui/app.js`. Results and the GUI limitation are in `docs/TESTING.md`.
- **Definition of done:** **not yet met.** On a supported graphical Linux environment, open the native picker, process the real fixture through Poppler/Piper, play/seek/change rate, close and cancel safely, then relaunch and verify persisted progress. Decide packaging/runtime/model distribution and review notices before enabling bundles.

### Phase 6 — React interface and product usability

**Priority:** build only after the desktop command/event contracts are stable. **Objective:** provide an accessible, navigable reader UI. **Status: implemented and automated checks pass; graphical desktop acceptance remains pending.**

- **Tasks completed:**
  - Introduced React 19, TypeScript ~6.0, and Vite 8.3 in `ui-react/` within Tauri's configuration (`src-tauri/tauri.conf.json`).
  - Implemented typed Tauri IPC bindings (`src/lib/tauri.ts`) mirroring Rust commands and events (`pick_document`, `start_reading`, `cancel_reading`, `current_session`, `load_progress`, `save_progress`, `synthesis-finished`).
  - Implemented core application hook (`src/hooks/useSonara.ts`) encapsulating synthesis lifecycle, token-authenticated HTTP playback, error handling with retry/skip, throttled progress persistence, interactive passage dots, and global keyboard shortcuts.
  - Built accessible UI components:
    - `TopBar`: Branding, local-only status with animated pulse dot, document history badge, settings modal trigger, and keyboard shortcuts guide trigger.
    - `DocumentCard`: Document picker with native file dialog integration, status/error reporting, animated synthesis progress track, and worker cancellation.
    - `PlayerCard`: Audio transport controls (Play/Pause), interactive passage dots with direct seek and duration tooltips, seek and speed sliders with ARIA range attributes (`aria-valuenow`, `aria-valuetext`), live status display, and error recovery buttons.
    - `ShortcutsModal`: Accessible keyboard cheatsheet dialog (`Space/K`, `←/J`, `→/L`, `↑/]`, `↓/[`, `Home`, `End`, `?`, `Esc`).
    - `SettingsModal`: Voice and playback settings, voice-default/less/more Piper variation, opt-in ISO-date and citation expansion, narration privacy explanation, spoken-text preview entry point, and audio/runtime information.
    - `HistoryDrawer`: Recent documents list persisted in local storage (`sonara_recent_documents`), formatted timestamps, passage counts, durations, and clear history option.
  - Implemented vanilla CSS design system (`src/index.css`) with glassmorphism, lime-green accents, micro-animations, reduced-motion queries, and responsive layout without TailwindCSS.
- **Prerequisites:** Phase 5 backend contracts and verified playback.
- **Deliverables:** Accessible React reader, audio controls, voice/speed and variation settings, narration normalization options/preview, document history, keyboard shortcuts guide, and 46 Vitest component/unit tests.
- **Acceptance:**
  - **Passed (2026-10-27):** `npm test` — 46 tests across 11 files; `npm run build` — TypeScript and Vite build; `cargo test` — 9 Rust tests; Python fast suite — 77 passed, 6 opt-in skips. `npm run lint` completes with four React hook/ref warnings. Graphical desktop acceptance remains pending.
  - **Unverified (environment restriction):** End-to-end interactive GUI testing in a graphical desktop session (sound output hardware and GTK display are unavailable in headless sandbox).
- **Tests:** `cd ui-react && npm test`; `cd ui-react && npm run build`; `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline`; `.venv/bin/python -m unittest discover -s tests -v`.
- **Definition of done:** MVP flow is accessible and error states are understandable; automated tests cover state and components; graphical desktop acceptance pending outside restricted sandbox.

### Phase 7 — DOCX, EPUB, TXT, and OCR expansion

**Priority:** after the PDF MVP; do not delay first usable speech for every format. **Objective:** add formats through the same block contract. **Status: complete for multi-format extraction and pluggable OCR architecture.**

- **Tasks completed:**
  - Added native plain text extraction (`extract_txt_document` in `document.py`) with automatic multi-encoding detection (`utf-8`, `utf-8-sig`, `latin-1` fallback), paragraph splitting, and Markdown/quote/list heuristics.
  - Added native Microsoft Word extraction (`extract_docx_document`) using standard library `zipfile` and XML parsing of `word/document.xml`, extracting paragraphs, headings (`w:pStyle`), list markers, and table cells in sequential reading order without heavy/AGPL external dependencies.
  - Added native EPUB extraction (`extract_epub_document`) via standard library `zipfile` resolving `META-INF/container.xml`, reading OPF package manifest and spine itemrefs, and extracting clean XHTML text blocks.
  - Added unified dispatcher `extract_document(path)` in `document.py` and `sonara.py`.
  - Added cross-platform desktop document picking in `src-tauri/src/lib.rs` supporting `.pdf`, `.txt`, `.docx`, `.epub` across Linux (Zenity with Kdialog fallback), macOS (osascript), and Windows (PowerShell Forms).
  - Updated React frontend (`ui-react`) copy and components to support general documents.
  - Added pluggable OCR adapter (`ocr.py`) with `pdftoppm` rendering, `tesseract` TSV parsing into schema-v1 blocks, DPI-to-point coordinate scaling, local disk caching per page hash, and helpful installation guidance when Tesseract is absent.
- **Prerequisites:** Phase 1 document schema.
- **Deliverables:** Format extractors in `document.py`, pluggable OCR module in `ocr.py`, test suites in `tests/test_document_formats.py` and `tests/test_ocr.py`, updated Tauri backend and React reader.
- **Acceptance:**
  - **Passed:** TXT, DOCX, EPUB, and OCR unit tests are included in the current Python suite; current overall test evidence is recorded in `docs/TESTING.md`.

### Phase 8 — Model evaluation, multilingual/expressive scope, performance, and distribution

**Priority:** ongoing after an end-to-end application exists. **Objective:** improve voice quality and portability using evidence rather than assumptions. **Status: performance baseline and packaging strategy documented; blind listening pack implemented; Kokoro evaluation, human ratings, and packaging verification remain open.**

- **Tasks completed:**
  - Implemented repeatable benchmark script (`benchmark.py`) measuring cold model load time, Time to First Audio (TTFA), Real-Time Factor (RTF), and peak RSS memory across a standardized test corpus.
  - Historical local performance baseline across four Piper voices is recorded in `docs/BENCHMARKS.md`. The original reported measurements use the earlier four-passage latency corpus; they are not a listening-quality evaluation.
  - Added an eight-passage corpus and `listening_eval.py`, which generates randomized, RMS-matched voice-default/less/more clips and separates participant ratings from the facilitator key. A 24-clip pack was generated on the local John voice; ratings have not yet been collected.
  - Piper now respects each voice's configured synthesis defaults unless a user explicitly selects a comparative variation profile. The default remains the voice config pending blind listening results.
  - **Implemented, pending full evaluation:** Kokoro-82M is available as an optional `SpeechEngine`; do not change the Piper default without a blinded, matched-level listening result.
  - Published comprehensive benchmark and architectural comparison report in `docs/BENCHMARKS.md`, analyzing Piper vs. Kokoro-82M vs. XTTS-v2.
  - Authored comprehensive packaging and distribution guide in `docs/PACKAGING.md` covering standalone Python runtime bundling, Linux `.deb`/AppImage, macOS `.dmg`, and Windows NSIS installers.
  - Configured Tauri bundle metadata (category, descriptions, copyright) in `src-tauri/tauri.conf.json`.

### Phase 9 — Local LLM runtime and semantic document retrieval

**Priority:** after the graphical reader flow is verified. **Objective:** make the document assistant useful on long documents while keeping local inference and cloud-provider behavior explicit. **Status: initial integration implemented; model-backed llama.cpp validation and supervised server lifecycle remain open.** Sonara exposes llama.cpp as a distinct loopback provider and uses `/v1/embeddings` for local top-k passage retrieval with a disk cache. Kokoro is an optional `SpeechEngine`; its runtime and model assets are installed locally and the Python CLI completed a smoke synthesis. The Tauri desktop flow and listening evaluation remain unverified.

#### Phase 9.1 — llama.cpp local assistant provider

- **Implemented:** `llm_client.py` supports a dedicated llama.cpp provider, loopback-only endpoint validation, configurable endpoint/model, and chat/summarization over an externally started compatible server. Settings provides the default endpoint `http://127.0.0.1:9931/v1`. API keys are removed from persisted WebView storage and remain session-only.
- **Implementation:** support a user-installed GGUF model and local `llama-server`, bound to `127.0.0.1`. First test chat and summaries via the existing custom endpoint. For an integrated runtime, Rust should launch and supervise the server, check `/health`, handle port conflicts and cancellation, report model loading/availability, and shut it down with the app. Keep filesystem tools disabled and do not expose the server on the LAN.
- **Privacy follow-up:** credentials are no longer persisted in WebView `localStorage`; they remain in frontend memory for the current app session and are sent only with the relevant request. An OS-protected/native credential store and per-operation cloud disclosure are still needed before treating cloud credentials as production-ready.
- **Narration polish gap:** `llm_enhance_script` exists in the Rust/Python command path, but the settings toggle currently only affects UI state/badge; it is not connected to the synthesis flow. If implemented, analyze bounded narration units, validate structured suggestions, preserve source offsets, show a source/spoken preview, and require user approval before applying changes. Do not allow generated prose to silently replace source text.
- **Acceptance:** local server startup/readiness/failure/shutdown works; chat is grounded in the open document; requests are bounded, cancellable, and do not freeze the app; local mode never silently falls back to a cloud endpoint; cloud use clearly discloses the provider and data being sent; credentials are not persisted in WebView storage.

#### Phase 9.2 — Local semantic retrieval with an embedding model

- **Objective:** replace the current first-N-character context truncation with retrieval of relevant passages for long-document questions. Embeddings are for search/retrieval, not speech synthesis.
- **Implemented, unvalidated:** llama.cpp requests use `/v1/embeddings`; Settings accepts an embedding-model alias and optional separate loopback embedding endpoint. Paragraph-aligned snippets are embedded, cached locally by endpoint/model/source text, ranked by cosine similarity, and passed to the assistant with passage labels. **Remaining:** retrieval currently lacks source-block IDs, offsets, and page/section metadata; it has no cache-management UI or fixed-corpus relevance evaluation, and requires the user to run an embedding-enabled local server/model.
- **Storage:** begin with a small per-document local index or exact cosine search for the existing single-active-document workflow. Defer SQLite/vector extensions until a multi-document library and measured index size justify persistent vector queries.
- **Acceptance:** tests prove correct indexing/invalidation, stable source offsets, relevant retrieval from early and late document sections, source-linked answers, no network access in local mode, and recoverable missing-model/index errors. Compare retrieval quality on a fixed question/answer corpus before enabling it by default.

#### Phase 9.3 — Kokoro-82M alternate narration engine

- **Current constraint:** Kokoro is optional and requires a Python environment supported by `kokoro-onnx` (Python 3.10–3.13 in the package information reviewed) and locally placed model files. The current tested environment is Python 3.14.4. No files are downloaded automatically.
- **Implemented:** `KokoroEngine` is available behind the existing `SpeechEngine` contract; CLI and Tauri expose the engine and voice choice, preserve narration source mapping, use the sample rate returned by the runtime, and include model/voice/runtime in cache identity. Python 3.12, `kokoro-onnx`, and the v1.0 model/voice assets are installed. Direct adapter synthesis and CLI reader-manifest smoke checks passed at 24 kHz. The UI gives the asset setup location. **Still unverified:** Tauri desktop playback and blind listening comparison.
- **Evaluation:** extend `listening_eval.py` to randomize identical passages across Piper voice defaults and selected Kokoro voice(s), match levels, and collect naturalness and intelligibility ratings. Do not interpret latency, model size, or architecture as proof of a more human voice. Keep Piper as the default unless blinded listening shows a clear, repeatable preference without unacceptable intelligibility or latency regressions.
- **Remaining acceptance:** install a compatible runtime and reviewed Kokoro assets, run real Tauri playback/audio-format checks, implement in-flight cancellation, and complete blinded matched-level Piper/Kokoro listening evaluation before selecting defaults. For llama.cpp, add lifecycle supervision, model-backed chat/embedding validation, source offsets and navigable citations, cache management, and fixed-corpus retrieval evaluation. Kokoro remains optional and Piper remains default until acceptance passes.

- **Environment limits:** llama.cpp is now run as an externally managed CPU server; Kokoro runs through a separate Python 3.12 environment on this CPU-only host. Record runtime, model revision, quantization, memory, cold start, first audio, generation speed, and user-perceived quality on this hardware before selecting defaults.
- **Technical references:** [Kokoro Python package requirements](https://github.com/hexgrad/kokoro/blob/main/pyproject.toml), [official Kokoro JavaScript/ONNX usage](https://github.com/hexgrad/kokoro/blob/main/kokoro.js/README.md), and [llama.cpp server and embeddings API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

### Phase 10 — Resource usage and efficiency

**Priority:** high, before expanding local model features. **Objective:** reduce Sonara's CPU, RAM, and storage footprint while keeping narration responsive and output quality intact. The user reports that current usage is too high. A recent llama.cpp launch log showed a 40,960-token context, four parallel slots, and a 5,760 MiB KV cache, alongside a 4,762 MiB mapped model buffer and 3,199 MiB CPU repack buffer. Treat these as observed allocations for that configuration, not a universal Sonara baseline.

- **Measure by workload:** capture per-process and whole-app CPU/RSS for idle, document extraction, Piper/Kokoro loading and synthesis, llama.cpp chat, embedding/index creation, playback, cancellation, and shutdown. Separate cold-start from warm steady-state numbers and record document size, model, context, parallelism, runtime, and hardware.
- **Tune llama.cpp defaults:** expose or document context length and parallel-slot controls; measure smaller contexts and one slot against response quality, latency, and peak RAM. Avoid the current 40k/four-slot configuration as a silent default on memory-constrained laptops. Never change user-managed server settings behind their back.
- **Bound background work:** keep TTS prefetch and embedding batches bounded; avoid embedding unchanged passages again; prune local audio and vector caches under configurable budgets; ensure cancel/close releases buffers and workers.
- **Load models intentionally:** reuse a loaded model during a reading session, avoid duplicate simultaneous engine instances, and add idle unload/shutdown only where the lifecycle is owned by Sonara. For externally managed llama.cpp servers, provide clear instructions rather than claiming Sonara can reclaim their memory.
- **Add a low-resource path:** provide practical CPU-conscious settings and explain their trade-offs in the UI. Keep model and quality choices explicit; don't switch to lower quality silently.
- **Acceptance:** establish target-hardware budgets for idle and active RAM/CPU; document p50/p95 cold and warm measurements; demonstrate bounded memory during a long document and embedding job; verify no UI freeze, playback underrun, or leaked worker after cancel/exit; compare output intelligibility before and after tuning. Set numeric budgets only after collecting this baseline.

## E. Architecture evolution

### Keep the current path Python-based initially

The Python code is small, and real Piper inference already works in this environment. Keep it as the first implementation path and CLI regression tool. Do not rewrite the PDF or TTS flow into Rust before tests and contracts show what must cross that boundary. Python is a good fit for model experimentation, NLP prototyping, and the Piper API; it is not currently used for PDF parsing beyond subprocess orchestration.

### Introduce Rust when lifecycle and application state require it

Rust becomes valuable when Sonara needs a native app boundary, file-picker security, cancellation, task ownership, cache/progress state, and bounded playback coordination. Use Serde for small typed request/status payloads. Tokio can coordinate asynchronous tasks, but blocking inference should be isolated; Tokio documents that `spawn_blocking` tasks cannot be aborted once running, so cancellation should supervise/terminate a worker process or use a cooperative engine API. Don't add Tokio simply to wrap a synchronous single-shot CLI.

SQLite is a local single-user fit once multiple documents, history, settings, and progress need durable queries. Start with the smallest suitable Rust SQLite binding; SQLx is async and useful when async database workflows/compile-time checked queries justify its setup. No database is needed for the current one-document static player.

### Keep Python as one local worker, not a service mesh

If Rust owns the app and Piper remains Python, run one supervised local worker that reuses its loaded model. Do not launch one model process per sentence. Use an explicit protocol, cancellation, and bounded buffers; keep PCM audio out of JSON/base64. A single child process is justified by the inference dependency and fault boundary. FastAPI/HTTP is unnecessary unless a second local client or independently managed API appears.

### Defer C/C++ until a measured boundary warrants it

The current ONNX Runtime already executes optimized native kernels; no evidence points to custom kernels as a bottleneck. Piper publishes a C-style library API, but switching from its Python integration adds build/runtime distribution and license complexity. Consider that API only if profiling shows Python/CLI overhead or deployment constraints are material. Use CMake and a stable C ABI if a native adapter is then needed; do not write inference kernels preemptively.

### Add desktop UI after contracts stabilize

Tauri 2 fits the desired Rust core plus web UI and reuses system WebView rather than bundling a full browser engine. React/TypeScript is reasonable for reader state and controls, but it creates a separate build/dependency surface and does not solve extraction or audio correctness. Start with a narrow one-window shell after phases 0–4. Tauri's filesystem permissions require explicit scopes; user-selected documents and narrow Rust commands are preferable to granting the frontend broad filesystem access. Python/ONNX/model bundling and target OS packaging remain an explicit experiment, not a solved consequence of choosing Tauri.

## F. Technology decision matrix

| Component | Current technology | Candidates | Preferred direction | Evidence required | Dependencies | Decision status |
|---|---|---|---|---|---|---|
| Orchestration | Python 3.14 CLI plus React/Tauri desktop shell | Python worker; Rust/Tauri core | Keep Python for extraction/narration; use Rust for desktop lifecycle, cancellation, playback state, and scoped file access | Worker lifecycle/IPC and cancellation tests; graphical responsiveness still requires manual review | Rust stable and locked Cargo dependencies | **Implemented prototype; graphical acceptance remains open** |
| PDF text | Poppler `pdftotext -bbox-layout` with `-layout` compatibility comparison | PyMuPDF structured dict; Poppler TSV/XML; pypdf | Keep bbox-layout: it supplies source geometry with no new Python dependency; preserve warnings for ambiguous order | Expected corpus text/order/page mapping; independent parser only if Poppler gaps justify a real benchmark and license review | Poppler installed; PyMuPDF absent and index inaccessible; PyMuPDF is AGPL/commercial | **Poppler baseline selected for current scope; real-PDF/independent comparison deferred** |
| DOCX | Standard-library OOXML traversal in `document.py` | `python-docx`; other OOXML readers | Keep the small dependency-free reader for paragraphs and tables unless fixture evidence requires a library | Reading order, tables, malformed packages, bounded archive expansion; headers/footnotes/tracked changes remain limited | Native parser uses ZIP/XML; no extra package | **Implemented; archive bounds and extraction tests present** |
| EPUB | Standard-library ZIP/XML + HTML parser following OPF spine in `document.py` | EbookLib; other EPUB readers | Keep the dependency-free spine reader for current scope; add navigation/metadata support only with fixtures and licensing review | EPUB2/3 ordering, markup edge cases, malformed and oversized archives | Native parser uses ZIP/XML; archive resource limits now applied | **Implemented for extracted text; broader EPUB structure remains limited** |
| OCR | Optional Tesseract plus `pdftoppm` rendering and cached coordinates in `ocr.py` | PyMuPDF OCR bridge; PaddleOCR | Keep OCR optional and CPU-first; preserve clear missing-tool errors | Real scanned-PDF corpus, accuracy/layout, language coverage, CPU/RAM, cache behavior | Tesseract was absent on the measured host; manual runtime verification remains open | **Adapter implemented; host-level scan verification pending** |
| Text analysis | Deterministic English narration rules in `narration.py` | spaCy; contextual model | Keep conservative source-mapped rules; only expand language/rule coverage with evaluation | Sentence boundaries, technical text, multilingual coverage, intelligibility, source mapping | No added NLP runtime/model | **Implemented with bounded English coverage; subjective quality evaluation open** |
| TTS default | Piper 1.8.0 Python worker; optional Kokoro ONNX adapter | XTTS-v2; other engine adapters | Keep Piper as default; retain Kokoro optional until matched listening/desktop checks | Same passages, randomized IDs, matched levels, naturalness/intelligibility, cold/warm load, TTFA, RTF, RAM, cancellation, licenses | Piper locally exercised; Kokoro uses separate compatible Python runtime and model assets | **Piper verified locally; Kokoro adapter implemented, GUI and listening evaluation open** |
| TTS runtime architecture | Persistent Python Piper worker with bounded mapped WAV chunks | Piper C API; other engine adapters | Keep worker contract; add adapters only when benchmark/feature need justifies | Performance, quality, cancellation, memory, packaging | Python API available; native C API adds CMake/GPL review | **Persistent Piper path selected; alternatives experimental** |
| Assistant inference | Python `llm_client.py` worker with OpenAI-compatible providers and optional embedded `llama-cpp-python` | External local or remote provider; embedded GGUF | Keep embedded mode explicit and lazy-loaded; preserve explicit provider choice and remote data disclosure | Model-backed correctness, resource use, cancellation/shutdown, credential handling, provider behavior | Embedded runtime and GGUF are optional; no model is bundled | **Implemented; mock-backed tests pass, real GGUF validation is opt-in** |
| Semantic retrieval | Legacy llama.cpp HTTP embedding retrieval; embedded mode receives bounded direct context | Local embedding model/index | Retain retrieval where configured; avoid assuming chat models provide embeddings | Fixed long-document question corpus, relevance/source citations, cache behavior, offline operation | Legacy HTTP server and embedding model are user configured; embedded mode has no vector retrieval | **Provider-dependent implementation; embedded retrieval not implemented** |
| Audio playback | Mapped WAV chunks through Tauri loopback HTTP server and WebView audio | Web Audio/WebView; CPAL native output | Keep the bounded local HTTP media path unless verified requirements call for native device output | Graphical Tauri playback, seeking, underruns, sample rates, restart behavior | Rust tests cover token/path/range handling; GUI audio remains unverified | **Desktop path implemented; interactive acceptance pending** |
| Audio decoding/resampling | None in application | Symphonia; Rubato | Add Symphonia for non-WAV decode, Rubato for measured resampling need | Required formats/device rates and profiling | Rust crates not in project | **Defer** |
| Persistence | Tauri app-local versioned progress JSON; HTML player `localStorage` | SQLite via rusqlite/SQLx | Keep progress-file approach while one active session/document is sufficient; consider SQLite when a searchable durable library needs queries | Restart, migration, corruption, privacy, query needs | No database dependency | **JSON progress implemented; database deferred** |
| Desktop UI | Tauri 2 + React/TypeScript/Vite | Native widgets or expanded webview architecture | Keep current Tauri/React shell; verify graphical playback and narration settings before adding more UI layers | Graphical Linux end-to-end run; browser controls; progress restoration; packaging/runtime review | Cargo and frontend builds pass; GUI display unavailable in audit session | **Source and automated checks pass; interactive behavior pending** |
| Native performance | ONNX Runtime's CPU EP | ONNX Runtime GPU EP; Piper C API; custom C/C++ | Use existing runtime; add acceleration only after profiling and hardware verification | RTF, CPU/GPU utilization, peak memory, quality parity, end-to-end packaging | Current runtime exposes CPU/Azure only; no working GPU device | **CPU verified; GPU open** |

## G. Performance targets and benchmark protocol

Performance measurements are available in `docs/BENCHMARKS.md` for a historical four-passage trial on the named CPU and four Piper voices. The current eight-passage corpus broadens coverage, but its new purpose is to support listening evaluation as well as future repeatable performance runs. Treat Kokoro comparisons in the report as estimates until Sonara runs them on the target hardware. No human voice-quality ratings have been collected.

Use a fixed, redistributable or self-authored corpus containing reports, technical terms, numbers/units, questions, citations, lists, dialogue, and multilingual passages only where the selected model claims support. Record corpus revision/hash, OS, CPU/GPU, runtime/provider, model/voice revision and precision, audio duration, text length, and cold/warm state. Separate model load from inference and UI playback. For subjective comparisons, randomize clip IDs/order, keep the answer key separate, match levels (current generator uses approximate RMS matching with a peak ceiling), and collect naturalness and intelligibility ratings before unblinding. The current comparison generator creates 8 passages × 3 Piper variation profiles; it does not produce quality findings by itself.

| Metric | Measurement method | Target policy |
|---|---|---|
| Model startup | Time process start to a ready signal; report cold disk/cache and already-loaded worker separately | Set after repeatable baseline; reuse model for later chunks |
| Time to first audio (TTFA) | Time from “read” action to first playable decoded PCM/sample; report p50/p95 across repeated runs, separate cold/warm | Define after baseline on named minimum hardware; include UI and queue delay, not just model kernel time |
| Real-time factor | `RTF = synthesis wall time / generated audio duration`; report per chunk and full passage, cold/warm | RTF < 1 is the necessary continuous-playback condition, but p95 chunk readiness and queue depth must also avoid underruns |
| RAM | Peak process and whole-application RSS; report model-loaded idle and long synthesis | Set a product budget only after the current CPU baseline and target user machine are measured |
| VRAM | Provider/device-reported peak allocated and reserved memory for actual GPU runs | Report as not applicable on this current host; never infer from installed CUDA packages alone |
| CPU/GPU utilization | Sample process and device utilization during model load, inference, and playback | Compare CPU and each compatible EP; verify actual EP use/fallback per session |
| Interruptions | Count playback underruns and record gap duration between chunk audio and planned playback time | Require no audible gaps in the agreed continuous-read test; establish acceptable jitter from listening/playback checks |
| Long-document stability | Fixed-duration and fixed-size sessions; sample RSS, queue/cache sizes, and cancellation/shutdown behavior | Memory and queues remain bounded; exact soak duration and budgets are set from expected user sessions |
| Speech quality | Blind human listening rubric for intelligibility, pronunciation, pauses, transitions, and consistency; collect per-passage ratings | No quality claim from RTF or model size; reject optimizations that materially damage listening quality |

Run at least repeated cold and warm trials on the current CPU-only laptop before adding GPU work. Record distributions, not a single best run. Add separate supported-GPU hardware later; this environment currently has no accessible GPU device or CUDA execution provider.

## H. Risks and unresolved questions

| Risk/question | Why it matters now | Mitigation or experiment |
|---|---|---|
| Naturalness and pronunciation | A blinded comparison pack can now be generated, but no participant ratings have been collected; rules are English-focused heuristics | Collect ratings with the generated participant pack; keep source/spoken text separate; tune only against listening evidence and review pronunciation errors |
| Piper variation profiles | Voice-specific defaults are retained; optional less/more profiles change noise parameters relative to those defaults | Compare randomized, level-matched clips before considering any default change; these values do not control pitch or emotion |
| Local LLM runtime | Local llama.cpp provider works through an externally managed compatible endpoint; process/model lifecycle is not integrated | Validate against a loopback server, then add supervised startup/readiness/shutdown |
| LLM privacy and credentials | WebView storage no longer persists API keys; credentials remain session-only; cloud/custom endpoints still transmit according to provider settings | Move secrets to secure native storage and show per-operation provider/data disclosure; never silently fall back from local to cloud |
| Long-document grounding | Local embedding retrieval and cache are implemented, but are not model-validated and lack page/block offset provenance | Evaluate long-document relevance; implement source-preserving passage metadata and cache controls |
| Kokoro runtime and audio contract | Optional engine integration exists but is unverified; current Python 3.14 runtime is incompatible with the reviewed package range and assets are absent | Validate on supported Python with reviewed model files; verify sample-rate handling, cancellation, offline loading, listening quality, and licensing |
| Language coverage | Spoken-text rules currently target conservative English abbreviations/units; ISO dates and numeric citations are opt-in | Add another language only with tested rules, reliable voice-language metadata, and language-specific listening evaluation |
| Browser playback/progress | HTML and JS exist, but browser behavior is untested; local-file storage policy varies | Exercise current page in supported browser and Tauri WebView; prefer app-owned persistence once desktop shell exists |
| PDF order/structure | Current synthetic corpus checks common layouts; Poppler `-layout` and bbox modes can still be row-wise or ambiguous for columns/tables | Keep warning and source boxes; add real, licensed multi-column/table PDFs before claiming broad extraction accuracy |
| OCR | No OCR executable/runtime is installed; recognition is slower and may reorder mixed text | OCR only pages that need it, cache results once/page, compare Tesseract and Paddle on multilingual scans, preserve confidence/boxes |
| Hardware portability | Only CPU execution is available in this audit; no GPU inference evidence | Declare CPU baseline; test exact ONNX Runtime execution provider, driver, CUDA/cuDNN compatibility on each target GPU |
| Piper/voice licenses | Piper runtime is GPL-3.0-or-later; model/voice terms are separate. John card cites public-domain LibriVox data; installed folder lacks provenance files | Retain model card/revision/hash and notices; review runtime, phonemizer, voice and output/distribution terms before bundling |
| Alternative model licensing | XTTS-v2 uses CPML; current upstream card describes 17 languages and reference voice cloning, but license is non-commercial absent separate authorization | Do not select XTTS for a distributed/commercial product without rights review; prioritize Kokoro benchmark if permissive terms fit |
| Python/Rust boundary | Tauri supervises the Python CLI in a Unix process group; Python starts Piper as a child; active child teardown has not been tested in a running desktop UI | Keep document/audio off JSON; retain process-group cancellation; verify cancellation and shutdown in a graphical desktop run |
| Native integration complexity | Piper has a C API, but CMake/native dependency distribution and GPL boundary add work | Only compare it after measurements show Python/process overhead or deployment is the bottleneck |
| Packaging | Tauri uses system WebView; bundling Python, ONNX Runtime, espeak data, models, voice notices, and OS libraries is substantial | Build a prototype package on the first target OS; measure installed size; document external/user-downloaded model requirements |
| Licensing of document libraries | EbookLib is AGPL; PyMuPDF is AGPL or commercial; a parser choice affects distribution | Decide distribution/license policy before selecting those dependencies; record licenses and transitive notices |
| Scope and complexity | Full feature list tempts premature LLM, voice acting, OCR, and microservices | Ship PDF + one voice + playback first; defer features until user need and tests justify them; no cloud service for local pipeline |
| Git workflow | The repository is active and contains untracked source files | Review `git status` and stage intended files explicitly; do not commit local model weights or generated artifacts |

## I. Immediate next actions

1. Launch Sonara from a graphical Linux session with `cargo run --manifest-path src-tauri/Cargo.toml --locked`; verify real Piper playback, narration preview/settings, cross-chunk seek, pause/resume, speed, cancellation, and progress restore. This is still the core desktop acceptance blocker.
2. Collect blind naturalness and intelligibility ratings for `/tmp/sonara-listening-evaluation/participant-pack` before consulting its facilitator key. Compare profiles by passage and retain Piper voice defaults unless there is a clear, repeatable improvement.
3. Run the standalone player checklist in a supported browser and an extended multi-chunk listening session; record media behavior, interruptions, memory, and progress persistence.
4. Prove llama.cpp connectivity through the existing custom endpoint using a small, locally installed GGUF model. Keep it bound to loopback; record latency, RAM, and response quality. Do not start embedding/index work until grounded assistant retrieval has a fixed evaluation corpus.
5. Prototype Kokoro runtime options and then compare identical matched-level clips with Piper. Do not change the default engine based on model claims or latency alone.

## Primary technical references

- [Tauri 2 prerequisites](https://v2.tauri.app/start/prerequisites/), [security model](https://v2.tauri.app/security/), and [filesystem permissions/scopes](https://v2.tauri.app/plugin/file-system/)
- [Tokio task cancellation and blocking-task caveats](https://docs.rs/tokio/latest/tokio/task/)
- [Serde](https://docs.serde.rs/), [SQLx SQLite](https://docs.rs/sqlx/latest/sqlx/sqlite/), [CPAL](https://docs.rs/cpal/latest/cpal/), [Symphonia](https://docs.rs/symphonia/latest/symphonia/), and [Rubato](https://docs.rs/rubato/latest/rubato/)
- [Piper CLI](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/CLI.md), [Piper license/upstream](https://github.com/OHF-Voice/piper1-gpl), [John medium voice card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/john/medium/MODEL_CARD), and [voice files/model metadata](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/john/medium)
- [Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M) and [official kokoro.js usage](https://github.com/hexgrad/kokoro/blob/main/kokoro.js/README.md)
- [XTTS-v2 model card](https://huggingface.co/coqui/XTTS-v2) and [CPML license text](https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt)
- [PyMuPDF extraction](https://pymupdf.readthedocs.io/en/latest/faq/index.html), [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html), [PyMuPDF license](https://pymupdf.readthedocs.io/en/latest/about.html), [python-docx document API](https://python-docx.readthedocs.io/en/latest/api/document.html), and [EbookLib](https://github.com/aerkalov/ebooklib)
- [spaCy sentence segmentation](https://spacy.io/usage/linguistic-features), [Tesseract manual/license](https://tesseract-ocr.github.io/tessdoc/), and [PaddleOCR OCR pipeline](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)
- [ONNX Runtime execution providers](https://onnxruntime.ai/docs/execution-providers/) and [CUDA provider requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [React installation](https://react.dev/learn/installation)
