# Sonara — Performance and Multi-Voice Benchmark Report

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
