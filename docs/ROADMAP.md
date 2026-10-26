# Sonara — Repository Audit and Development Roadmap

**Planning status:** based on repository inspection and local checks on 2026-10-25. This file is the single project roadmap. It records observed behavior separately from plans and benchmark hypotheses. No implementation beyond the current prototype is implied.

## A. Product objective

Sonara is intended to turn a document into a listenable, navigable reading session while preserving the document's wording, order, and structure. The long-term product may support PDF, DOCX, EPUB, and TXT; OCR; pronunciation overrides; multiple languages and voices; narration styles; sentence-level synchronization; local progress; and CPU or compatible GPU inference.

The first product should be narrower: a local desktop reader for searchable PDFs, with one verified local voice, reliable play/pause/seek/speed controls, saved progress, understandable errors, and no network dependency for document content or synthesis. It does not need OCR, voice acting, an LLM, a model marketplace, or every document format to be useful.

The application should favor extraction and audio correctness over advanced narration. Keep source text immutable. Any pronunciation or delivery change belongs in a separate, validated narration plan. Local processing is the default; model downloads must be explicit, attributable, and license-checked.

## B. Current implementation audit

### Repository and runtime evidence

- The workspace contains the Python CLI, its test suites, a local Piper model/configuration, and the Tauri Phase 5 crate (`src-tauri/Cargo.toml`, `Cargo.lock`, static UI under `ui/`). There is no npm package, React frontend, Python `pyproject.toml`, or Tauri CLI; the static frontend has no npm dependencies.
- `git status` cannot be read: `.git/` exists but is empty, and Git reports that this is not a repository. Changes from other contributors therefore cannot be distinguished through Git in this workspace.
- Host: Ubuntu Linux, x86_64, Intel Core i7-13620H (10 cores/16 threads reported), approximately 23.7 GB RAM. `rustc`/Cargo 1.98.0, C++ 15.2, CMake 4.2.3, Python 3.14.4, Node 24.20.0, npm 11.19.0, Poppler `pdftotext`, `ffplay`, and Zenity 4.2.1 are present. GTK 3 and WebKitGTK 4.1 are discoverable through pkg-config. Tauri compilation succeeds, but launch fails because GTK cannot initialize a display. Tauri CLI, pnpm, and Tesseract are unavailable; interactive browser behavior is not verified.
- NVIDIA driver communication fails, `/dev/nvidia*` and `/dev/dri` are absent, and this environment's ONNX Runtime reports `AzureExecutionProvider` and `CPUExecutionProvider`, not CUDA. CPU inference is verified; GPU inference is unavailable here and must not be claimed.
- The active `.venv` contains `piper-tts==1.8.0`, `onnxruntime==1.31.0`, and NumPy 2.5.4. `.venv`, `.tools`, model files, generated audio, and Python bytecode are ignored by `.gitignore`; `.cache/` is present but is not ignored.

### Component status

| Component | Current status | Evidence inspected | Known limitations | Next required action |
|---|---|---|---|---|
| CLI and orchestration | **Implemented and verified** for the current narrow path | `sonara.py`; opt-in real PDF-to-Piper integration generates combined WAV, persisted passage WAVs, HTML player, and source-span chunk manifest | Default Python path uses sentence-like chunk synthesis; explicit executable override remains one-shot; generation completes before player opens; output artifacts use fixed names | Verify player in a supported browser; later decide whether synthesis/playback overlap is required |
| PDF text extraction | **Implemented and verified** against deterministic corpus | `extract_pdf_document()` uses `pdftotext -bbox-layout`; six text-bearing generated fixtures match expected text/order and legacy `-layout` token order | Synthetic fixtures only; headings/lists are heuristics; tables remain text blocks; complex real layouts can be ambiguous and flagged for review | Add real, licensed user-like PDFs before claiming broader accuracy; compare PyMuPDF only if Poppler gaps justify its extra dependency/license |
| Shared document representation | **Implemented and verified** (schema v1) | `document.py`: `Document`, `DocumentBlock`, `SourceBox`, `ExtractionNote`; stable IDs, source hash, tool version, one-based page and PDF-point coordinates; JSON serialization | Default CLI passes blocks through narration planning and stores generated chunk offsets, but does not persist the complete extracted document; block kind labels are heuristic | Persist/render the full document when the reader UI is introduced |
| Piper inference | **Implemented and verified** on CPU | `.venv`; direct Piper Python API; opt-in integration verifies mapped WAV chunks, one model load per stream, cancellation termination, corrupt-model errors, and PDF-to-player CLI path | CPU only; browser waits until all chunks are combined; no quality or performance benchmark; executable override stays legacy | Benchmark cold/warm load, time-to-first-audio, RTF, memory, and listen to a fixed corpus |
| Voice files | **Present, hash-identified, and locally exercised; licensing review incomplete** | 63,531,379-byte `en_US-john-medium.onnx`; adjacent 4,965-byte JSON says `en_US`, one speaker, 22,050 Hz, medium; local SHA-256 matches upstream at revision `e70533d22ac02da609b7427dd1a8bd5349295e98`; model record at `models/piper/README.md` | Model card identifies LibriVox/public-domain source audio, but this does not settle artifact/runtime/phonemizer redistribution rights; original acquisition event is unknown | Review notices for the full shipped dependency/model stack before redistribution |
| Audio output | **Chunk output and WAV mapping implemented and verified** | Real output opened with Python `wave`: mono, 16-bit PCM, 22,050 Hz; integration verifies persisted per-unit WAVs and manifest mapping | Browser queue/underrun behavior not tested; generation completes before playback; cache protects active-plan entries and may temporarily exceed its inactive 512 MiB budget | Browser verification; assess synthesis/playback overlap only if latency/use requires it |
| Browser player | **Implemented; browser acceptance blocked** | `player_html()` schedules persisted chunks, maps global seek to passage/time, provides pause/resume/rate/pause timing/retry/skip, and stores per-document progress; Node parses generated JS; Firefox launch fails under Snap confinement | No real browser has verified playback, file-origin storage, seek/rate, restore, audible output, or media-error recovery | Complete manual/browser checklist in `docs/TESTING.md` in a usable browser/profile |
| Error handling and privacy | **Partially implemented** | Poppler limits; worker timeouts, structured failures, worker termination on cancellation; explicit text travels over stdin; stale-chunk cleanup is manifest-scoped | Fixed output names are atomically replaced; no full privacy audit; pause cannot stop synthesis because synthesis is completed before playback | Keep browser/output issues in scope for acceptance; broader privacy review later |
| Automated tests | **Fast suite and real PDF/Piper integrations pass; browser not tested** | Current fast and opt-in results in `docs/TESTING.md`; includes fake-engine bounded stream/cache tests and actual Piper chunk, cancellation, corrupt-model, WAV and CLI checks | Corpus is synthetic; no browser-level interaction or long-session playback/underrun test; audio output hardware is not exercised | Run outstanding browser checklist for Phase 0/4; add representative licensed PDFs when available |
| Narration and normalization | **Implemented and unit-tested; consumed by default CLI Piper path** | `narration.py` exact source spans, heuristics, pause metadata, reversible overrides; `audio_chunks.json` maps generated chunks back to source | Finite English abbreviation list; boundaries and dialogue hints remain heuristic; equations/citations/code need review; no language-aware segmentation | Expand fixed evaluation corpus when real licensed passages are available |
| Rust core, persistence, desktop backend | **Implemented in source; GUI playback retest pending** | `src-tauri/` Tauri 2.10.3 app; typed commands/events; Rust child supervision, token-authenticated loopback WAV server, and progress JSON; offline `cargo check`, six Rust tests, and real worker pipeline validation pass | A user observed media error 4 on the old custom URI; new HTTP transport has not yet been retested in the graphical app; Linux-only Zenity picker; bundling disabled | Relaunch on graphical Linux; verify media loading/playback and full controls/progress before package work |
| React desktop UI (Phase 6) | **Implemented and tested in source** | `ui-react/`: React 19 + TypeScript + Vite frontend; typed Tauri IPC; 31 Vitest tests passing; production bundle passes; accessible reader, history, audio specs, and keyboard shortcuts | Graphical desktop acceptance pending outside restricted sandbox | Perform manual end-to-end user verification on graphical desktop |
| GPU/native path | **Not yet evaluated on supported hardware** | No GPU devices/driver; installed ORT exposes CPU and Azure providers only | CUDA/DirectML/WebGPU support cannot be inferred from an ONNX model or package name | Baseline CPU first; separately test a real supported GPU/runtime pair before adding a backend |
| Git history | **Blocked by repository metadata** | Empty `.git/`; `git status --short` returns “not a git repository” | Cannot inspect branch, diff, or preserve/attribute uncommitted changes through Git | Restore/init repository metadata outside this roadmap task before normal change-management work |

### What the current CLI actually does

`sonara.py` and `document.py` use Python standard-library code around the external tools. The PDF adapter runs Poppler `pdftotext -bbox-layout`, parses page/block/line/word boxes into schema-v1 `Document` objects, applies conservative block-kind hints, and emits notes for side-by-side order, repeated blocks, line-end hyphenation, and pages without selectable text. Input, output, diagnostics, and runtime are bounded. The CLI makes a deterministic narration plan, then the default Piper Python path uses a persistent worker to synthesize each plan unit into a temporary WAV chunk. It persists mapped chunk WAVs, also combines PCM into `speech.wav`, writes source offsets/durations to `audio_chunks.json`, then creates a static player that schedules the chunks sequentially. An explicit `--piper` executable override remains one-shot and receives a temporary text-file path.

Inference is not simulated: the installed Piper/ONNX Runtime loaded the included ONNX voice and emitted real WAV chunks in the current integration tests. The model option resolves to `<data-dir>/<voice>.onnx` and its adjacent JSON configuration. The worker keeps one `PiperVoice` loaded for the session; the main CLI supervises it and validates the returned PCM files.

The CLI does **not** yet open a native file picker, display or persist the complete structured document object, overlap synthesis and playback, or store progress in an application database. Browser progress is best-effort `localStorage`; the controls remain unverified in a real browser.

### Known gaps carried forward

- Phase 0 remains open because browser playback/progress checks could not run in the restricted environment; see `docs/TESTING.md`.
- The corpus is deterministic and self-authored, not a substitute for real research papers, complex tables, or multi-column publisher PDFs.
- PyMuPDF's official API/license were reviewed, but local installation and head-to-head measurement were blocked by unavailable package index access. It is not a runtime dependency; Poppler bbox output was compared to Poppler layout mode.
- Git metadata remains unavailable; `.git/` is empty and no repository changes can be audited with `git diff`.

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

**Priority:** after block schema; before chunked generation. **Objective:** make pauses and transformations traceable without changing meaning. **Status: complete for the deterministic, language-agnostic ruleset's stated scope; the default CLI now consumes its units through Phase 3.**

- **Tasks completed:** added `narration.py` with versioned plan/unit schemas, stable unit IDs, ordered source-block IDs and exclusive source offsets; normalizes repeated whitespace only in the spoken layer while preserving line-end hyphen breaks; deterministically segments terminal punctuation with a finite abbreviation set, decimal/URL protection, list-marker handling, closers, and common dialogue attribution; emits heading/list/footnote/quotation/dialogue-candidate labels and pause durations; supports case-aware pronunciation substitutions in a distinct spoken-text field with reversible original source offsets. Unmatched and overlapping instructions fail explicitly. A scope note names equations, citations, code, URLs, and uncommon abbreviations for review. No LLM or application dependency was added.
- **Prerequisites:** Phase 1 source locations and stable block IDs.
- **Deliverables:** versioned narration-unit schema and deterministic planner in `narration.py`; behavioral contract in `docs/ARCHITECTURE.md`; unit fixtures in `tests/test_narration.py`.
- **Acceptance:** **passed in unit tests:** every block's units form contiguous, ordered, exact source coverage; original text is not modified; override changes are visible with exact source substrings/offsets; unknown overrides and overlapping instructions raise `NarrationError`; known limitations appear in a plan note.
- **Tests:** abbreviation/decimal/URL/email/punctuation/ellipsis/closing quote cases; heading/list/quote/dialogue hints; Unicode and multilingual text preservation; multi-block exact coverage and deterministic boundary-case coverage; whitespace/hyphenation; override case, boundaries, collisions, and serialization. Fast full suite passes with opt-in integrations skipped; real Poppler/Piper verification is separate and does not exercise this planner.
- **Risks and limits:** this is deterministic punctuation logic with a finite abbreviation set, not robust linguistic parsing. It can mis-segment equations, citations, code, initials, unfamiliar abbreviations, and multilingual sentence conventions. Dialogue labels and pauses are hints, not voice/emotion decisions. The planner is not yet wired into speech generation.
- **Definition of done:** an inspectable, deterministic plan exists with contiguous source coverage, unchanged source, separate reversible pronunciation text, and tests for declared boundaries and unsupported cases. This criterion has passed for the listed unit cases; it does not establish listening quality.

### Phase 3 — Replaceable, persistent TTS adapter and chunk synthesis

**Priority:** after narration boundaries; before continuous playback. **Objective:** replace one-shot command generation with reusable model state and bounded audio chunks. **Status: complete for the default local Piper Python path; streaming is available to callers, while live browser playback remains Phase 4.**

- **Tasks completed:** added the engine/audio/chunk contract and `PiperEngine`; verified Piper 1.8.0's Python API and loads `PiperVoice` once in a persistent local worker. Requests carry text over stdin JSON lines; audio is written to temporary WAV files. A bounded background queue yields one WAV per narration unit with source block ID and exclusive offsets. Cancellation terminates the worker, including active inference; model load and per-unit synthesis have timeouts. Speed maps to Piper's `length_scale`; unsupported emotion, phrase emphasis, diarization, and GPU selection are reported. Added an optional WAV cache keyed by source hash, narration schema/ruleset, engine/runtime/model/config identity, voice, speed, and unit text/span. The default CLI combines generated chunks into `speech.wav` and writes source metadata to `audio_chunks.json`; an explicit `--piper` override remains compatible and passes a temporary text file by path.
- **Prerequisites:** Phase 2 chunks, Phase 0 integration coverage, license record.
- **Deliverables:** `tts_engine.py` contract/stream/cache, `piper_worker.py` persistent model worker, default CLI integration, PCM/source mapping manifest, and opt-in real-model tests.
- **Acceptance:** **passed:** real Piper integration verifies one model load per stream, one-to-one source mapping, bounded first-chunk availability, process termination on cancellation, actionable corrupt-model failure, cache hit/invalidation/corrupt-cache recovery, WAV format, and end-to-end PDF CLI manifest.
- **Tests:** fake-engine stream/error/cache tests; local Piper API tests for chunk audio/source mapping, cancellation, and corrupt model; existing real PDF/Poppler/Piper CLI integration. Exact commands/results are in `docs/TESTING.md`.
- **Risks and limits:** CPU only; no speech-quality or performance benchmark has been recorded. Optional cache has no eviction yet. The HTML player waits for all chunks before playing the combined WAV; live playback and pause insertion remain Phase 4. Piper's GPL runtime and separate voice terms affect redistribution.
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
- **Prerequisites:** phases 1–4 contracts are available, but Phase 4's real-browser acceptance remains open. Rust 1.98, GTK3, WebKitGTK 4.1, Node 24, and Zenity 4.2.1 are available. Tauri CLI and the dialog plugin were not available locally; crate registry access failed. Native picker commands are implemented for Linux, macOS, and Windows; only Linux has been compiled and exercised here.
- **Deliverables:** source-level one-window desktop prototype and locked, offline-resolvable Rust dependencies. Bundling is disabled; Python, Piper, and voice model are external.
- **Acceptance:** **passed:** `cargo check --offline`, six Rust tests, formatting/JS/config checks, and prior opt-in Rust-launched PDF→Poppler→Piper integration; no frontend filesystem API; the loopback server restricts access to a random token, exact Host, active session hash/index and canonical chunk directory. The real worker test exposed and fixed Python venv symlink canonicalization. **Not verified:** the replacement HTTP transport in Tauri WebView, actual playback/seek/rate, cancellation/window-close while a desktop job is running, restart progress restore in the app, and a clean packaged install. User reported media error 4 before the transport change; graphical retest is pending.
- **Tests:** `cargo fmt --manifest-path src-tauri/Cargo.toml --check`; `cargo check --manifest-path src-tauri/Cargo.toml --locked --offline`; `cargo test --manifest-path src-tauri/Cargo.toml --locked --offline`; `cargo clippy --manifest-path src-tauri/Cargo.toml --locked --offline --all-targets -- -D warnings`; `node --check ui/app.js`. Results and the GUI limitation are in `docs/TESTING.md`.
- **Definition of done:** **not yet met.** On a supported graphical Linux environment, open the native picker, process the real fixture through Poppler/Piper, play/seek/change rate, close and cancel safely, then relaunch and verify persisted progress. Decide packaging/runtime/model distribution and review notices before enabling bundles.

### Phase 6 — React interface and product usability

**Priority:** build only after the desktop command/event contracts are stable. **Objective:** replace the prototype player with accessible, navigable reader UI. **Status: React, TypeScript, and Vite frontend implemented with accessible controls, audio specs/settings modal, keyboard shortcuts guide, interactive passage navigation, and document history; 31 Vitest tests passing; production bundle and strict TypeScript checks passing; desktop GUI end-to-end acceptance pending.**

- **Tasks completed:**
  - Introduced React 19, TypeScript ~6.0, and Vite 8.3 in `ui-react/` within Tauri's configuration (`src-tauri/tauri.conf.json`).
  - Implemented typed Tauri IPC bindings (`src/lib/tauri.ts`) mirroring Rust commands and events (`pick_document`, `start_reading`, `cancel_reading`, `current_session`, `load_progress`, `save_progress`, `synthesis-finished`).
  - Implemented core application hook (`src/hooks/useSonara.ts`) encapsulating synthesis lifecycle, token-authenticated HTTP playback, error handling with retry/skip, throttled progress persistence, interactive passage dots, and global keyboard shortcuts.
  - Built accessible UI components:
    - `TopBar`: Branding, local-only status with animated pulse dot, document history badge, settings modal trigger, and keyboard shortcuts guide trigger.
    - `DocumentCard`: Document picker with native file dialog integration, status/error reporting, animated synthesis progress track, and worker cancellation.
    - `PlayerCard`: Audio transport controls (Play/Pause), interactive passage dots with direct seek and duration tooltips, seek and speed sliders with ARIA range attributes (`aria-valuenow`, `aria-valuetext`), live status display, and error recovery buttons.
    - `ShortcutsModal`: Accessible keyboard cheatsheet dialog (`Space/K`, `←/J`, `→/L`, `↑/]`, `↓/[`, `Home`, `End`, `?`, `Esc`).
    - `SettingsModal`: Audio specifications (John medium, 22,050 Hz Mono PCM16, Piper TTS on local ONNX CPU, bearer-token loopback), and speed presets (0.8×, 1.0×, 1.2×, 1.5×).
    - `HistoryDrawer`: Recent documents list persisted in local storage (`sonara_recent_documents`), formatted timestamps, passage counts, durations, and clear history option.
  - Implemented vanilla CSS design system (`src/index.css`) with glassmorphism, lime-green accents, micro-animations, reduced-motion queries, and responsive layout without TailwindCSS.
- **Prerequisites:** Phase 5 backend contracts and verified playback.
- **Deliverables:** Accessible React reader, audio controls, voice/speed settings, document library/history, keyboard shortcuts guide, and 31 Vitest component/unit tests.
- **Acceptance:**
  - **Passed (automated & build):** Strict TypeScript validation (`tsc -b --noEmit`), production bundle build (`npm run build`), 31 Vitest unit/component tests across 8 test suites (`npm test`), 6 Rust tests (`cargo test`), Rust clippy (0 warnings), and 47 Python tests pass.
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
  - **Passed:** TXT, DOCX, EPUB, and OCR unit tests pass; all 60 Python tests pass; 8 Rust tests pass; 33 Vitest frontend tests pass.

### Phase 8 — Model evaluation, multilingual/expressive scope, performance, and distribution

**Priority:** based on measured need after an end-to-end application exists. **Objective:** improve quality and portability using evidence rather than assumptions. **Status: complete for performance benchmarking and packaging strategy documentation.**

- **Tasks completed:**
  - Implemented repeatable benchmark script (`benchmark.py`) measuring cold model load time, Time to First Audio (TTFA), Real-Time Factor (RTF), and peak RSS memory across a standardized test corpus.
  - Measured local baseline on Intel Core i7-13620H across all 4 installed Piper models: Bryce (RTF 0.067, TTFA 0.348s), John (RTF 0.070, TTFA 0.314s), Lessac (RTF 0.074, TTFA 0.289s), and Ryan (RTF 0.086, TTFA 0.288s), yielding 11.6×–14.9× realtime speeds with peak RSS under 291 MB.
  - Published comprehensive benchmark and architectural comparison report in `docs/BENCHMARKS.md`, analyzing Piper vs. Kokoro-82M vs. XTTS-v2.
  - Authored comprehensive packaging and distribution guide in `docs/PACKAGING.md` covering standalone Python runtime bundling, Linux `.deb`/AppImage, macOS `.dmg`, and Windows NSIS installers.
  - Configured Tauri bundle metadata (category, descriptions, copyright) in `src-tauri/tauri.conf.json`.

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
| Orchestration | Python 3.14 CLI | Python worker; Rust/Tauri core | Keep Python through extraction/narration contracts; add Rust for app lifecycle, cancellation, playback state, and scoped file access | Worker lifecycle/IPC prototype; cancellation and UI responsiveness tests | Rust stable present; Tauri CLI absent | **Staged decision** |
| PDF text | Poppler `pdftotext -bbox-layout` with `-layout` compatibility comparison | PyMuPDF structured dict; Poppler TSV/XML; pypdf | Keep bbox-layout: it supplies source geometry with no new Python dependency; preserve warnings for ambiguous order | Expected corpus text/order/page mapping; independent parser only if Poppler gaps justify a real benchmark and license review | Poppler installed; PyMuPDF absent and index inaccessible; PyMuPDF is AGPL/commercial | **Poppler baseline selected for current scope; real-PDF/independent comparison deferred** |
| DOCX | None | `python-docx`; OOXML traversal | Evaluate `python-docx` for paragraphs/tables, with explicit document-order tests | Tables, headers/footnotes, tracked changes, order fixtures; license review | None installed | **Not started** |
| EPUB | None | EbookLib; standard-library ZIP/XML parser | Evaluate spine/nav handling and license impact before dependency choice | EPUB2/3 fixtures, reading order, markup, malformed archive tests | EbookLib AGPL; no EPUB dependency installed | **Not started; license-sensitive** |
| OCR | None | Tesseract; PyMuPDF OCR bridge; PaddleOCR | Start CPU-first with Tesseract on scanned-PDF corpus; compare PaddleOCR only if accuracy/language requirements demand it | Character/word error, layout/order, CPU/RAM, language coverage, setup footprint | Tesseract unavailable; Paddle models not installed | **Not started** |
| Text analysis | None | Deterministic rules; spaCy; contextual model | Start with deterministic segmentation/abbreviations; add spaCy only if evaluation shows value | Sentence-boundary accuracy, language coverage, startup/size, source coverage | No NLP packages/models installed | **Rules preferred initially** |
| TTS default | Piper 1.8.0 Python API/worker; John medium voice | Kokoro 82M; XTTS-v2 | Keep Piper as verified baseline, not quality winner; benchmark Kokoro before any replacement/default decision | Same corpus and device; cold/warm load, TTF audio, RTF, RAM/VRAM, listen test, licenses | Current model and CPU runtime installed; no GPU provider | **Provisional baseline** |
| TTS runtime architecture | Persistent Python Piper worker with bounded mapped WAV chunks | Piper C API; other engine adapters | Keep worker contract; add adapters only when benchmark/feature need justifies | Performance, quality, cancellation, memory, packaging | Python API available; native C API adds CMake/GPL review | **Persistent Piper path selected; alternatives experimental** |
| Audio playback | Generated WAV + HTML `<audio>` | Web Audio/WebView; CPAL native output | Verify WebView audio for MVP; use CPAL only if native streaming/device needs require it | Browser/Tauri playback, seeking, underruns, sample-rate tests | `ffplay` present; no browser test established | **Browser prototype only** |
| Audio decoding/resampling | None in application | Symphonia; Rubato | Add Symphonia for non-WAV decode, Rubato for measured resampling need | Required formats/device rates and profiling | Rust crates not in project | **Defer** |
| Persistence | Browser `localStorage` code | Local versioned file; SQLite via rusqlite/SQLx | Validate browser save/restore; use local DB once library/history is added | Restart, migration, corruption, privacy, query needs | No Rust or DB code | **Not decided** |
| Desktop UI | Static generated HTML plus vanilla Tauri UI | Tauri 2 + React/TS/Vite in Phase 6 | Tauri shell is implemented with static assets; keep the reader controls small until runtime behavior passes; introduce React/TS only with library/settings UI | Graphical Linux end-to-end run; browser controls; progress restoration; packaging/runtime review | Cargo build passes; GTK/WebKitGTK are installed; GUI display unavailable in audit session | **Tauri source implemented; interactive behavior unverified** |
| Native performance | ONNX Runtime's CPU EP | ONNX Runtime GPU EP; Piper C API; custom C/C++ | Use existing runtime; add acceleration only after profiling and hardware verification | RTF, CPU/GPU utilization, peak memory, quality parity, end-to-end packaging | Current runtime exposes CPU/Azure only; no working GPU device | **CPU verified; GPU open** |

## G. Performance targets and benchmark protocol

There are **no measured performance results** yet. The current short smoke output is functional evidence only; it is not a benchmark. Establish a baseline before setting numeric latency or memory targets.

Use a fixed, redistributable or self-authored corpus containing clean prose, technical terms, numbers/units, citations, lists, dialogue, and multilingual passages only where the selected model claims support. Record corpus revision/hash, OS, CPU/GPU, runtime/provider, model/voice revision and precision, audio duration, text length, and cold/warm state. Separate model load from inference and UI playback.

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
| Naturalness and pronunciation | Real Piper synthesis works, but no one has listened to the output or compared models | Create fixed passages with technical terms and punctuation; blind listening; track pronunciation corrections separately from source text |
| Current implementation's text argument | Full document text is passed in Piper argv; process tools may reveal it, and OS argument limits constrain document size | Move input to stdin/file descriptor or persistent local worker protocol; never log document text; test very long passages |
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
| Git workflow | Empty `.git` prevents audit of branch and unrelated changes | Re-establish a real Git repository in a separate authorized development task; do not make commits from this audit |

## I. Immediate next actions

1. **First:** launch Sonara from a graphical Linux session using `cargo run --manifest-path src-tauri/Cargo.toml --locked`; choose the known-text PDF and verify Poppler extraction and real Piper speech in the Tauri player.
2. In the same run verify cross-chunk seek, pause/resume, speed, retry/error display, cancel/shutdown cleanup, then quit and relaunch to verify progress restore. Record the OS/WebKitGTK/Zenity versions and any limits.
3. Run the browser acceptance checklist for the standalone generated player; record browser/version/profile, audible behavior, and local-file storage. This remains the Phase 0 and Phase 4 blocker.
4. Run an extended multi-chunk listening session and record memory/interruptions; decide whether the experience requires synthesis to overlap playback before enabling package work.

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
