#!/usr/bin/env python3
"""Blind, loudness-matched listening comparison: create packs, analyze ratings.

``listening_eval.py`` writes a participant pack of anonymised clips (Piper
variations, and Kokoro when ``--kokoro-dir`` is given) plus a private
facilitator key. ``listening_eval.py analyze`` reads the completed rating
sheets with that key and reports per-condition scores with bootstrap
confidence intervals, paired differences against the baseline, and
preference shares.

The tooling cannot run the study: ratings must come from human listeners.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import random
import statistics
import struct
import sys
import wave
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from benchmark import BENCHMARK_PASSAGES, make_benchmark_document
from narration import build_narration_plan
from sonara import _voice_language
from tts_engine import KokoroEngine, PiperEngine, SpeechEngine, SynthesisStream, kokoro_language, validate_voice_name


VARIATIONS = ("voice_default", "less", "more")
BASELINE_CONDITION = "piper:voice_default"
TARGET_RMS_DBFS = -20.0
PEAK_LIMIT_DBFS = -1.0
RATING_FIELDS = ("naturalness_1_to_5", "intelligibility_1_to_5")
BLIND_FIELDS = ["comparison_group", "clip_id", "naturalness_1_to_5", "intelligibility_1_to_5", "preferred_in_group", "notes"]
KEY_FIELDS = ["clip_id", "comparison_group", "passage", "condition", "engine", "voice", "variation", "normalization", "rms_gain_db"]


@dataclass(frozen=True)
class Condition:
    """One arm of the comparison, such as ``piper:less`` or ``kokoro:af_sarah``."""

    name: str
    engine: str
    voice: str
    variation: str
    language: str
    open: Callable[[], SpeechEngine]


def piper_conditions(voice: str, models_dir: Path) -> list[Condition]:
    model_path = models_dir / f"{validate_voice_name(voice)}.onnx"
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError(f"Piper model and config must exist for voice {voice!r} in {models_dir}")
    return [
        Condition(
            f"piper:{variation}", "piper", voice, variation, _voice_language(voice),
            lambda variation=variation: PiperEngine(model_path, config_path, variation=variation),
        )
        for variation in VARIATIONS
    ]


def kokoro_condition(model_dir: Path, voice: str) -> Condition:
    try:
        language = kokoro_language(voice)[1]
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    return Condition(f"kokoro:{voice}", "kokoro", voice, "voice_default", language, lambda: KokoroEngine(model_dir, voice))


def _write_sample(engine: SpeechEngine, plan, destination: Path) -> None:
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
                        raise ValueError("The engine returned an unexpected audio format for the listening evaluation.")
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
    conditions: Sequence[Condition] | None = None,
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    if conditions is None:
        conditions = piper_conditions(voice, models_dir)
    if len({condition.name for condition in conditions}) != len(conditions) or len(conditions) < 2:
        raise ValueError("A comparison needs at least two distinct conditions.")

    rng = random.Random(seed)
    participant_dir = output_dir / "participant-pack"
    facilitator_dir = output_dir / "facilitator-only"
    clips_dir = participant_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    facilitator_dir.mkdir(parents=True, exist_ok=True)
    key_rows: list[dict[str, object]] = []
    rating_rows: list[dict[str, object]] = []

    for condition in conditions:
        engine = condition.open()
        try:
            for group_index, (passage_name, text) in enumerate(BENCHMARK_PASSAGES, start=1):
                for repeat in range(1, repeats + 1):
                    plan = build_narration_plan(
                        make_benchmark_document(text),
                        language=condition.language,
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
                        "condition": condition.name,
                        "engine": condition.engine,
                        "voice": condition.voice,
                        "variation": condition.variation,
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
    _write_csv(participant_dir / "blind-ratings.csv", BLIND_FIELDS, rating_rows)
    _write_csv(facilitator_dir / "facilitator-key.csv", KEY_FIELDS, key_rows)
    (participant_dir / "LISTENING-INSTRUCTIONS.txt").write_text(
        "Blind Sonara narration comparison\n\n"
        "Give listeners the clips/ folder and blind-ratings.csv only. Keep facilitator-key.csv private until ratings are complete.\n"
        "Each listener fills in their own copy of blind-ratings.csv and returns it under a pseudonymous file name, such as listener-07.csv.\n"
        "Compare clips with the same comparison_group. Rate naturalness and intelligibility from 1 (poor) to 5 (excellent).\n"
        "Mark one preferred clip per group with an x in preferred_in_group. Use consistent headphones and playback volume.\n"
        "Samples are RMS matched to a -20 dBFS target with a -1 dBFS peak ceiling. This is level matching, not LUFS normalization.\n"
        "Engines may differ in sample rate (Piper 22.05 kHz, Kokoro 24 kHz); that difference is part of what is compared.\n"
        "The ratings are subjective evidence; they do not replace a latency or intelligibility measurement.\n",
        encoding="utf-8",
    )
    metadata: dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "voice": voice,
        "conditions": [
            {"name": c.name, "engine": c.engine, "voice": c.voice, "variation": c.variation, "language": c.language}
            for c in conditions
        ],
        "variations": list(VARIATIONS),
        "passages": [{"name": name, "text": text} for name, text in BENCHMARK_PASSAGES],
        "repeats_per_condition": repeats,
        "random_seed": seed,
        "normalization": {"expand_dates": expand_dates, "expand_citations": expand_citations},
        "level_match": {"method": "whole-clip RMS with peak ceiling", "target_dbfs": TARGET_RMS_DBFS, "peak_limit_dbfs": PEAK_LIMIT_DBFS},
        "runtime": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "rating_count": len(rating_rows),
    }
    (facilitator_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


# ── Rating analysis ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Rating:
    rater: str
    clip_id: str
    group: str
    condition: str
    naturalness: int
    intelligibility: int
    preferred: bool


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _score(value: str, field: str, where: str) -> int:
    text = (value or "").strip()
    if text not in {"1", "2", "3", "4", "5"}:
        raise ValueError(f"{where}: {field} must be a whole number from 1 to 5, got {text!r}")
    return int(text)


def load_ratings(key_path: Path, rating_paths: Iterable[Path]) -> tuple[list[Rating], list[str]]:
    """Join rating sheets to the key. Returns ratings and per-sheet warnings.

    A sheet is one listener; its file stem is the rater ID. Every row must
    carry two valid scores, and each group needs exactly one preferred clip.
    Rows for unknown clips, or a group placed differently than the key says,
    are errors: the sheet was edited or belongs to another pack.
    """
    key = {row["clip_id"]: row for row in _read_csv(key_path)}
    if not key:
        raise ValueError(f"{key_path} has no clips.")
    if "condition" not in next(iter(key.values())):
        # Keys from before engine comparisons only had Piper variations.
        for row in key.values():
            row["condition"] = f"piper:{row['variation']}"
    ratings: list[Rating] = []
    warnings: list[str] = []
    raters: set[str] = set()
    for path in rating_paths:
        rater = path.stem
        if rater in raters:
            raise ValueError(f"Two rating sheets are named {rater!r}; give each listener a unique file name.")
        raters.add(rater)
        rows = _read_csv(path)
        seen: set[str] = set()
        preferred_by_group: dict[str, int] = defaultdict(int)
        sheet: list[Rating] = []
        for number, row in enumerate(rows, start=2):
            where = f"{path.name} line {number}"
            clip_id = (row.get("clip_id") or "").strip()
            if clip_id not in key:
                raise ValueError(f"{where}: clip {clip_id!r} is not in the facilitator key.")
            if clip_id in seen:
                raise ValueError(f"{where}: clip {clip_id} is rated twice.")
            seen.add(clip_id)
            group = key[clip_id]["comparison_group"]
            if (row.get("comparison_group") or "").strip() != group:
                raise ValueError(f"{where}: clip {clip_id} belongs to {group}, not {row.get('comparison_group')!r}.")
            preferred = bool((row.get("preferred_in_group") or "").strip())
            preferred_by_group[group] += preferred
            sheet.append(Rating(
                rater, clip_id, group, key[clip_id]["condition"],
                _score(row.get(RATING_FIELDS[0], ""), RATING_FIELDS[0], where),
                _score(row.get(RATING_FIELDS[1], ""), RATING_FIELDS[1], where),
                preferred,
            ))
        missing = len(key) - len(seen)
        if missing:
            warnings.append(f"{rater}: {missing} of {len(key)} clips were not rated.")
        groups = {rating.group for rating in sheet}
        bad = sorted(group for group in groups if preferred_by_group[group] != 1)
        if bad:
            warnings.append(f"{rater}: preferences ignored for {', '.join(bad)} (need exactly one per group).")
            sheet = [Rating(**{**r.__dict__, "preferred": False}) if r.group in bad else r for r in sheet]
        ratings.extend(sheet)
    if not ratings:
        raise ValueError("No ratings were read.")
    return ratings, warnings


def _bootstrap_ci(
    raters: Sequence[str], statistic: Callable[[Sequence[str]], float | None], *, samples: int, seed: int,
) -> tuple[float, float] | None:
    """Percentile 95% interval, resampling listeners (not clips) with replacement.

    Ratings from one listener are correlated, so resampling individual rows
    would understate the uncertainty.
    """
    if len(raters) < 2:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(samples):
        value = statistic([rng.choice(raters) for _ in raters])
        if value is not None:
            values.append(value)
    if len(values) < samples // 2:
        return None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


def analyze_ratings(
    ratings: Sequence[Rating], *, baseline: str = BASELINE_CONDITION, samples: int = 2000, seed: int = 20261116,
) -> dict[str, object]:
    by_rater: dict[str, list[Rating]] = defaultdict(list)
    for rating in ratings:
        by_rater[rating.rater].append(rating)
    raters = sorted(by_rater)
    conditions = sorted({rating.condition for rating in ratings})
    if baseline not in conditions:
        baseline = conditions[0]

    def mean_of(condition: str, field: str, sample: Sequence[str]) -> float | None:
        values = [getattr(r, field) for rater in sample for r in by_rater[rater] if r.condition == condition]
        return statistics.fmean(values) if values else None

    def paired_difference(condition: str, field: str, sample: Sequence[str]) -> float | None:
        # Difference within each listener and comparison group, so passage
        # difficulty and listener leniency cancel out.
        differences = []
        for rater in sample:
            cells: dict[tuple[str, str], int] = {}
            for r in by_rater[rater]:
                if r.condition in (condition, baseline):
                    cells[(r.group, r.condition)] = getattr(r, field)
            for group in {g for g, _ in cells}:
                if (group, condition) in cells and (group, baseline) in cells:
                    differences.append(cells[(group, condition)] - cells[(group, baseline)])
        return statistics.fmean(differences) if differences else None

    def preference_share(condition: str, sample: Sequence[str]) -> float | None:
        # A bootstrap sample can hold one listener more than once; each copy
        # counts, so wins and decisions are both counted per copy.
        decisions = [r for rater in sample for r in by_rater[rater] if r.preferred]
        if not decisions:
            return None
        return sum(1 for r in decisions if r.condition == condition) / len(decisions)

    report_conditions = []
    for index, condition in enumerate(conditions):
        entry: dict[str, object] = {
            "condition": condition,
            "ratings": sum(1 for r in ratings if r.condition == condition),
        }
        for offset, field in enumerate(("naturalness", "intelligibility")):
            stat = lambda sample, field=field: mean_of(condition, field, sample)  # noqa: E731
            entry[field] = {
                "mean": _round(stat(raters)),
                "ci95": _round_pair(_bootstrap_ci(raters, stat, samples=samples, seed=seed + 10 * index + offset)),
            }
            if condition != baseline:
                diff = lambda sample, field=field: paired_difference(condition, field, sample)  # noqa: E731
                entry[field]["paired_difference_vs_baseline"] = {
                    "mean": _round(diff(raters)),
                    "ci95": _round_pair(_bootstrap_ci(raters, diff, samples=samples, seed=seed + 10 * index + offset + 5)),
                }
        share = lambda sample: preference_share(condition, sample)  # noqa: E731
        entry["preference_share"] = {
            "share": _round(share(raters)),
            "ci95": _round_pair(_bootstrap_ci(raters, share, samples=samples, seed=seed + 10 * index + 9)),
            "chance": _round(1 / len(conditions)),
        }
        report_conditions.append(entry)
    return {
        "raters": len(raters),
        "ratings": len(ratings),
        "baseline": baseline,
        "bootstrap": {"resampled_unit": "listener", "samples": samples, "seed": seed, "interval": "percentile 95%"},
        "conditions": report_conditions,
        "caveats": _caveats(len(raters)),
    }


def _caveats(raters: int) -> list[str]:
    notes = ["Scores are ordinal 1-5 ratings; means summarise them but are not interval measurements."]
    if raters < 2:
        notes.append("One listener: no confidence intervals. Collect ratings from more people before drawing conclusions.")
    elif raters < 12:
        notes.append(f"Only {raters} listeners: intervals are wide and the bootstrap is unstable below about 12.")
    notes.append("An interval for a paired difference that excludes 0 suggests a real difference for this corpus and these listeners only.")
    return notes


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _round_pair(pair: tuple[float, float] | None) -> list[float] | None:
    return None if pair is None else [round(pair[0], 3), round(pair[1], 3)]


def format_report(report: dict[str, object], warnings: Sequence[str]) -> str:
    def interval(value: object) -> str:
        return f"[{value[0]:.2f}, {value[1]:.2f}]" if value else "n/a"

    def percent_interval(value: object) -> str:
        return f"[{value[0]:.0%}, {value[1]:.0%}]" if value else "n/a"

    lines = [f"{report['raters']} listeners, {report['ratings']} ratings; baseline {report['baseline']}", ""]
    lines.append(f"{'condition':<24} {'naturalness':>22} {'intelligibility':>22} {'preferred':>20}")
    for entry in report["conditions"]:  # type: ignore[union-attr]
        cells = []
        for field in ("naturalness", "intelligibility"):
            cells.append(f"{entry[field]['mean']:.2f} {interval(entry[field]['ci95'])}")
        share = entry["preference_share"]
        preferred = "n/a" if share["share"] is None else f"{share['share']:.0%} {percent_interval(share['ci95'])}"
        lines.append(f"{entry['condition']:<24} {cells[0]:>22} {cells[1]:>22} {preferred:>20}")
    lines.append("")
    for entry in report["conditions"]:  # type: ignore[union-attr]
        for field in ("naturalness", "intelligibility"):
            paired = entry[field].get("paired_difference_vs_baseline")
            if paired and paired["mean"] is not None:
                lines.append(f"{entry['condition']} - baseline, {field}: {paired['mean']:+.2f} {interval(paired['ci95'])}")
    lines += ["", *(f"Note: {note}" for note in report["caveats"])]  # type: ignore[union-attr]
    lines += [f"Warning: {warning}" for warning in warnings]
    return "\n".join(lines)


def analyze_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="listening_eval.py analyze", description="Summarise completed blind rating sheets.")
    parser.add_argument("ratings", nargs="+", type=Path, help="One completed blind-ratings CSV per listener")
    parser.add_argument("--key", type=Path, required=True, help="facilitator-only/facilitator-key.csv")
    parser.add_argument("--baseline", default=BASELINE_CONDITION)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--json", type=Path, help="Also write the report as JSON")
    args = parser.parse_args(argv)
    try:
        ratings, warnings = load_ratings(args.key, args.ratings)
        report = analyze_ratings(ratings, baseline=args.baseline, samples=args.bootstrap_samples)
    except (OSError, ValueError, KeyError) as exc:
        print(f"listening_eval: {exc}", file=sys.stderr)
        return 2
    print(format_report(report, warnings))
    if args.json:
        args.json.write_text(json.dumps({**report, "warnings": list(warnings)}, indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["analyze"]:
        return analyze_main(argv[1:])
    parser = argparse.ArgumentParser(
        description="Generate blind, level-matched local comparison clips. Run 'analyze' to summarise ratings.",
    )
    parser.add_argument("--voice", default="en_US-john-medium")
    parser.add_argument("--models-dir", type=Path, default=Path("models/piper"))
    parser.add_argument("--output-dir", type=Path, default=Path("listening-evaluation"))
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--repeats", type=int, default=1, help="Independent audio takes per passage and variation")
    parser.add_argument("--keep-dates-raw", action="store_true", help="Do not expand ISO dates in spoken text")
    parser.add_argument("--keep-citations-raw", action="store_true", help="Do not expand bracketed numeric citations")
    parser.add_argument("--kokoro-dir", type=Path, help="Add a Kokoro arm using the model files in this directory")
    parser.add_argument("--kokoro-voice", default="af_sarah")
    args = parser.parse_args(argv)
    try:
        models_dir = args.models_dir.expanduser().resolve()
        conditions = piper_conditions(args.voice, models_dir)
        if args.kokoro_dir is not None:
            conditions.append(kokoro_condition(args.kokoro_dir.expanduser().resolve(), args.kokoro_voice))
        metadata = create_listening_pack(
            args.voice,
            models_dir,
            args.output_dir.expanduser().resolve(),
            seed=args.seed,
            repeats=args.repeats,
            expand_dates=not args.keep_dates_raw,
            expand_citations=not args.keep_citations_raw,
            conditions=conditions,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"listening_eval: {exc}", file=sys.stderr)
        return 2
    print(f"Created {metadata['rating_count']} blind clips in {args.output_dir.resolve() / 'participant-pack'}")
    print(f"Facilitator mapping and run metadata: {args.output_dir.resolve() / 'facilitator-only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
