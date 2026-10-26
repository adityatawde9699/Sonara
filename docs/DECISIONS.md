# Decisions

## 2026-10-27: Piper defaults, reversible narration, and listening evaluation

Leave Piper `noise_scale` and `noise_w_scale` unspecified in the default worker request so the selected voice config supplies its own synthesis defaults. Optional `less`/`more` profiles are relative experiments (0.85×/1.10×, capped at 1.0); retain voice defaults unless a blinded, loudness-matched listening evaluation demonstrates a clear improvement. These parameters describe generator noise and phoneme-width variation, not pitch or emotion.

Keep source text and source offsets immutable. Apply conservative English abbreviation/unit normalization only to `spoken_text`, with ISO date and numeric citation expansion separately opt-in. Expose a preview of the planned spoken text. Refine only inter-unit pauses from punctuation and block structure; do not introduce per-sentence prosody changes without listening evidence.

Add a repeatable blind comparison pack with randomized IDs, a broader corpus, RMS level matching, and a separate facilitator key. Treat the pack as an evaluation protocol, not a quality result. Kokoro figures in the existing benchmark remain estimates until run and listened to on Sonara's target hardware.

## 2026-10-25: Bootstrap with local CLI adapters

The repository was empty and the environment provides Poppler but no Tauri CLI, pnpm, or installed TTS runtime. Start with a Python standard-library orchestrator and external Poppler/Piper processes so the PDF-to-audio contract can be exercised without inventing inference or fetching large model artifacts. This is a temporary bootstrap, not a decision to displace Rust as the application core.

## 2026-10-25: Piper as first integration target, not selected quality winner

Piper provides a straightforward local CLI and voice files can be installed separately. The currently maintained upstream is GPL-3.0-or-later; per-voice licensing varies and must be checked. The Lessac medium model was rejected for setup because its cited dataset licence is research-only. The John medium voice is the example selected for local testing because its card reports LibriVox public-domain recordings. Do not bundle Piper/voice assets until licensing is reviewed. Benchmark Kokoro before any default-engine decision. No model has been downloaded automatically.

## 2026-10-25: Poppler for initial PDF extraction

`pdftotext -layout` is already installed and avoids a heavyweight Python PDF dependency. Preserve its output and fail visibly. Layout text is a first-pass extraction; multi-column ordering and scanned-page OCR remain limitations.

## 2026-10-25: Phase 0 repeatable integration baseline

Use a small standard-library PDF generator under `tests/fixtures/` rather than adding a PDF-generation package or checking in a binary fixture. Keep Poppler/Piper integration opt-in with `SONARA_RUN_INTEGRATION=1`; the ordinary tests stay model-independent while the integration exercises installed tools and local model files without mocks or downloads. Use `TemporaryDirectory` for all generated integration artifacts.

Pin the actually exercised Piper runtime and its ONNX Runtime dependency in one `requirements.txt`; ONNX Runtime is pinned because it is material to inference reproducibility even though Piper depends on it transitively. Keep NumPy transitive because Sonara does not use it directly. Record model hashes and upstream revision in `models/piper/README.md`; keep weights ignored and selectively allow this provenance document.

The generated HTML reports when local-file browser policy prevents progress storage. Browser behavior could not be verified in this environment: cached Chromium revisions 1228, 1243, and 1247 plus Playwright were present, but all browser binaries failed because the environment denied Crashpad/sandbox operations; Firefox and Brave failed under Snap confinement; WebKitGTK could not connect to a display, including Xvfb. Phase 0 remains incomplete until the browser checklist in `docs/TESTING.md` is run in a usable browser.

## 2026-10-25: Phase 1 PDF source mapping with Poppler bbox output

Use the existing Poppler binary's `pdftotext -bbox-layout` output as the PDF adapter's source of text blocks and page/point coordinates. It emits block, line, and word boxes without adding a Python PDF parser; the standard-library XML parser is sufficient for this output. Keep the old `-layout` extraction as a comparison baseline and compatibility text behavior. The generated corpus passed exact expected-text/order/page checks and token-order comparison against `-layout`; two-column and side-by-side table-like cases are flagged for review. Extraction now caps PDF input at 100 MiB, bbox output at 32 MiB, diagnostics at 1 MiB, and execution at 60 seconds.

Do not add PyMuPDF to the runtime now. Its official [`Page.get_text("dict")` API](https://pymupdf.readthedocs.io/en/latest/faq/index.html) exposes blocks, lines, spans, fonts, and bounding boxes, but no local install was available and package index access failed. The current Poppler contract satisfies this phase's tested location needs; PyMuPDF remains an independent comparison candidate if corpus failures show missing value. Its [official licensing page](https://pymupdf.readthedocs.io/en/latest/about.html) describes AGPL and commercial licensing, so that review is a real distribution cost.

Block kinds (`heading`, `list_item`, `quote`, `footnote`, `paragraph`) are hints with an explicit `kind_source`, not PDF semantics. A PDF exposes visual/text cues but generally lacks reliable semantic tags; do not use these heuristic labels as truth without review.

## 2026-10-25: Deterministic narration planning contract

Keep Phase 2 as a standard-library Python module over immutable document blocks. Represent each spoken unit with a block ID and exclusive source offsets, and retain exact source text independently from whitespace-normalized or pronunciation-adjusted `spoken_text`. Require contiguous full block coverage and fail unmatched/overlapping pronunciation rules explicitly. Use deterministic punctuation and a finite abbreviation list first; expose structural labels and pause durations as hints only. Record out-of-scope/ambiguous text in a plan note. At Phase 2 completion the CLI was not yet connected; Phase 3 now consumes these units through the persistent adapter.

## 2026-10-25: Persistent Piper worker and mapped chunk stream

Use Piper 1.8.0's Python API in one supervised local worker process per synthesis session. It loads the selected voice once, accepts newline-delimited JSON requests on stdin, and writes each unit's PCM WAV to a temporary file; document text is not placed in process arguments or copied through JSON audio payloads. The Rust boundary is not introduced before there is a desktop core. Terminate the worker to cancel active ONNX inference because the Python synthesis call itself has no cooperative cancellation hook. Yield chunks through a bounded queue with the original narration unit and source offsets. Keep the existing executable override as a one-shot compatibility path, supplying text via a temporary file. Optional caller-configured cache keys include source hash, planner version, model/runtime identity, voice, speed, and unit text/span; eviction is deferred to Phase 4. The CLI currently combines chunks before browser playback, so this decision does not claim live playback.

## 2026-10-25: Phase 4 browser playback artifacts and cache cleanup

Keep playback in the existing generated local HTML page for this phase; do not add a server, Rust audio device layer, or frontend framework. Persist each successfully synthesized passage WAV in a unique run directory and reference it from the versioned JSON manifest; retain the combined `speech.wav` for compatibility. The player owns sequencing, segment/time seek mapping, rate, pause timers, local progress, and explicit retry/skip states. On regeneration, remove only old chunk files explicitly named by the prior manifest and constrained under the selected output's `chunks/` directory. Prune content-addressed cache WAVs by least-recently-used order toward 512 MiB, protecting entries needed by the active synthesis plan; this means the active plan can temporarily exceed the limit. Browser `localStorage` remains best-effort because `file:` origin policy varies. In this environment Firefox cannot launch due Snap confinement, so the code-level checks and real synthesis test do not constitute verified browser playback or saved progress. Synthesis currently finishes before opening the generated player; pause affects browser playback only, not inference.

## 2026-10-25: Phase 5 Tauri core and local media boundary

Add a minimal Tauri 2.10.3 crate and static frontend without introducing the Phase 6 React toolchain. Rust owns the selected PDF path, one active worker, current manifest/session state, and versioned per-document progress under app-local-data. Use the existing Python CLI rather than porting extraction or Piper. The frontend receives no filesystem access and no audio bytes via JSON. The first custom `sonara-audio://` media route produced WebKit media error 4 in a user smoke test. Replace it with one ephemeral HTTP listener bound to `127.0.0.1`, protected by a random per-launch token, strict Host check, active-session hash/index validation, canonical chunk-directory containment, bounded range responses, and CSP `media-src` restriction. The listener serves only WAV chunks and stops when the window closes. Spawn the Python process in its own Unix process group and terminate that group on cancel/close. Use a JSON progress file while the app has a single reader session; defer SQLite until there is library/history querying. The standard Tauri dialog crate was absent and crates.io was unreachable during implementation, so this prototype uses installed Zenity and explicitly supports Linux only. Keep Tauri bundling disabled because Python, runtime libraries, model files, and distribution licenses are not packaged/reviewed. Preserve the configured venv Python symlink so Python discovers its site-packages. Six Rust tests and the fast Python suite pass after the media transport change; GUI playback still needs a graphical retest.
## 2026-10-27: Piper defaults, reversible narration, and listening evaluation

Leave Piper `noise_scale` and `noise_w_scale` unspecified in the default worker request so the selected voice config supplies its own synthesis defaults. Optional `less`/`more` profiles are relative experiments (0.85×/1.10×, capped at 1.0); retain voice defaults unless a blinded, loudness-matched listening evaluation demonstrates a clear improvement. These parameters describe generator noise and phoneme-width variation, not pitch or emotion.

Keep source text and source offsets immutable. Apply conservative English abbreviation/unit normalization only to `spoken_text`, with ISO date and numeric citation expansion separately opt-in. Expose a preview of the planned spoken text. Refine only inter-unit pauses from punctuation and block structure; do not introduce per-sentence prosody changes without listening evidence.

Add a repeatable blind comparison pack with randomized IDs, a broader corpus, RMS level matching, and a separate facilitator key. Treat the pack as an evaluation protocol, not a quality result. Kokoro figures in the existing benchmark remain estimates until run and listened to on Sonara's target hardware.

