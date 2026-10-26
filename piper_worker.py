"""Persistent Piper model worker; newline JSON on stdin/stdout, audio stays in WAV files."""

from __future__ import annotations

import json
import math
import sys
import wave
from pathlib import Path


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) not in (2, 3):
        _send({"type": "fatal", "error": "worker expects model path and optional configuration path"})
        return 2
    model_path = Path(sys.argv[1])
    config_path = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    try:
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        voice = PiperVoice.load(model_path, config_path=config_path, use_cuda=False, download_dir=None)
        effective_config = config_path or model_path.with_suffix(model_path.suffix + ".json")
        voice_metadata = json.loads(effective_config.read_text(encoding="utf-8"))
    except Exception as exc:
        _send({"type": "fatal", "error": f"Could not load Piper voice: {exc}"})
        return 2

    language = voice_metadata.get("language", {}).get("code", "unknown")
    _send({
        "type": "ready",
        "sample_rate": voice.config.sample_rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "language": language,
        "speaker_count": len(voice.config.speaker_id_map),
        "piper_version": _piper_version(),
    })

    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            text = request["text"]
            speed = float(request["speed"])
            variation = request.get("variation", "voice_default")
            output = Path(request["output_path"])
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            if not 0.5 <= speed <= 2.0:
                raise ValueError("speed must be between 0.5 and 2.0")
            noise_scale, noise_w_scale = _variation_scales(
                voice.config,
                variation,
                request.get("noise_scale"),
                request.get("noise_w_scale"),
            )
            config = SynthesisConfig(
                length_scale=1.0 / speed,
                noise_scale=float(noise_scale) if noise_scale is not None else None,
                noise_w_scale=float(noise_w_scale) if noise_w_scale is not None else None,
            )
            with wave.open(str(output), "wb") as wav_file:
                wav_file.setframerate(voice.config.sample_rate)
                wav_file.setsampwidth(2)
                wav_file.setnchannels(1)
                voice.synthesize_wav(text, wav_file, syn_config=config, set_wav_format=False)
                if wav_file.tell() == 0:
                    # Text contained only punctuation/symbols with no speakable phonemes (e.g. "...", "---", "•").
                    # Emit a brief slice of silence (0.1s) so the chunk is a valid, playable audio file.
                    silence_frames = max(1, int(voice.config.sample_rate * 0.1))
                    wav_file.writeframes(b"\x00" * (silence_frames * 2))
            with wave.open(str(output), "rb") as wav_file:
                _send({
                    "id": request_id,
                    "ok": True,
                    "frames": wav_file.getnframes(),
                    "sample_rate": wav_file.getframerate(),
                    "channels": wav_file.getnchannels(),
                    "sample_width_bytes": wav_file.getsampwidth(),
                })
        except Exception as exc:
            try:
                output_path = Path(request.get("output_path", ""))
                output_path.unlink(missing_ok=True)
            except (NameError, OSError, ValueError):
                pass
            _send({
                "id": request.get("id") if isinstance(request, dict) else None,
                "ok": False,
                "error": str(exc),
            })
    return 0


def _adjust_variation(value: float, factor: float) -> float:
    """Scale a voice's own setting while avoiding values beyond Piper's usual range."""
    return max(0.0, min(1.0, float(value) * factor))


def _variation_scales(config, variation: str, noise_scale=None, noise_w_scale=None):
    if variation not in {"voice_default", "less", "more"}:
        raise ValueError("variation must be voice_default, less, or more")
    if variation != "voice_default" and noise_scale is None and noise_w_scale is None:
        factor = 0.85 if variation == "less" else 1.10
        noise_scale = _adjust_variation(config.noise_scale, factor)
        noise_w_scale = _adjust_variation(config.noise_w_scale, factor)
    for value in (noise_scale, noise_w_scale):
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0 or float(value) > 1):
            raise ValueError("Piper variation values must be between 0 and 1")
    return noise_scale, noise_w_scale


def _piper_version() -> str:
    try:
        from importlib.metadata import version

        return version("piper-tts")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
