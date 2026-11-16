# Optional Kokoro setup

Sonara keeps Kokoro optional and keeps its runtime separate from the Piper environment. The app looks for Python at `.cache/kokoro-venv/bin/python` by default; override this with `SONARA_KOKORO_PYTHON` when launching Sonara.

The repository environment has been created with Python 3.12. Install the runtime when package access is available:

```bash
uv pip install --python .cache/kokoro-venv/bin/python kokoro-onnx
```

Place these two files in `models/kokoro/`:

- [`kokoro-v1.0.onnx`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx)
- [`voices-v1.0.bin`](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin)

The `kokoro-onnx` project documents those asset names, recommends Python 3.12, and identifies its wrapper as MIT and model as Apache 2.0. The upstream Kokoro model card also declares Apache 2.0. Review notices for the exact downloaded release before redistribution.

Sonara does not fetch model files automatically. Until the runtime and both assets exist, choosing Kokoro reports the missing dependency/model instead of substituting Piper silently. Piper remains the default engine.

## Languages

The first letter of a Kokoro voice ID sets its language. Sonara passes the matching espeak-ng language to kokoro-onnx's phonemizer, and the matching language to its narration planner:

| Prefix | Language | Voices in Settings | Notes |
|---|---|---|---|
| `a` | US English | 20 | English normalization rules apply |
| `b` | British English | 8 | English rules apply, with British date and unit readings |
| `e` | Spanish | 3 | spoken as written |
| `f` | French | 1 | spoken as written |
| `h` | Hindi | 4 | the danda (`।`) ends a sentence |
| `i` | Italian | 2 | spoken as written |
| `p` | Brazilian Portuguese | 3 | spoken as written |
| `z` | Mandarin Chinese | 8 | experimental; `。！？` end sentences and each character counts as a word for passage length |

Japanese (`j`) voices are not offered. kokoro-onnx phonemizes Japanese with espeak-ng, which reads kanji as "Chinese letter", while Kokoro's Japanese needs the misaki G2P, which Sonara does not ship. `sonara.py read --engine kokoro --voice jf_alpha` stops with that explanation.

Each language was synthesized once on 2026-11-16, and its phonemes were checked to be in that language (French was also run through the full `sonara.py read` path). Nobody who speaks these languages has listened to the results; treat the non-English voices as unreviewed. Choose a voice that matches the document's language: Sonara does not detect it.

