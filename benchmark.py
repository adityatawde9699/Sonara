#!/usr/bin/env python3
"""Repeatable TTS benchmark protocol conforming to Sonara ROADMAP.md Section G."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from document import Document, DocumentBlock, SourceBox, SCHEMA_VERSION
from narration import build_narration_plan
from tts_engine import PiperEngine, SynthesisStream

try:
    import resource
except ImportError:  # resource is not available on Windows
    resource = None


# Evaluation corpus passages covering prose, technical phrases, numbers, and dialogue
BENCHMARK_PASSAGES = [
    (
        "Short phrase",
        "Welcome to Sonara, a local document reading system.",
    ),
    (
        "Technical prose",
        "The ONNX Runtime executes optimized CPU kernels with a real-time factor strictly below 1.0.",
    ),
    (
        "Numbers and units",
        "In section 4.2, the 512 MiB inactive cache budget was verified across 10 trials at 22,050 Hz.",
    ),
    (
        "Dialogue and quotes",
        '"Are the audio chunks ready?" she asked. "Yes," Bryce replied, "and the stream is settling."',
    ),
    (
        "Research report",
        "The report compares three cohorts over twelve weeks. The treatment group improved, while the control group remained stable.",
    ),
    (
        "Question and emphasis",
        "What changed after the second trial? The answer was unexpected! The effect appeared only in the final sample.",
    ),
    (
        "Citation and date",
        "The review was published on 2026-10-27 and cites [12, 14] for the primary result.",
    ),
    (
        "Abbreviations and units",
        "For example, the sample moved at 3.5 km/h and the sensor recorded 22,050 Hz.",
    ),
]


def get_peak_rss_mb() -> float:
    """Return peak process RSS in megabytes (Linux getrusage gives kilobytes)."""
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_maxrss / 1024.0


def make_benchmark_document(text: str) -> Document:
    box = SourceBox(page=1, page_width=612.0, page_height=792.0, x_min=54.0, y_min=54.0, x_max=558.0, y_max=738.0)
    block = DocumentBlock("b-bench-001", "paragraph", "benchmark", 0, text, box)
    return Document(
        schema_version=SCHEMA_VERSION,
        source_name="benchmark_corpus",
        source_sha256="0" * 64,
        extractor="benchmark",
        extractor_version="1.0",
        page_count=1,
        blocks=(block,),
        notes=(),
    )


def run_single_trial(
    engine: PiperEngine,
    text: str,
    output_dir: Path,
) -> dict[str, Any]:
    doc = make_benchmark_document(text)
    plan = build_narration_plan(doc)

    t_start = time.perf_counter()
    ttfa: float | None = None
    total_audio_seconds = 0.0
    chunk_count = 0

    with SynthesisStream(engine, plan, prefetch_chunks=2) as stream:
        for chunk in stream:
            chunk_time = time.perf_counter()
            if ttfa is None:
                ttfa = chunk_time - t_start
            total_audio_seconds += chunk.duration_seconds
            chunk_count += 1

    t_end = time.perf_counter()
    wall_time = t_end - t_start
    rtf = wall_time / total_audio_seconds if total_audio_seconds > 0 else 0.0

    return {
        "text_length": len(text),
        "wall_time_seconds": round(wall_time, 4),
        "ttfa_seconds": round(ttfa or 0.0, 4),
        "audio_seconds": round(total_audio_seconds, 4),
        "rtf": round(rtf, 4),
        "chunks": chunk_count,
    }


def benchmark_voice(
    voice: str,
    models_dir: Path,
    trials_per_passage: int = 3,
) -> dict[str, Any]:
    model_path = models_dir / f"{voice}.onnx"
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    # Measure cold startup
    rss_before = get_peak_rss_mb()
    t_load_start = time.perf_counter()
    engine = PiperEngine(model_path, config_path)
    cold_load_seconds = time.perf_counter() - t_load_start
    rss_after_load = get_peak_rss_mb()

    with tempfile.TemporaryDirectory(prefix="sonara-bench-") as temp_dir:
        temp_path = Path(temp_dir)
        passage_results: list[dict[str, Any]] = []

        for name, text in BENCHMARK_PASSAGES:
            trial_metrics: list[dict[str, Any]] = []
            for _ in range(trials_per_passage):
                res = run_single_trial(engine, text, temp_path)
                trial_metrics.append(res)

            avg_rtf = statistics.mean(t["rtf"] for t in trial_metrics)
            avg_ttfa = statistics.mean(t["ttfa_seconds"] for t in trial_metrics)
            total_audio = statistics.mean(t["audio_seconds"] for t in trial_metrics)

            passage_results.append({
                "passage_name": name,
                "text": text,
                "avg_rtf": round(avg_rtf, 4),
                "avg_ttfa_seconds": round(avg_ttfa, 4),
                "avg_audio_seconds": round(total_audio, 4),
                "trials": trial_metrics,
            })

    engine.close()
    rss_final = get_peak_rss_mb()

    overall_rtfs = [p["avg_rtf"] for p in passage_results]
    overall_ttfas = [p["avg_ttfa_seconds"] for p in passage_results]

    return {
        "voice": voice,
        "cold_model_load_seconds": round(cold_load_seconds, 4),
        "peak_rss_mb_start": round(rss_before, 2),
        "peak_rss_mb_loaded": round(rss_after_load, 2),
        "peak_rss_mb_final": round(rss_final, 2),
        "mean_rtf": round(statistics.mean(overall_rtfs), 4),
        "mean_ttfa_seconds": round(statistics.mean(overall_ttfas), 4),
        "passages": passage_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonara TTS Performance & RTF Benchmark")
    parser.add_argument("--voice", default="en_US-john-medium", help="Piper voice name to benchmark")
    parser.add_argument("--all", action="store_true", help="Benchmark all installed voices in models-dir")
    parser.add_argument("--models-dir", type=Path, default=Path("models/piper"), help="Directory containing Piper models")
    parser.add_argument("--trials", type=int, default=2, help="Trials per passage")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format")
    args = parser.parse_args()

    models_dir = args.models_dir.resolve()
    print(f"Running Sonara benchmark on {platform.system()} {platform.machine()} (Python {sys.version.split()[0]})...", file=sys.stderr)

    voices_to_test = []
    if args.all:
        for model_file in sorted(models_dir.glob("*.onnx")):
            voices_to_test.append(model_file.stem)
    else:
        voices_to_test.append(args.voice)

    if not voices_to_test:
        print("No voices found to benchmark.", file=sys.stderr)
        return 1

    reports = []
    for voice_name in voices_to_test:
        print(f"\nBenchmarking voice: {voice_name} ...", file=sys.stderr)
        rep = benchmark_voice(voice_name, models_dir, trials_per_passage=args.trials)
        reports.append(rep)

    system_info = {
        "os": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "python_version": sys.version.split()[0],
    }

    if args.json:
        out = {"system": system_info, "reports": reports if args.all else reports[0]}
        print(json.dumps(out, indent=2))
    else:
        if args.all:
            print("\n" + "=" * 76)
            print("SONARA MULTI-VOICE COMPARATIVE BENCHMARK REPORT")
            print("=" * 76)
            print(f"{'Voice':<24} | {'Cold Load':<10} | {'Mean TTFA':<10} | {'Mean RTF':<10} | {'Peak RAM':<10}")
            print("-" * 76)
            for r in reports:
                print(f"{r['voice']:<24} | {r['cold_model_load_seconds']:>8.3f} s | {r['mean_ttfa_seconds']:>8.3f} s | {r['mean_rtf']:>8.3f}   | {r['peak_rss_mb_loaded']:>7.1f} MB")
            print("=" * 76)
        else:
            report = reports[0]
            print("\n" + "=" * 65)
            print(f"SONARA PERFORMANCE BENCHMARK REPORT: {report['voice']}")
            print("=" * 65)
            print(f"• Cold Model Load Time : {report['cold_model_load_seconds']} s")
            print(f"• Mean Time to First Audio (TTFA): {report['mean_ttfa_seconds']} s")
            print(f"• Mean Real-Time Factor (RTF)    : {report['mean_rtf']} (RTF < 1.0 is required for real-time)")
            print(f"• Peak Memory RSS (Post-load)    : {report['peak_rss_mb_loaded']} MB")
            print(f"• Peak Memory RSS (Final)        : {report['peak_rss_mb_final']} MB")
            print("\nPassage Breakdown:")
            print(f"{'Passage':<22} | {'Audio Duration':<14} | {'TTFA':<10} | {'RTF':<8}")
            print("-" * 65)
            for p in report["passages"]:
                print(f"{p['passage_name']:<22} | {p['avg_audio_seconds']:>12.2f} s | {p['avg_ttfa_seconds']:>8.3f} s | {p['avg_rtf']:>7.3f}")
            print("=" * 65)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
