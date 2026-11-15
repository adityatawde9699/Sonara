"""Deterministic finishing for synthesized speech: edge trimming, level matching and fades.

Speech engines leave voice-specific silence at the edges of each utterance
(measured on the bundled Piper voices: from 3 ms to about 200 ms per chunk) and
render at voice-specific levels (about 2.3 dB apart). Narration pauses are
planned explicitly, so the built-in silence makes the same planned pause sound
different from voice to voice, and level jumps are audible when a listener
switches voice. Every chunk is therefore trimmed to a short fixed pad,
matched to one speech level, and given short fades so chunk edges never click.

The level measure is a two-stage gated RMS over 10 ms frames (absolute gate,
then a relative gate below the mean speech power), similar in spirit to
EBU R128 gating but without K-weighting. It is level matching, not LUFS.
"""

from __future__ import annotations

import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# Part of the TTS cache key: bump when finishing changes the produced audio.
AUDIO_FINISH_VERSION = "finish-1"

_FRAME_MS = 10
_ABSOLUTE_GATE_DBFS = -70.0
_RELATIVE_GATE_DB = -10.0


@dataclass(frozen=True)
class FinishSettings:
    """How a synthesized chunk is finished; all lengths in milliseconds."""

    lead_pad_ms: int = 15
    trail_pad_ms: int = 40
    # A frame counts as sound when it is within this range of the loudest
    # frame and above the absolute floor; quieter edge frames are trimmed.
    trim_below_peak_db: float = 45.0
    trim_floor_dbfs: float = -60.0
    target_speech_dbfs: float = -18.0
    peak_ceiling_dbfs: float = -1.0
    max_gain_db: float = 12.0
    fade_in_ms: int = 5
    fade_out_ms: int = 15


DEFAULT_FINISH = FinishSettings()


def _frame_rms(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    size = max(1, sample_rate * _FRAME_MS // 1000)
    count = len(samples) // size
    if count == 0:
        return np.sqrt(np.array([np.mean(samples**2)], dtype=np.float64)) if len(samples) else np.zeros(0)
    framed = samples[: count * size].reshape(count, size).astype(np.float64)
    rms = np.sqrt(np.mean(framed**2, axis=1))
    if len(samples) > count * size:
        tail = samples[count * size:].astype(np.float64)
        rms = np.append(rms, np.sqrt(np.mean(tail**2)))
    return rms


def _dbfs(value: float) -> float:
    return 20.0 * float(np.log10(max(value, 1e-12)))


def trim_silence(samples: np.ndarray, sample_rate: int, settings: FinishSettings = DEFAULT_FINISH) -> np.ndarray:
    """Remove edge silence beyond the configured pads; keep a silent chunk unchanged."""
    if len(samples) == 0:
        return samples
    rms = _frame_rms(samples, sample_rate)
    loudest = float(rms.max())
    if _dbfs(loudest) <= settings.trim_floor_dbfs:
        return samples
    threshold = max(loudest * 10 ** (-settings.trim_below_peak_db / 20), 10 ** (settings.trim_floor_dbfs / 20))
    active = np.nonzero(rms > threshold)[0]
    size = max(1, sample_rate * _FRAME_MS // 1000)
    start = max(0, int(active[0]) * size - sample_rate * settings.lead_pad_ms // 1000)
    end = min(len(samples), (int(active[-1]) + 1) * size + sample_rate * settings.trail_pad_ms // 1000)
    return samples[start:end]


def speech_level_dbfs(samples: np.ndarray, sample_rate: int) -> float | None:
    """Return the gated speech RMS in dBFS, or None when there is no speech."""
    rms = _frame_rms(samples, sample_rate)
    power = rms**2
    power = power[power > 10 ** (_ABSOLUTE_GATE_DBFS / 10)]
    if len(power) == 0:
        return None
    relative_gate = float(np.mean(power)) * 10 ** (_RELATIVE_GATE_DB / 10)
    gated = power[power >= relative_gate]
    return 10.0 * float(np.log10(float(np.mean(gated))))


def match_level(
    samples: np.ndarray, sample_rate: int, settings: FinishSettings = DEFAULT_FINISH,
) -> tuple[np.ndarray, float]:
    """Scale speech to the target gated level without exceeding the peak ceiling."""
    level = speech_level_dbfs(samples, sample_rate)
    if level is None:
        return samples, 0.0
    gain_db = max(-settings.max_gain_db, min(settings.max_gain_db, settings.target_speech_dbfs - level))
    peak = float(np.max(np.abs(samples)))
    if peak > 0:
        gain_db = min(gain_db, settings.peak_ceiling_dbfs - _dbfs(peak))
    return samples * np.float32(10 ** (gain_db / 20)), gain_db


def apply_fades(samples: np.ndarray, sample_rate: int, settings: FinishSettings = DEFAULT_FINISH) -> np.ndarray:
    """Apply raised-cosine fades so a chunk starts and ends at zero."""
    result = samples.copy()
    for length_ms, at_start in ((settings.fade_in_ms, True), (settings.fade_out_ms, False)):
        length = min(len(result) // 2, sample_rate * length_ms // 1000)
        if length <= 0:
            continue
        ramp = (0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, length, dtype=np.float32))).astype(np.float32)
        if at_start:
            result[:length] *= ramp
        else:
            result[-length:] *= ramp[::-1]
    return result


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(np.round(samples * 32767.0), -32768, 32767)).astype("<i2").tobytes()


def finish_samples(samples: np.ndarray, sample_rate: int, settings: FinishSettings = DEFAULT_FINISH) -> tuple[np.ndarray, float]:
    """Trim, level-match and fade one utterance; returns the samples and gain in dB."""
    trimmed = trim_silence(samples, sample_rate, settings)
    leveled, gain_db = match_level(trimmed, sample_rate, settings)
    return apply_fades(leveled, sample_rate, settings), gain_db


def finish_wav(path: Path, settings: FinishSettings = DEFAULT_FINISH) -> float:
    """Finish a mono 16-bit WAV in place (atomically); returns the applied gain in dB."""
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Audio finishing supports mono 16-bit PCM only.")
        sample_rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    finished, gain_db = finish_samples(pcm16_to_float(pcm), sample_rate, settings)
    descriptor, temporary = tempfile.mkstemp(prefix=".finish-", suffix=".wav", dir=path.parent)
    os.close(descriptor)
    try:
        with wave.open(temporary, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            target.writeframes(float_to_pcm16(finished))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return gain_db
