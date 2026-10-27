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
