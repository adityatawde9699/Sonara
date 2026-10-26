#!/usr/bin/env python3
"""Create a blind, loudness-matched Piper listening comparison pack."""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import random
import struct
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

from benchmark import BENCHMARK_PASSAGES, make_benchmark_document
from narration import build_narration_plan
from tts_engine import PiperEngine, SynthesisStream


VARIATIONS = ("voice_default", "less", "more")
TARGET_RMS_DBFS = -20.0
PEAK_LIMIT_DBFS = -1.0


def _voice_language(voice: str) -> str:
    language = voice.split("-", 1)[0]
    return language if "_" in language else "und"


def _write_sample(engine: PiperEngine, plan, destination: Path) -> None:
    sample_rate = engine.capabilities.audio_format.sample_rate
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as combined:
        combined.setnchannels(1)
        combined.setsampwidth(2)
        combined.setframerate(sample_rate)
        with SynthesisStream(engine, plan, prefetch_chunks=1) as stream:
            chunks = iter(stream)
            for index, chunk in enumerate(chunks):
                with wave.open(str(chunk.wav_path), "rb") as audio:
                    if audio.getframerate() != sample_rate or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                        raise ValueError("Piper returned an unexpected audio format for the listening evaluation.")
                    combined.writeframes(audio.readframes(audio.getnframes()))
                if index + 1 < len(plan.units):
                    pause_frames = round(sample_rate * plan.units[index].pause_after_ms / 1000)
                    if pause_frames > 0:
                        combined.writeframes(b"\0\0" * pause_frames)


def loudness_match_wav(
    path: Path,
    *,
    target_rms_dbfs: float = TARGET_RMS_DBFS,
    peak_limit_dbfs: float = PEAK_LIMIT_DBFS,
) -> float:
    """RMS-match mono 16-bit PCM and cap peaks; returns applied gain in dB."""
    with wave.open(str(path), "rb") as source:
        if source.getcomptype() != "NONE" or source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Listening samples must be uncompressed mono 16-bit PCM WAV.")
        sample_rate = source.getframerate()
        samples = list(struct.iter_unpack("<h", source.readframes(source.getnframes())))
    values = [sample[0] for sample in samples]
    if not values:
        raise ValueError("Cannot loudness-match an empty WAV.")
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    if rms == 0:
        gain_db = 0.0
    else:
        desired_rms = 32768 * (10 ** (target_rms_dbfs / 20))
        peak_limit = 32767 * (10 ** (peak_limit_dbfs / 20))
        target_gain = desired_rms / rms
        observed_peak = max(abs(value) for value in values)
        peak_gain = peak_limit / observed_peak if observed_peak else target_gain
        gain = min(target_gain, peak_gain)
        gain_db = 20 * math.log10(gain) if gain > 0 else 0.0
        values = [max(-32768, min(32767, round(value * gain))) for value in values]

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(values)}h", *values))
    return gain_db


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def create_listening_pack(
    voice: str,
    models_dir: Path,
    output_dir: Path,
    *,
    seed: int = 20261027,
    repeats: int = 1,
    expand_dates: bool = True,
    expand_citations: bool = True,
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    model_path = models_dir / f"{voice}.onnx"
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError(f"Piper model and config must exist for voice {voice!r} in {models_dir}")

    rng = random.Random(seed)
    participant_dir = output_dir / "participant-pack"
    facilitator_dir = output_dir / "facilitator-only"
    clips_dir = participant_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    facilitator_dir.mkdir(parents=True, exist_ok=True)
    key_rows: list[dict[str, object]] = []
    rating_rows: list[dict[str, object]] = []
    voice_language = _voice_language(voice)

    for variation in VARIATIONS:
        engine = PiperEngine(model_path, config_path, variation=variation)
        try:
            for group_index, (passage_name, text) in enumerate(BENCHMARK_PASSAGES, start=1):
                for repeat in range(1, repeats + 1):
                    plan = build_narration_plan(
                        make_benchmark_document(text),
                        language=voice_language,
                        expand_dates=expand_dates,
                        expand_citations=expand_citations,
                    )
                    clip_id = f"clip-{rng.getrandbits(48):012x}"
                    clip_path = clips_dir / f"{clip_id}.wav"
                    _write_sample(engine, plan, clip_path)
                    gain_db = loudness_match_wav(clip_path)
                    group_id = f"prompt-{group_index:02d}" + (f"-take-{repeat:02d}" if repeats > 1 else "")
                    key_rows.append({
                        "clip_id": clip_id,
                        "comparison_group": group_id,
                        "passage": passage_name,
                        "variation": variation,
                        "normalization": "english_rules_on",
                        "rms_gain_db": round(gain_db, 2),
                    })
                    rating_rows.append({
                        "comparison_group": group_id,
                        "clip_id": clip_id,
                        "naturalness_1_to_5": "",
                        "intelligibility_1_to_5": "",
                        "preferred_in_group": "",
                        "notes": "",
                    })
        finally:
            engine.close()

    rng.shuffle(rating_rows)
    _write_csv(
        participant_dir / "blind-ratings.csv",
        ["comparison_group", "clip_id", "naturalness_1_to_5", "intelligibility_1_to_5", "preferred_in_group", "notes"],
        rating_rows,
    )
    _write_csv(
        facilitator_dir / "facilitator-key.csv",
        ["clip_id", "comparison_group", "passage", "variation", "normalization", "rms_gain_db"],
        key_rows,
    )
    (participant_dir / "LISTENING-INSTRUCTIONS.txt").write_text(
        "Blind Sonara narration comparison\n\n"
        "Give listeners the clips/ folder and blind-ratings.csv only. Keep facilitator-key.csv private until ratings are complete.\n"
        "Compare clips with the same comparison_group. Rate naturalness and intelligibility from 1 (poor) to 5 (excellent).\n"
        "Mark one preferred clip per group. Use consistent headphones and playback volume; avoid showing filenames from the key.\n"
        "Samples are RMS matched to a -20 dBFS target with a -1 dBFS peak ceiling. This is level matching, not LUFS normalization.\n"
        "The ratings are subjective evidence; they do not replace a latency or intelligibility measurement.\n",
        encoding="utf-8",
    )
    metadata: dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "voice": voice,
        "variations": list(VARIATIONS),
        "passages": [{"name": name, "text": text} for name, text in BENCHMARK_PASSAGES],
        "repeats_per_condition": repeats,
        "random_seed": seed,
        "normalization": {"language": voice_language, "expand_dates": expand_dates, "expand_citations": expand_citations},
        "level_match": {"method": "whole-clip RMS with peak ceiling", "target_dbfs": TARGET_RMS_DBFS, "peak_limit_dbfs": PEAK_LIMIT_DBFS},
        "runtime": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "rating_count": len(rating_rows),
    }
    (facilitator_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate blind, level-matched local Piper comparison clips.")
    parser.add_argument("--voice", default="en_US-john-medium")
    parser.add_argument("--models-dir", type=Path, default=Path("models/piper"))
    parser.add_argument("--output-dir", type=Path, default=Path("listening-evaluation"))
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--repeats", type=int, default=1, help="Independent audio takes per passage and variation")
    parser.add_argument("--keep-dates-raw", action="store_true", help="Do not expand ISO dates in spoken text")
    parser.add_argument("--keep-citations-raw", action="store_true", help="Do not expand bracketed numeric citations")
    args = parser.parse_args(argv)
    try:
        metadata = create_listening_pack(
            args.voice,
            args.models_dir.expanduser().resolve(),
            args.output_dir.expanduser().resolve(),
            seed=args.seed,
            repeats=args.repeats,
            expand_dates=not args.keep_dates_raw,
            expand_citations=not args.keep_citations_raw,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"listening_eval: {exc}", file=sys.stderr)
        return 2
    print(f"Created {metadata['rating_count']} blind clips in {args.output_dir.resolve() / 'participant-pack'}")
    print(f"Facilitator mapping and run metadata: {args.output_dir.resolve() / 'facilitator-only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
