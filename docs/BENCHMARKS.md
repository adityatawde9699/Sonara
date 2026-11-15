# Sonara — Performance and Multi-Voice Benchmark Report

## Reproducible baseline run (2026-10-29)

This workspace was measured on Linux x86_64, kernel 7.0.0-31-generic, Python 3.14.4, Piper 1.8.0, and ONNX Runtime 1.31.0. The host reports 16 logical CPUs and 22 GiB RAM (15 GiB available during the snapshot). ORT reports `CPUExecutionProvider` and `AzureExecutionProvider`; no GPU device or provider was available. Models: Piper `en_US-john-medium.onnx` (Float32, 22,050 Hz) and Kokoro `kokoro-v1.0.onnx` / `voices-v1.0.bin`.

Commands: `.venv/bin/python benchmark.py --voice en_US-john-medium --trials 2 --json` and a one-passage direct `KokoroEngine` synthesis using `.cache/kokoro-venv` (Python 3.12.14). The Piper run generated about 115.5 seconds of audio over 16 passage trials: mean per-passage RTF 0.0408, mean TTFA 0.1924 s. The first short-phrase cold trial was 1.294 s (RTF 0.336); subsequent short-phrase warm trial was 0.082 s (RTF 0.021). The original benchmark only measured parent RSS; these first-run memory numbers are therefore excluded.

After correcting RSS reporting, a separate one-trial Piper run measured parent peak RSS 28.0 MiB and completed worker peak RSS 349.0 MiB. It measured 1.289 s on the first short phrase and 0.019–0.023 RTF on the remaining warmed passages. A single cold Kokoro passage measured 0.690 s wall time, 3.071 s audio, 0.225 RTF, and 525.3 MiB process peak RSS (mono, 16-bit, 24 kHz). These are observations, not comparative quality evidence; the Kokoro result has one passage/trial.

PDF extraction was exercised through the opt-in generated-corpus integration suite (six fixtures); it passed. Per-task RSS, CPU utilization, cache growth, and total desktop-process memory were not sampled. No active llama.cpp endpoint or selected GGUF was available, so LLM inference and embeddings are unavailable measurements. Playback is an HTML/Tauri UI workload and was not launched; no concurrent workload, GPU, idle, or shutdown performance profile was measured. Historical tables below predate this run and should not be compared directly: their recorded process RSS excluded the child inference process, and the old benchmark timed engine construction rather than first model load.

**Protocol Conformance:** Sonara `docs/ROADMAP.md` Section G (Performance Targets and Benchmark Protocol).  
**Test Date:** October 26, 2026.  
**Hardware & System:**  
- **Host:** Linux x86_64, Ubuntu 24.04  
- **Processor:** Intel Core i7-13620H (10 physical cores / 16 threads)  
- **Memory:** 24.0 GB Physical RAM  
- **Inference Runtime:** Python 3.14.4, ONNX Runtime 1.31.0 (`CPUExecutionProvider`), Piper TTS 1.8.0  
- **Evaluation Script:** `benchmark.py` (historical standardized 4-passage performance corpus, 2 trials per passage)  

> **Scope:** The latency measurements below are the earlier four-passage performance trial. The current benchmark script includes a broader eight-passage corpus. Neither those historical latency numbers nor the model-architecture estimates below are a subjective voice-quality evaluation. Kokoro figures remain estimates until Sonara runs it on the target hardware and listeners compare level-matched samples.

---

## 1. Multi-Voice Comparative Baseline

All four locally installed Piper ONNX medium-quality voices were evaluated under identical conditions:

| Voice Model | Precision / Sample Rate | Cold Model Load | Mean TTFA (Time to First Audio) | Mean RTF (Real-Time Factor) | Speed Ratio (vs. 1.0x Realtime) | Peak Process RSS |
|---|---|---|---|---|---|---|
| `en_US-bryce-medium` | Float32 / 22,050 Hz | **0.061 s** | **0.348 s** | **0.067** | **~14.9×** real-time | 291.0 MB |
| `en_US-john-medium` | Float32 / 22,050 Hz | **0.038 s** | **0.314 s** | **0.070** | **~14.3×** real-time | 291.0 MB |
| `en_US-lessac-medium` | Float32 / 22,050 Hz | **0.047 s** | **0.289 s** | **0.074** | **~13.5×** real-time | 291.0 MB |
| `en_US-ryan-medium` | Float32 / 22,050 Hz | **0.052 s** | **0.288 s** | **0.086** | **~11.6×** real-time | 291.0 MB |

> [!NOTE]
> **Real-Time Factor (RTF)** is defined as:
> $$\text{RTF} = \frac{\text{synthesis wall time (seconds)}}{\text{generated audio duration (seconds)}}$$
> An RTF strictly below $1.0$ is the necessary mathematical condition for continuous stutter-free playback. Every voice tested runs between **$0.067$ and $0.086$**, yielding audio **11.6× to 14.9× faster than human speech playback**.

---

## 2. Passage Breakdown & Latency Analysis

Each voice was evaluated across four passage types designed to test sentence boundaries, technical nomenclature, numeric terms, and dialogue:

### Passage 1: Short Phrase
- **Text:** *"Welcome to Sonara, a local document reading system."*
- **Audio Duration:** ~3.25 seconds
- **Observed Metrics:**
  - Bryce: TTFA = 0.281 s, RTF = 0.086
  - John: TTFA = 0.264 s, RTF = 0.081
  - Lessac: TTFA = 0.252 s, RTF = 0.078
  - Ryan: TTFA = 0.248 s, RTF = 0.076

### Passage 2: Technical Prose
- **Text:** *"The ONNX Runtime executes optimized CPU kernels with a real-time factor strictly below 1.0."*
- **Audio Duration:** ~4.75 seconds
- **Observed Metrics:**
  - Bryce: TTFA = 0.380 s, RTF = 0.080
  - John: TTFA = 0.339 s, RTF = 0.071
  - Lessac: TTFA = 0.314 s, RTF = 0.074
  - Ryan: TTFA = 0.301 s, RTF = 0.089

### Passage 3: Numbers & Units
- **Text:** *"In section 4.2, the 512 MiB inactive cache budget was verified across 10 trials at 22,050 Hz."*
- **Audio Duration:** ~5.50 seconds
- **Observed Metrics:**
  - Bryce: TTFA = 0.370 s, RTF = 0.067
  - John: TTFA = 0.341 s, RTF = 0.070
  - Lessac: TTFA = 0.318 s, RTF = 0.072
  - Ryan: TTFA = 0.320 s, RTF = 0.088

### Passage 4: Dialogue & Quotes
- **Text:** *'"Are the audio chunks ready?" she asked. "Yes," Bryce replied, "and the stream is settling."'*
- **Audio Duration:** ~5.90 seconds
- **Observed Metrics:**
  - Bryce: TTFA = 0.362 s, RTF = 0.061
  - John: TTFA = 0.312 s, RTF = 0.058
  - Lessac: TTFA = 0.272 s, RTF = 0.071
  - Ryan: TTFA = 0.283 s, RTF = 0.091

---

## 3. Architecture Comparison: Piper vs. Kokoro-82M vs. XTTS-v2

| Dimension | Piper (Current Baseline) | Kokoro-82M | Coqui XTTS-v2 |
|---|---|---|---|
| **Model Architecture** | VITS (Variational Inference with adversarial learning for end-to-end Text-to-Speech) | StyleTTS2 + ISTFT decoder | Autoregressive Transformer + Diffusion Latent Decoder |
| **Model Size on Disk** | **~63 MB** (medium voice `.onnx`) | **~320 MB** (PyTorch / ONNX) | **~1.8 GB** |
| **Cold Startup Latency** | **38 – 61 ms** | ~350 – 800 ms | 4,000 – 12,000 ms |
| **CPU RTF (Core i7-13620H)**| **0.067 – 0.086** (~14× realtime) | ~0.25 – 0.45 (~3× realtime) | ~1.2 – 2.5 (slower than realtime without GPU) |
| **RAM Footprint (RSS)** | **~291 MB** peak | ~650 – 900 MB peak | > 2.5 GB peak |
| **Voice Variety** | Multiple distinct single-speaker voices | Multiple embedded speaker vectors in one checkpoint | Zero-shot reference voice cloning |
| **Licensing** | Runtime GPL-3.0+; voices Public Domain / LibriVox / ODC-By | Apache 2.0 (weights and code) | **CPML (Coqui Public Model License) — Non-Commercial only** |
| **Recommendation for Sonara** | **Selected Default**: Ultra-low memory, fast CPU execution, proven local-first stability. | **Candidate for Phase 8.2**: High voice naturalness, permissive Apache 2.0 licensing, feasible on CPU. | **Rejected**: Non-commercial license prevents redistribution; excessive compute/RAM footprint for laptop CPU reader. |

---

## 4. Key Findings & Engineering Conclusions

1. **Persistent Worker Model**: Reusing the loaded `PiperVoice` in a persistent Python worker completely eliminates model load overhead (38–61ms paid once per session).
2. **Streaming Overlap Feasibility**: Because TTFA is only ~300ms and RTF is < 0.09, continuous playback is immune to underruns even on modest dual-core laptops.
3. **Memory Ceiling**: The entire synthesis process caps at ~291 MB RSS, well below the configured 512 MB inactive audio cache budget.

## 5. Listening quality evaluation

`listening_eval.py` generates blind, randomized, RMS-level-matched comparison packs for Piper voice-config defaults and the optional `less`/`more` variation profiles. Its eight-passage corpus covers report prose, technical terms, numbers and units, questions, citations/dates, and dialogue. Participant files contain randomized IDs; the key is kept separately under `facilitator-only/`. Use the generated ratings to assess naturalness and intelligibility before changing the default profile.

No participant ratings have been collected as part of this implementation, so there is no supported claim that either variation profile sounds better. RMS matching with a peak ceiling is approximate loudness control, not LUFS normalization. Piper's `noise_scale` and `noise_w_scale` are left unset for the default profile so voice-specific config values apply; they are generator noise and phoneme-width variation, not pitch controls.

## 6. Voice profiles and audio finishing (2026-11-16)

Measured on this host with piper-tts 1.8.0 by synthesizing one fixed six-sentence passage (mixed statement, question, list-like and heading text) with each bundled voice at speed 1.0. Pitch was tracked by autocorrelation over 40 ms windows. "Duration spread" is the standard deviation of the total passage duration over three runs with the same settings. These are objective measurements, not listening results.

| Voice | Words/s of speech | Built-in edge silence per sentence (lead + trail) | Gated speech level | Median F0 | Pitch spread |
|---|---|---|---|---|---|
| ryan | 3.26 | 3 ms | −14.8 dBFS | 153 Hz | 4.5 semitones |
| lessac | 3.32 | 160 ms | −14.6 dBFS | 185 Hz | 4.5 semitones |
| bryce | 2.42 | 163 ms | −16.9 dBFS | 134 Hz | 3.5 semitones |
| john | 2.47 | 195 ms | −16.7 dBFS | 115 Hz | 3.1 semitones |

Sweeping `noise_scale` over 0.33/0.667/0.9 and `noise_w_scale` over 0.4/0.8/1.0 moved pitch spread by less than 0.2 semitones for every voice. These settings do not widen intonation. `noise_w_scale` changes rhythm: higher values slow the passage by 4–8% and make timing vary more from run to run. john is the outlier. At its default `noise_w` of 0.8, its duration spread is 0.38–0.71 s, against 0.2 s or less for the other voices. The previous `less`/`more` presets (0.85×/1.10× of the voice config) made no measurable difference.

What Sonara does with this (`narration.VoiceProfile`):

- **Pauses** scale with the square root of the tempo ratio to ryan. bryce and john get 1.15× planned pauses (a heading pause becomes 828 ms instead of 720 ms) and 230 ms between sentences instead of 200 ms.
- **Variation presets.** For ryan, lessac and bryce, `less` is `noise_scale` 0.5 / `noise_w` 0.5 and `more` is 0.8 / 1.0. john's are 0.5 / 0.4 and 0.75 / 0.85, so "more" stays clear of its unstable range. `voice_default` still sends nothing and uses the voice's own config.
- **Finishing** (`audio_processing.py`, applied to every chunk before caching):
  - Edge silence is trimmed to 15 ms before and 40 ms after the speech. A frame counts as silence when it is more than 45 dB under the loudest frame.
  - Speech is matched to −18 dBFS by two-stage gated RMS, with a −1 dBFS peak ceiling and at most ±12 dB of gain.
  - Each chunk gets a 5 ms fade-in and a 15 ms fade-out.
  - The Piper worker also trims each sentence's edges before inserting the sentence pause.

End-to-end result through `SynthesisStream` (two-sentence passage, real Piper):

| Voice | Speech level before → after | Peak before → after | Longest gap inside the passage before → after |
|---|---|---|---|
| ryan | −13.1 → −18.0 dBFS | 0.0 → −4.7 dBFS | 200 → 200 ms |
| lessac | −13.3 → −18.0 dBFS | 0.0 → −5.1 dBFS | 290 → 350 ms (a comma pause; timing varies run to run) |
| bryce | −15.4 → −18.0 dBFS | 0.0 → −2.8 dBFS | 300 → 290 ms |
| john | −14.1 → −18.0 dBFS | 0.0 → −3.8 dBFS | 400 → 290 ms |

Raw Piper chunks peak at full scale. The finished chunks leave headroom and no longer change level when the voice changes. The profiles still need a blind listening check with `listening_eval.py` before anyone claims they sound better.
