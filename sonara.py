#!/usr/bin/env python3
"""Local PDF-to-speech prototype using Poppler and Piper subprocesses."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

from document import (
    Document,
    extract_docx_document,
    extract_epub_document,
    extract_txt_document,
    parse_bbox_layout,
)
from narration import NarrationError, build_narration_plan
from tts_engine import KokoroEngine, PiperEngine, SynthesisStream, TtsError
from resource_policy import get_resource_profile


class SonaraError(RuntimeError):
    """A user-actionable extraction or synthesis error."""


MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_BBOX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_TOOL_STDERR_BYTES = 1024 * 1024
PDF_EXTRACTION_TIMEOUT_SECONDS = 60


def extract_pdf(pdf: Path, pdftotext: str = "pdftotext") -> str:
    """Compatibility helper returning source text in structured block order."""
    return extract_document(pdf, pdftotext).text


def extract_document(document_path: Path, pdftotext: str = "pdftotext") -> Document:
    """Extract a supported document (.pdf, .txt/.text, .md, .docx, .epub) into a schema-v1 Document."""
    ext = document_path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf_document(document_path, pdftotext)
    elif ext in (".txt", ".text", ".md"):
        try:
            return extract_txt_document(document_path)
        except ValueError as exc:
            raise SonaraError(str(exc)) from exc
    elif ext == ".docx":
        try:
            return extract_docx_document(document_path)
        except ValueError as exc:
            raise SonaraError(str(exc)) from exc
    elif ext == ".epub":
        try:
            return extract_epub_document(document_path)
        except ValueError as exc:
            raise SonaraError(str(exc)) from exc
    else:
        raise SonaraError(
            f"Unsupported document format: '{ext}'. Supported formats are: .pdf, .txt, .text, .md, .docx, .epub"
        )


def extract_pdf_document(pdf: Path, pdftotext: str = "pdftotext") -> Document:
    if not pdf.is_file():
        raise SonaraError(f"PDF does not exist or is not a file: {pdf}")
    try:
        pdf_size = pdf.stat().st_size
    except OSError as exc:
        raise SonaraError(f"Could not inspect PDF: {exc}") from exc
    if pdf_size > MAX_PDF_BYTES:
        raise SonaraError(f"PDF is larger than the {MAX_PDF_BYTES // (1024 * 1024)} MiB extraction limit.")
    try:
        source_sha256 = _file_sha256(pdf)
    except OSError as exc:
        raise SonaraError(f"Could not read PDF for integrity metadata: {exc}") from exc
    executable = shutil.which(pdftotext)
    if executable is None:
        raise SonaraError(f"pdftotext was not found: {pdftotext}")
    version = _pdftotext_version(executable)
    command = [executable, "-bbox-layout", "-enc", "UTF-8", str(pdf), "-"]
    stdout, stderr, returncode, failure = _run_bounded(command)
    if failure == "timeout":
        raise SonaraError(f"PDF extraction exceeded {PDF_EXTRACTION_TIMEOUT_SECONDS} seconds and was stopped.")
    if failure == "stdout_limit":
        raise SonaraError(f"PDF extraction output exceeded the {MAX_BBOX_OUTPUT_BYTES // (1024 * 1024)} MiB limit.")
    if failure == "stderr_limit":
        raise SonaraError("PDF extraction produced excessive diagnostic output and was stopped.")
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip() or f"exit status {returncode}"
        raise SonaraError(f"PDF extraction failed: {detail}")
    try:
        markup = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SonaraError("Poppler returned text that was not valid UTF-8 despite the UTF-8 output setting.") from exc
    try:
        document = parse_bbox_layout(
            markup,
            source_name=pdf.name,
            source_sha256=source_sha256,
            extractor_version=version,
        )
    except ValueError as exc:
        if "No selectable text was found" in str(exc):
            from ocr import is_tesseract_available, extract_scanned_pdf
            if is_tesseract_available():
                try:
                    return extract_scanned_pdf(pdf)
                except Exception as ocr_err:
                    raise SonaraError(f"No selectable text was found, and OCR failed: {ocr_err}") from ocr_err
            raise SonaraError(
                "No selectable text was found. This may be a scanned PDF; OCR is not implemented yet "
                "or Tesseract OCR is not installed. To enable reading for scanned documents, install 'tesseract-ocr' "
                "or provide a document with selectable text."
            )
        raise SonaraError(str(exc)) from exc
    return document


def _run_bounded(command: list[str]) -> tuple[bytes, bytes, int, str | None]:
    """Run Poppler while bounding captured output and wall-clock time."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise SonaraError(f"Could not start pdftotext: {exc}") from exc

    stdout = bytearray()
    stderr = bytearray()
    exceeded = {"stdout": threading.Event(), "stderr": threading.Event()}

    def drain(stream, destination: bytearray, limit: int, event: threading.Event) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit + 1 - len(destination)
            if remaining > 0:
                destination.extend(chunk[:remaining])
            if len(destination) > limit:
                event.set()
                return

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout, MAX_BBOX_OUTPUT_BYTES, exceeded["stdout"]), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr, MAX_TOOL_STDERR_BYTES, exceeded["stderr"]), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + PDF_EXTRACTION_TIMEOUT_SECONDS
    failure = None
    while process.poll() is None:
        if exceeded["stdout"].is_set():
            failure = "stdout_limit"
        elif exceeded["stderr"].is_set():
            failure = "stderr_limit"
        elif time.monotonic() >= deadline:
            failure = "timeout"
        if failure is not None:
            process.kill()
            break
        time.sleep(0.025)
    returncode = process.wait()
    for reader in readers:
        reader.join()
    process.stdout.close()
    process.stderr.close()
    if failure is None:
        if exceeded["stdout"].is_set():
            failure = "stdout_limit"
        elif exceeded["stderr"].is_set():
            failure = "stderr_limit"
    return bytes(stdout), bytes(stderr), returncode, failure


@lru_cache(maxsize=8)
def _pdftotext_version(executable: str) -> str:
    try:
        result = subprocess.run([executable, "-v"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = result.stdout + result.stderr
    match = re.search(r"pdftotext version\s+([^\s]+)", output, re.IGNORECASE)
    return match.group(1) if match else "unknown"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def player_html(title: str, manifest: dict[str, Any] | None = None) -> str:
    safe_title = html.escape(title)
    payload = manifest or {"schema_version": 1, "document_source_sha256": "", "chunks": []}
    manifest_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    manifest_json = manifest_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} — Sonara</title>
<style>
:root{{color-scheme:light dark;font:16px system-ui,sans-serif}}body{{max-width:48rem;margin:clamp(1rem,8vh,5rem) auto;padding:0 1rem;background:#10151b;color:#edf3f8}}
main{{background:#19222c;border:1px solid #344454;border-radius:1rem;padding:clamp(1rem,4vw,2rem);box-shadow:0 1rem 3rem #0005}}
h1{{font-size:1.5rem;margin-top:0}}button,input{{font:inherit}}button{{border:0;border-radius:.5rem;padding:.65rem 1rem;background:#75d5bd;color:#10211c;font-weight:650;cursor:pointer}}button:disabled{{opacity:.45;cursor:not-allowed}}
.controls{{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:.8rem 0}}.seek-row,.speed-row{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.75rem;margin:1.1rem 0}}input[type=range]{{width:100%;accent-color:#75d5bd}}#status{{min-height:1.5em;color:#b9cbd6}}#error-actions[hidden]{{display:none}}.hint{{font-size:.9rem;color:#aebdca}}audio{{display:none}}
</style></head><body><main><h1>{safe_title}</h1>
<p class="hint">Local, sentence-chunk playback. Progress is saved in this browser when storage is available.</p>
<audio id="audio" preload="metadata"></audio>
<div class="controls"><button id="play" type="button">Play</button><button id="pause" type="button" disabled>Pause</button><button id="retry" type="button" hidden>Retry chunk</button><button id="skip" type="button" hidden>Skip chunk</button></div>
<label class="seek-row" for="seek"><span>Position</span><input id="seek" type="range" min="0" max="1000" value="0" aria-label="Seek through document"><span id="time">0:00 / 0:00</span></label>
<label class="speed-row" for="speed"><span>Speed</span><input id="speed" type="range" min="0.7" max="1.5" step="0.1" value="1"><span id="speed-label">1.0×</span></label>
<p id="status" role="status" aria-live="polite">Ready to play.</p>
</main>
<script id="sonara-manifest" type="application/json">{manifest_json}</script>
<script>
const manifest=JSON.parse(document.querySelector('#sonara-manifest').textContent);
const chunks=Array.isArray(manifest.chunks)?manifest.chunks:[];
const audio=document.querySelector('#audio'), playButton=document.querySelector('#play'), pauseButton=document.querySelector('#pause');
const retryButton=document.querySelector('#retry'), skipButton=document.querySelector('#skip'), seek=document.querySelector('#seek');
const timeLabel=document.querySelector('#time'), speed=document.querySelector('#speed'), speedLabel=document.querySelector('#speed-label'), status=document.querySelector('#status');
const storageKey='sonara-progress-v1:'+String(manifest.document_source_sha256||'unknown')+':'+String(manifest.narration_ruleset_version||'legacy');
const durations=chunks.map(c=>Number.isFinite(c.duration_seconds)&&c.duration_seconds>0?c.duration_seconds:0);
const starts=[];let total=0;for(const duration of durations){{starts.push(total);total+=duration}}
let segment=0,pendingOffset=0,pendingAutoplay=false,expectedSrc='',playing=false,failed=false,failedResume=false,pauseTimer=null,pauseDeadline=0,pauseRemaining=0,inNarrationPause=false;
let storageAvailable=true,stored=null;
try{{stored=localStorage.getItem(storageKey)}}catch{{storageAvailable=false;status.textContent='This browser blocks saved progress for local files. Playback works, but progress will not be restored.'}}
let saved=null;if(stored){{try{{saved=JSON.parse(stored)}}catch{{status.textContent='Saved progress is invalid and will be replaced.'}}}}
if(saved&&Number.isFinite(saved.rate)&&saved.rate>=0.7&&saved.rate<=1.5)speed.value=String(saved.rate);
function clock(value){{value=Math.max(0,Math.floor(value||0));return Math.floor(value/60)+':'+String(value%60).padStart(2,'0')}}
function currentPosition(){{return (starts[segment]||0)+(audio.currentTime||0)}}
function renderTime(position=currentPosition()){{timeLabel.textContent=clock(position)+' / '+clock(total);seek.value=String(total?Math.round(Math.max(0,Math.min(1,position/total))*1000):0)}}
function setPlaying(value){{playing=value;playButton.disabled=value||!chunks.length;pauseButton.disabled=!value}}
function setSpeed(persist=true){{audio.playbackRate=Number(speed.value);speedLabel.textContent=audio.playbackRate.toFixed(1)+'×';if(persist)saveProgress()}}
function saveProgress(index=segment,offset=audio.currentTime||0){{
 if(!storageAvailable||!chunks.length)return;
 try{{localStorage.setItem(storageKey,JSON.stringify({{version:1,document:manifest.document_source_sha256,segment:index,offset,rate:Number(speed.value)}}))}}
 catch{{storageAvailable=false;status.textContent='Progress could not be saved by this browser.'}}
}}
function clearPause(){{if(pauseTimer!==null)clearTimeout(pauseTimer);pauseTimer=null;inNarrationPause=false;pauseRemaining=0}}
function showLoadError(){{failedResume=playing||pendingAutoplay;pendingAutoplay=false;failed=true;setPlaying(false);status.textContent='This audio chunk could not be loaded. Check that its WAV file is beside the player.';retryButton.hidden=false;skipButton.hidden=segment>=chunks.length-1}}
function loadChunk(index,offset=0,autoplay=false){{
 clearPause();if(index<0||index>=chunks.length){{setPlaying(false);return}}
 segment=index;pendingOffset=Math.max(0,offset||0);pendingAutoplay=autoplay;failed=false;failedResume=false;retryButton.hidden=true;skipButton.hidden=true;setPlaying(false);
 const entry=chunks[index];if(!entry.audio_file){{showLoadError();return}}
 audio.pause();expectedSrc=new URL(entry.audio_file,location.href).href;audio.src=expectedSrc;audio.load();status.textContent='Loading passage '+(index+1)+' of '+chunks.length+'…';renderTime(starts[index]+pendingOffset);
}}
async function startPlayback(){{
 if(!chunks.length){{status.textContent='No audio chunks are available.';return}}
 if(failed){{status.textContent='Retry this chunk or skip it to continue.';return}}
 if(inNarrationPause){{const wait=pauseRemaining;pauseDeadline=Date.now()+wait;pauseTimer=setTimeout(()=>{{pauseTimer=null;inNarrationPause=false;loadChunk(segment+1,0,true)}},wait);setPlaying(true);status.textContent='Resuming the narration pause…';return}}
 if(audio.ended){{loadChunk(0,0,true);return}}
 try{{await audio.play();setPlaying(true);status.textContent='Playing passage '+(segment+1)+' of '+chunks.length+'.'}}
 catch{{setPlaying(false);status.textContent='Playback was blocked by the browser. Press Play to start audio.'}}
}}
function pausePlayback(){{
 if(pauseTimer!==null){{clearTimeout(pauseTimer);pauseTimer=null;pauseRemaining=Math.max(0,pauseDeadline-Date.now());inNarrationPause=true}}
 else audio.pause();setPlaying(false);saveProgress();status.textContent='Paused.';
}}
function seekTo(position,resume=playing){{
 position=Math.max(0,Math.min(total,position));let index=chunks.length-1,offset=durations[index]||0;
 for(let i=0;i<chunks.length;i++){{if(position<starts[i]+durations[i]||i===chunks.length-1){{index=i;offset=Math.max(0,position-starts[i]);break}}}}
 loadChunk(index,offset,resume);saveProgress(index,offset);
}}
playButton.addEventListener('click',startPlayback);pauseButton.addEventListener('click',pausePlayback);
retryButton.addEventListener('click',()=>loadChunk(segment,pendingOffset,failedResume));
skipButton.addEventListener('click',()=>loadChunk(segment+1,0,failedResume));
speed.addEventListener('input',setSpeed);
seek.addEventListener('input',()=>renderTime((Number(seek.value)/1000)*total));
seek.addEventListener('change',()=>seekTo((Number(seek.value)/1000)*total,playing));
audio.addEventListener('loadedmetadata',async()=>{{
 if(audio.currentSrc&&audio.currentSrc!==expectedSrc)return;
 const upper=Math.max(0,audio.duration-0.02);audio.currentTime=Math.min(pendingOffset,upper);setSpeed();renderTime();
 status.textContent='Ready — passage '+(segment+1)+' of '+chunks.length+'.';
 if(pendingAutoplay){{pendingAutoplay=false;await startPlayback()}}
}});
audio.addEventListener('timeupdate',()=>{{renderTime();saveProgress()}});
audio.addEventListener('error',()=>{{if(!audio.currentSrc||audio.currentSrc===expectedSrc)showLoadError()}});
audio.addEventListener('ended',()=>{{
 if(audio.currentSrc&&audio.currentSrc!==expectedSrc)return;
 saveProgress(segment,audio.duration);setPlaying(false);
 if(segment>=chunks.length-1){{status.textContent='Reading complete.';return}}
 const delay=Math.max(0,Number(chunks[segment].pause_after_ms)||0);pauseRemaining=delay;inNarrationPause=delay>0;
 if(delay){{pauseDeadline=Date.now()+delay;status.textContent='Pause between passages…';pauseTimer=setTimeout(()=>{{pauseTimer=null;inNarrationPause=false;loadChunk(segment+1,0,true)}},delay)}}
 else loadChunk(segment+1,0,true);
}});
window.addEventListener('beforeunload',()=>{{saveProgress();audio.pause()}});
if(!chunks.length){{playButton.disabled=true;pauseButton.disabled=true;seek.disabled=true;status.textContent='No audio chunks were written for this document.'}}
else{{
 let restoreIndex=0,restoreOffset=0;
 if(saved&&saved.version===1&&saved.document===manifest.document_source_sha256&&Number.isInteger(saved.segment)&&saved.segment>=0&&saved.segment<chunks.length&&Number.isFinite(saved.offset)&&saved.offset>=0){{restoreIndex=saved.segment;restoreOffset=Math.min(saved.offset,durations[restoreIndex])}}
 segment=restoreIndex;pendingOffset=restoreOffset;loadChunk(segment,restoreOffset,false);setSpeed(false);renderTime(starts[segment]+restoreOffset);
}}
</script></body></html>'''


def synthesize(text: str, voice: str, data_dir: Path, output: Path, piper: str) -> None:
    if len(text.encode("utf-8")) > 100_000:
        raise SonaraError(
            "The one-shot Piper executable path supports up to 100 KB of text; "
            "use the default installed Python engine for chunked synthesis."
        )
    if piper == "piper":
        try:
            module_available = importlib.util.find_spec("piper") is not None
        except ModuleNotFoundError:
            module_available = False
        if module_available:
            command_prefix = [sys.executable, "-m", "piper"]
        else:
            executable = shutil.which(piper)
            if executable is None:
                raise SonaraError(f"Piper was not found: {piper}. Install piper-tts in an isolated environment or provide --piper.")
            command_prefix = [executable]
    else:
        executable = shutil.which(piper)
        if executable is None:
            raise SonaraError(f"Piper executable was not found: {piper}")
        command_prefix = [executable]
    if not data_dir.is_dir():
        raise SonaraError(f"Piper data directory does not exist: {data_dir}")
    try:
        with tempfile.TemporaryDirectory(prefix="sonara-piper-input-") as temp_dir:
            input_path = Path(temp_dir) / "document.txt"
            input_path.write_text(text, encoding="utf-8")
            command = command_prefix + [
                "-m", voice,
                "--data-dir", str(data_dir),
                "--output_file", str(output),
                "--input-file", str(input_path),
            ]
            result = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise SonaraError(f"Could not run Piper speech synthesis: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise SonaraError(f"Speech synthesis failed: {detail}")
    if not output.is_file() or output.stat().st_size == 0:
        raise SonaraError("Piper reported success but did not create a non-empty WAV file.")


def read_document(args: argparse.Namespace) -> Path:
    doc_path = (getattr(args, "document", None) or getattr(args, "pdf", None))
    if doc_path is None:
        raise SonaraError("No input document was specified.")
    doc_path = doc_path.expanduser().resolve()
    document = extract_document(doc_path, getattr(args, "pdftotext", "pdftotext"))
    text = document.text
    for note in document.notes:
        page = f" (page {note.page})" if note.page is not None else ""
        print(f"sonara: review: {note.message}{page}", file=sys.stderr)
    out = args.output_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(out / "extracted_document.json", document.to_dict())
    _write_text_atomic(out / "document_text.txt", text)
    speech = out / "speech.wav"
    old_manifest = _load_audio_manifest(out / "audio_chunks.json")
    data_dir = args.data_dir.expanduser().resolve()
    try:
        plan = build_narration_plan(
            document,
            language="en_US" if getattr(args, "engine", "piper") == "kokoro" else _voice_language(args.voice),
            expand_dates=getattr(args, "expand_dates", False),
            expand_citations=getattr(args, "expand_citations", False),
        )
    except NarrationError as exc:
        raise SonaraError(f"Could not plan document narration: {exc}") from exc
    if getattr(args, "engine", "piper") == "kokoro":
        manifest = _synthesize_plan(
            plan, args.voice, data_dir, speech,
            variation=getattr(args, "variation", "voice_default"),
            engine_name="kokoro",
            kokoro_dir=getattr(args, "kokoro_dir", Path("models/kokoro")),
            resource_profile=getattr(args, "resource_profile", "standard"),
        )
    elif _piper_python_api_available(args.piper):
        manifest = _synthesize_plan(
            plan, args.voice, data_dir, speech,
            variation=getattr(args, "variation", "voice_default"),
            resource_profile=getattr(args, "resource_profile", "standard"),
        )
    else:
        # Keep explicit executable overrides and the PATH fallback working.
        synthesize(" ".join(unit.spoken_text for unit in plan.units), args.voice, data_dir, speech, args.piper)
        manifest = _legacy_audio_manifest(document, speech, args.voice)
        _write_json_atomic(out / "audio_chunks.json", manifest)
    _write_text_atomic(out / "index.html", player_html(doc_path.name, manifest))
    _cleanup_old_chunks(out, old_manifest, manifest)
    return out / "index.html"


def _piper_python_api_available(piper: str) -> bool:
    if piper != "piper":
        return False
    try:
        return importlib.util.find_spec("piper") is not None
    except ModuleNotFoundError:
        return False


def _voice_language(voice: str) -> str:
    """Read the language prefix from installed Piper voice IDs such as en_US-name."""
    candidate = voice.split("-", 1)[0]
    return candidate if re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", candidate) else "und"


def preview_document(args: argparse.Namespace) -> dict[str, Any]:
    """Return a bounded preview of planned spoken text without generating audio."""
    document = extract_document(args.document.expanduser().resolve(), getattr(args, "pdftotext", "pdftotext"))
    plan = build_narration_plan(
        document,
        language=_voice_language(args.voice),
        expand_dates=getattr(args, "expand_dates", False),
        expand_citations=getattr(args, "expand_citations", False),
    )
    units = []
    for unit in plan.units[:12]:
        changes = [{
            "overrideId": change.override_id,
            "sourceTerm": change.source_term,
            "replacement": change.replacement,
            "matchedSourceText": change.matched_source_text,
            "sourceStart": change.source_start,
            "sourceEnd": change.source_end,
        } for change in unit.applied_overrides]
        units.append({
            "order": unit.order,
            "sourceText": _preview_text(unit.source_text),
            "spokenText": _preview_text(unit.spoken_text),
            "changes": changes,
        })
    return {
        "sourceName": document.source_name,
        "language": _voice_language(args.voice),
        "totalUnits": len(plan.units),
        "units": units,
    }


def _preview_text(value: str, limit: int = 700) -> str:
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _synthesize_plan(
    plan,
    voice: str,
    data_dir: Path,
    output: Path,
    *,
    variation: str = "voice_default",
    engine_name: str = "piper",
    kokoro_dir: Path = Path("models/kokoro"),
    resource_profile: str = "standard",
) -> dict[str, Any]:
    """Generate mapped unit WAVs with one worker and return a playback manifest."""
    try:
        policy = get_resource_profile(resource_profile)
        if engine_name == "kokoro":
            engine = KokoroEngine(kokoro_dir, voice=voice)
        else:
            model_path = data_dir / f"{voice}.onnx"
            config_path = model_path.with_suffix(model_path.suffix + ".json")
            engine = PiperEngine(model_path, config_path, variation=variation)
    except TtsError as exc:
        raise SonaraError(str(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=".sonara-speech-", suffix=".wav", dir=output.parent, delete=False
    )
    temporary_output = Path(temp_handle.name)
    temp_handle.close()
    manifest_chunks: list[dict[str, Any]] = []
    chunk_root = output.parent / "chunks"
    run_chunk_dir = chunk_root / plan.document_source_sha256 / uuid.uuid4().hex
    try:
        run_chunk_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        temporary_output.unlink(missing_ok=True)
        engine.close()
        raise SonaraError(f"Could not prepare the document audio directory: {exc}") from exc
    manifest_committed = False
    try:
        with wave.open(str(temporary_output), "wb") as combined:
            combined.setnchannels(engine.capabilities.audio_format.channels)
            combined.setsampwidth(engine.capabilities.audio_format.sample_width_bytes)
            combined.setframerate(engine.capabilities.audio_format.sample_rate)
            chunk_count = 0
            with SynthesisStream(
                engine,
                plan,
                prefetch_chunks=policy.tts_prefetch_chunks,
                cache_dir=output.parent / ".sonara-audio-cache",
                cache_max_bytes=policy.audio_cache_bytes,
            ) as chunks:
                for chunk in chunks:
                    chunk_name = f"chunk-{chunk.sequence:06d}.wav"
                    chunk_path = run_chunk_dir / chunk_name
                    _copy_file_atomic(chunk.wav_path, chunk_path)
                    audio_file = chunk_path.relative_to(output.parent).as_posix()
                    with wave.open(str(chunk.wav_path), "rb") as source:
                        if (
                            source.getframerate() != combined.getframerate()
                            or source.getnchannels() != combined.getnchannels()
                            or source.getsampwidth() != combined.getsampwidth()
                        ):
                            raise SonaraError("Piper returned incompatible audio chunk formats.")
                        frames_left = source.getnframes()
                        while frames_left:
                            frames = source.readframes(min(frames_left, 65_536))
                            if not frames:
                                raise SonaraError("A synthesized WAV chunk ended before its declared frame count.")
                            combined.writeframes(frames)
                            frames_left -= len(frames) // (
                                source.getnchannels() * source.getsampwidth()
                            )
                    manifest_chunks.append({
                        "sequence": chunk.sequence,
                        "unit_id": chunk.unit_id,
                        "source_block_id": chunk.source_block_id,
                        "source_start": chunk.source_start,
                        "source_end": chunk.source_end,
                        "content_type": plan.units[chunk.sequence].content_type,
                        "pause_after_ms": plan.units[chunk.sequence].pause_after_ms,
                        "duration_seconds": chunk.duration_seconds,
                        "audio_file": audio_file,
                    })
                    chunk_count += 1
                    progressive_manifest = {
                        "schema_version": 1,
                        "document_source_sha256": plan.document_source_sha256,
                        "narration_ruleset_version": plan.ruleset_version,
                        "engine": engine.capabilities.engine,
                        "engine_version": engine.capabilities.engine_version,
                        "voice": engine.capabilities.voice,
                        "language": engine.capabilities.language,
                        "audio_format": {
                            "sample_rate": engine.capabilities.audio_format.sample_rate,
                            "channels": engine.capabilities.audio_format.channels,
                            "sample_width_bytes": engine.capabilities.audio_format.sample_width_bytes,
                        },
                        "total_units": len(plan.units),
                        "completed_units": chunk_count,
                        "chunks": list(manifest_chunks),
                    }
                    _write_json_atomic(output.parent / "audio_chunks.json", progressive_manifest)
            if chunk_count == 0:
                raise SonaraError("Narration plan contains no speech units.")
        os.replace(temporary_output, output)
        manifest = {
            "schema_version": 1,
            "document_source_sha256": plan.document_source_sha256,
            "narration_ruleset_version": plan.ruleset_version,
            "engine": engine.capabilities.engine,
            "engine_version": engine.capabilities.engine_version,
            "voice": engine.capabilities.voice,
            "language": engine.capabilities.language,
            "audio_format": {
                "sample_rate": engine.capabilities.audio_format.sample_rate,
                "channels": engine.capabilities.audio_format.channels,
                "sample_width_bytes": engine.capabilities.audio_format.sample_width_bytes,
            },
            "chunks": manifest_chunks,
        }
        _write_json_atomic(output.with_name("audio_chunks.json"), manifest)
        manifest_committed = True
        return manifest
    except TtsError as exc:
        temporary_output.unlink(missing_ok=True)
        raise SonaraError(str(exc)) from exc
    except (OSError, wave.Error) as exc:
        temporary_output.unlink(missing_ok=True)
        raise SonaraError(f"Could not assemble synthesized audio: {exc}") from exc
    except BaseException:
        temporary_output.unlink(missing_ok=True)
        raise
    finally:
        engine.close()
        if not manifest_committed:
            shutil.rmtree(run_chunk_dir, ignore_errors=True)


def _legacy_audio_manifest(document: Document, speech: Path, voice: str) -> dict[str, Any]:
    try:
        with wave.open(str(speech), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            audio_format = {
                "sample_rate": audio.getframerate(),
                "channels": audio.getnchannels(),
                "sample_width_bytes": audio.getsampwidth(),
            }
    except (OSError, EOFError, wave.Error, ZeroDivisionError) as exc:
        raise SonaraError(f"Could not inspect the one-shot Piper WAV: {exc}") from exc
    return {
        "schema_version": 1,
        "document_source_sha256": document.source_sha256,
        "narration_ruleset_version": "legacy-whole-document",
        "engine": "Piper CLI override",
        "voice": voice,
        "audio_format": audio_format,
        "chunks": [{
            "sequence": 0,
            "unit_id": "legacy-whole-document",
            "source_block_id": None,
            "source_start": 0,
            "source_end": len(document.text),
            "pause_after_ms": 0,
            "duration_seconds": duration,
            "audio_file": "speech.wav",
        }],
    }


def _load_audio_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("chunks"), list) else None


def _cleanup_old_chunks(
    output_dir: Path,
    old_manifest: dict[str, Any] | None,
    new_manifest: dict[str, Any],
) -> None:
    """Delete only old WAVs explicitly named by the previous Sonara manifest."""
    if old_manifest is None:
        return
    chunk_root = (output_dir / "chunks").resolve()
    current_files = {
        item.get("audio_file")
        for item in new_manifest.get("chunks", [])
        if isinstance(item, dict) and isinstance(item.get("audio_file"), str)
    }
    for item in old_manifest.get("chunks", []):
        if not isinstance(item, dict):
            continue
        audio_file = item.get("audio_file")
        if not isinstance(audio_file, str) or audio_file in current_files:
            continue
        candidate = (output_dir / audio_file).resolve()
        if candidate == chunk_root or not candidate.is_relative_to(chunk_root):
            continue
        if candidate.is_file():
            candidate.unlink()
        parent = candidate.parent
        while parent != chunk_root and parent.is_relative_to(chunk_root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sonara", description="Read a document (.pdf, .txt, .text, .md, .docx, .epub) aloud with local Piper TTS.")
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="extract a document (.pdf, .txt, .text, .md, .docx, .epub), synthesize audio, and create a resumable browser player")
    read.add_argument("document", type=Path, metavar="DOCUMENT", help="Path to document (.pdf, .txt, .text, .md, .docx, .epub)")
    read.add_argument("--voice", required=True, help="installed Piper voice model name or Kokoro voice id")
    read.add_argument("--engine", choices=("piper", "kokoro"), default="piper", help="local speech engine")
    read.add_argument("--resource-profile", choices=("low_resource", "standard", "high_performance"), default="standard", help="resource policy; does not change the selected model or voice")
    read.add_argument("--kokoro-dir", type=Path, default=Path("models/kokoro"), help="directory containing Kokoro ONNX and voice files")
    read.add_argument(
        "--variation",
        choices=("voice_default", "less", "more"),
        default="voice_default",
        help="Piper variation profile; voice_default preserves the model's configured values",
    )
    read.add_argument("--data-dir", type=Path, required=True, help="directory containing the reviewed Piper voice files")
    read.add_argument("--output-dir", type=Path, default=Path("sonara-reading"))
    read.add_argument(
        "--piper",
        default="piper",
        help="Piper runner: use the persistent active-Python worker when piper-tts is installed; otherwise use piper on PATH. Set this to override the executable.",
    )
    read.add_argument("--pdftotext", default="pdftotext", help="Poppler pdftotext executable")
    read.add_argument("--expand-dates", action="store_true", help="Speak unambiguous ISO dates as words")
    read.add_argument("--expand-citations", action="store_true", help="Speak numeric bracket citations as references")
    read.add_argument("--preview", action="store_true", help="Print the spoken-text preview as JSON without synthesizing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.preview:
            if not args.document.is_file():
                raise SonaraError(f"Document does not exist or is not a file: {args.document}")
            print(json.dumps(preview_document(args), ensure_ascii=False))
            return 0
        player = read_document(args)
    except (SonaraError, OSError) as exc:
        print(f"sonara: {exc}", file=sys.stderr)
        return 2
    print(f"Created local reader: {player}")
    print("Open it in a browser to play audio and save reading progress.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
