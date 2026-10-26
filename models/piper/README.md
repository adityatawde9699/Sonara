# Local Piper voice records

This directory contains locally installed Piper neural speech models for Sonara development, testing, and listening. The ONNX models are intentionally ignored by Git; this record documents local integrity and upstream provenance.

## Installed voices

| Voice ID | Description | Sample rate | ONNX Size | ONNX SHA-256 | Config SHA-256 |
|---|---|---|---|---|---|
| `en_US-ryan-medium` | Ryan (American Male · Natural, articulate) | 22,050 Hz | 63,531,379 bytes | `abf4c274862564ed647ba0d2c47f8ee7c9b717d27bdad9219100eb310db4047a` | `44034c056cb15681b2ad494307c7f3f2e4499d1253c700c711fa0a4607ffe78d` |
| `en_US-lessac-medium` | Lessac (American Female · Expressive, clear) | 22,050 Hz | 63,201,294 bytes | `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f` | `efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0` |
| `en_US-bryce-medium` | Bryce (American Male · Narrative, warm) | 22,050 Hz | 63,531,379 bytes | `dc9caa6c313199ffb5ac698b6e542fa6cba388aeaf2731e25262e33b9810aef1` | `7ceb1bc4af6d4e41b6d1edbb86c67e91e01eaa71f66db4cd0ae92ac704d415be` |
| `en_US-john-medium` | John (American Male · LibriVox public domain) | 22,050 Hz | 63,531,379 bytes | `789c6c875726e627ddee93d51d8727859abe9c091c3d141591f4b83c2072e988` | `af60f177b6b550f3d7a302720c0fb89e7f94a82b5dca464775ef63b1c69ba09a` |

## Provenance

All models originate from the official [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices) repository. Models can be previewed audio-wise on the [Piper Samples Webpage](https://rhasspy.github.io/piper-samples/).

- Upstream repository: `https://huggingface.co/rhasspy/piper-voices`
- Piper runtime: `piper-tts` (GPL-3.0-or-later) with ONNX Runtime CPU.

## Verification

From the repository root:

```sh
sha256sum models/piper/*.onnx models/piper/*.onnx.json
```
