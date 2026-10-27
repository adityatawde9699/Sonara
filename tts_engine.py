"""Replaceable local TTS contract and bounded narration-unit synthesis stream."""

from __future__ import annotations

import hashlib
import json
import importlib.metadata
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from narration import NarrationPlan, NarrationUnit


class TtsError(RuntimeError):
    """A recoverable engine, model, cache, or synthesis failure."""


class SynthesisCancelled(TtsError):
    """The consumer cancelled pending synthesis work."""


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    sample_width_bytes: int


@dataclass(frozen=True)
class EngineCapabilities:
    engine: str
    engine_version: str
    voice: str
    language: str
    model_available: bool
    audio_format: AudioFormat
    minimum_speed: float
    maximum_speed: float
    supported_controls: tuple[str, ...]
    unsupported_controls: tuple[str, ...]
    supports_inflight_cancellation: bool
    device: str


@dataclass(frozen=True)
class SynthesisSettings:
    """Settings supported by the common adapter contract."""

    speed: float = 1.0

    def __post_init__(self) -> None:
        if not 0.5 <= self.speed <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")


@dataclass(frozen=True)
class SynthesizedChunk:
    """A WAV chunk tied to its original narration passage.

    The path is owned by its SynthesisStream unless it came from the optional
    persistent cache. Consumers must finish reading before closing the stream.
    """

    sequence: int
    unit_id: str
    source_block_id: str
    source_start: int
    source_end: int
    source_text: str
    spoken_text: str
    wav_path: Path
    audio_format: AudioFormat
    duration_seconds: float
    cached: bool = False


class SpeechEngine(Protocol):
    """Engine contract: synthesize one narration unit to a WAV file."""

    @property
    def capabilities(self) -> EngineCapabilities: ...

    @property
    def cache_identity(self) -> str: ...

    def synthesize_to_wav(
        self,
        text: str,
        speed: float,
        output_path: Path,
        cancel_event: threading.Event,
        timeout_seconds: float,
    ) -> AudioFormat: ...

    def cancel_active(self) -> None: ...

    def begin_stream(self) -> object: ...

    def end_stream(self, token: object) -> None: ...


_END = object()


class SynthesisStream:
    """Bounded background producer; iteration yields audio before the plan ends."""

    def __init__(
        self,
        engine: SpeechEngine,
        plan: NarrationPlan,
        *,
        settings: SynthesisSettings | None = None,
        prefetch_chunks: int = 2,
        cache_dir: Path | None = None,
        cache_max_bytes: int = 512 * 1024 * 1024,
        synthesis_timeout_seconds: float = 180.0,
    ) -> None:
        if prefetch_chunks < 1:
            raise ValueError("prefetch_chunks must be at least one")
        if synthesis_timeout_seconds <= 0:
            raise ValueError("synthesis timeout must be positive")
        if cache_max_bytes <= 0:
            raise ValueError("cache size limit must be positive")
        self.engine = engine
        self.plan = plan
        self.settings = settings or SynthesisSettings()
        self.cache_dir = cache_dir
        self.cache_max_bytes = cache_max_bytes
        self.synthesis_timeout_seconds = synthesis_timeout_seconds
        self._queue: queue.Queue[object] = queue.Queue(maxsize=prefetch_chunks)
        self._cancel = threading.Event()
        lease_token = self.engine.begin_stream()
        try:
            self._temporary = tempfile.TemporaryDirectory(prefix="sonara-audio-chunks-")
        except BaseException:
            self.engine.end_stream(lease_token)
            raise
        self._lease_token = lease_token
        try:
            if self.cache_dir is not None:
                protected = {self._cache_path(unit) for unit in self.plan.units}
                prune_audio_cache(self.cache_dir, self.cache_max_bytes, protected=protected)
        except BaseException:
            self._temporary.cleanup()
            self.engine.end_stream(self._lease_token)
            raise
        self._thread = threading.Thread(target=self._produce, name="sonara-tts-producer", daemon=True)
        self._closed = False
        self._finished = False
        try:
            self._thread.start()
        except BaseException:
            self._temporary.cleanup()
            self.engine.end_stream(self._lease_token)
            raise

    def __iter__(self) -> SynthesisStream:
        return self

    def __next__(self) -> SynthesizedChunk:
        if self._closed:
            raise StopIteration
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if not self._thread.is_alive():
                    self.close()
                    raise StopIteration
                continue
            if item is _END:
                self._finished = True
                self.close()
                raise StopIteration
            if isinstance(item, BaseException):
                self.close(cancel=False)
                raise item
            return item  # type: ignore[return-value]

    def cancel(self) -> None:
        """Stop the worker process, interrupting active Piper inference."""
        if self._closed:
            return
        self._cancel.set()
        self.engine.cancel_active()
        self.close(cancel=False)

    def close(self, *, cancel: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        if cancel and not self._finished:
            self._cancel.set()
            self.engine.cancel_active()
        if self._thread is not threading.current_thread():
            self._thread.join()
        self._temporary.cleanup()
        self.engine.end_stream(self._lease_token)

    def __enter__(self) -> SynthesisStream:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close(cancel=not self._finished)

    def _produce(self) -> None:
        try:
            for sequence, unit in enumerate(self.plan.units):
                if self._cancel.is_set():
                    raise SynthesisCancelled("Synthesis was cancelled.")
                wav_path, cached = self._cache_lookup(unit, sequence)
                if wav_path is None:
                    wav_path = Path(self._temporary.name) / f"chunk-{sequence:06d}.wav"
                    started = time.monotonic()
                    generated_format = self.engine.synthesize_to_wav(
                        unit.spoken_text,
                        self.settings.speed,
                        wav_path,
                        self._cancel,
                        self.synthesis_timeout_seconds,
                    )
                    if generated_format != self.engine.capabilities.audio_format:
                        wav_path.unlink(missing_ok=True)
                        raise TtsError("Speech engine returned an unexpected audio format.")
                    if self._cancel.is_set():
                        raise SynthesisCancelled("Synthesis was cancelled.")
                    if time.monotonic() - started > self.synthesis_timeout_seconds:
                        raise TtsError(
                            f"Synthesis of narration unit {unit.id} exceeded "
                            f"{self.synthesis_timeout_seconds:g} seconds."
                        )
                    if self.cache_dir is not None:
                        wav_path = self._cache_store(wav_path, unit)
                audio_format, duration = _inspect_wav(
                    wav_path,
                    expected=self.engine.capabilities.audio_format,
                )
                chunk = SynthesizedChunk(
                    sequence=sequence,
                    unit_id=unit.id,
                    source_block_id=unit.source_block_id,
                    source_start=unit.source_start,
                    source_end=unit.source_end,
                    source_text=unit.source_text,
                    spoken_text=unit.spoken_text,
                    wav_path=wav_path,
                    audio_format=audio_format,
                    duration_seconds=duration,
                    cached=cached,
                )
                if not self._put(chunk):
                    return
            self._put(_END)
        except BaseException as exc:
            if not self._cancel.is_set():
                self._put(exc)

    def _put(self, value: object) -> bool:
        while not self._cancel.is_set():
            try:
                self._queue.put(value, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _cache_path(self, unit: NarrationUnit) -> Path:
        cache_key_data = {
            "document_source_sha256": self.plan.document_source_sha256,
            "plan_schema": self.plan.schema_version,
            "ruleset": self.plan.ruleset_version,
            "engine": self.engine.cache_identity,
            "voice": self.engine.capabilities.voice,
            "speed": self.settings.speed,
            "unit_id": unit.id,
            "source_text": unit.source_text,
            "spoken_text": unit.spoken_text,
        }
        digest = hashlib.sha256(
            json.dumps(cache_key_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{digest}.wav"  # type: ignore[operator]

    def _cache_lookup(self, unit: NarrationUnit, sequence: int) -> tuple[Path | None, bool]:
        if self.cache_dir is None:
            return None, False
        path = self._cache_path(unit)
        if not path.is_file():
            return None, False
        try:
            _inspect_wav(path, expected=self.engine.capabilities.audio_format)
        except (OSError, wave.Error, TtsError):
            path.unlink(missing_ok=True)
            return None, False
        os.utime(path, None)
        return path, True

    def _cache_store(self, source: Path, unit: NarrationUnit) -> Path:
        destination = self._cache_path(unit)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            try:
                _inspect_wav(destination, expected=self.engine.capabilities.audio_format)
                return destination
            except (OSError, wave.Error, TtsError):
                destination.unlink(missing_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        if self.cache_dir is not None:
            protected = {self._cache_path(item) for item in self.plan.units}
            prune_audio_cache(self.cache_dir, self.cache_max_bytes, protected=protected)
        return destination


def _inspect_wav(path: Path, expected: AudioFormat | None = None) -> tuple[AudioFormat, float]:
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getcomptype() != "NONE":
                raise TtsError(f"Generated audio is not uncompressed PCM: {path.name}")
            audio_format = AudioFormat(audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
            frames = audio.getnframes()
            if min(audio_format.sample_rate, audio_format.channels, audio_format.sample_width_bytes, frames) <= 0:
                raise TtsError(f"Generated audio is empty or has invalid format: {path.name}")
            if expected is not None and audio_format != expected:
                raise TtsError(f"Cached audio format does not match the active engine: {path.name}")
            duration = frames / audio_format.sample_rate
            return audio_format, duration
    except (OSError, EOFError, wave.Error) as exc:
        raise TtsError(f"Could not read generated WAV {path.name}: {exc}") from exc


def prune_audio_cache(
    cache_dir: Path,
    max_bytes: int,
    *,
    protected: set[Path] | None = None,
) -> tuple[int, int]:
    """Remove least-recently-used Sonara hash WAVs, preserving active entries.

    The directory must be dedicated to Sonara's content-addressed WAV cache.
    Active-plan entries are protected; one active document may temporarily use
    more than the budget when its own required chunks exceed the configured cap.
    """
    if max_bytes <= 0:
        raise ValueError("cache size limit must be positive")
    root = cache_dir.expanduser().resolve()
    if not root.exists():
        return 0, 0
    protected_paths = {path.expanduser().resolve() for path in (protected or set())}
    entries: list[tuple[float, Path, int]] = []
    for path in root.glob("*.wav"):
        if not re.fullmatch(r"[0-9a-f]{64}\.wav", path.name):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, path, stat.st_size))
    total = sum(size for _, _, size in entries)
    removed = 0
    for _, path, size in sorted(entries):
        if total <= max_bytes:
            break
        if path.resolve() in protected_paths:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        total -= size
        removed += 1
    return removed, total


class PiperEngine:
    """Persistent Piper Python-API adapter using a cancellable local worker."""

    def __init__(
        self,
        model_path: Path,
        config_path: Path | None = None,
        *,
        load_timeout_seconds: float = 180.0,
        variation: str = "voice_default",
    ) -> None:
        if variation not in {"voice_default", "less", "more"}:
            raise ValueError("variation must be voice_default, less, or more")
        self.variation = variation
        self.model_path = model_path.expanduser().resolve()
        self.config_path = (config_path or self.model_path.with_suffix(self.model_path.suffix + ".json")).expanduser().resolve()
        if not self.model_path.is_file() or self.model_path.stat().st_size == 0:
            raise TtsError(f"Piper model is missing or empty: {self.model_path}")
        if not self.config_path.is_file() or self.config_path.stat().st_size == 0:
            raise TtsError(f"Piper model configuration is missing or empty: {self.config_path}")
        if load_timeout_seconds <= 0:
            raise ValueError("model load timeout must be positive")
        try:
            self._model_metadata = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TtsError(f"Could not read Piper model configuration: {exc}") from exc
        sample_rate = self._model_metadata.get("audio", {}).get("sample_rate")
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            raise TtsError("Piper configuration has no valid audio.sample_rate")
        try:
            runtime_version = importlib.metadata.version("piper-tts")
        except importlib.metadata.PackageNotFoundError as exc:
            raise TtsError("piper-tts is not installed in the active Python environment") from exc
        language = self._model_metadata.get("language", {}).get("code", "unknown")
        self.capabilities = EngineCapabilities(
            engine="Piper",
            engine_version=runtime_version,
            voice=self.model_path.stem,
            language=language,
            model_available=True,
            audio_format=AudioFormat(sample_rate, 1, 2),
            minimum_speed=0.5,
            maximum_speed=2.0,
            supported_controls=("speed", "variation"),
            unsupported_controls=("emotion", "phrase emphasis", "speaker diarization", "GPU selection"),
            supports_inflight_cancellation=True,
            device="CPU",
        )
        self.load_timeout_seconds = load_timeout_seconds
        self.cache_identity = ":".join((
            "piper",
            runtime_version,
            _sha256_file(self.model_path),
            _sha256_file(self.config_path),
            f"variation={self.variation}",
        ))
        self._worker: _PiperWorkerClient | None = None
        self._worker_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._active_token: object | None = None
        self._next_token = 0
        self.model_load_count = 0

    def begin_stream(self) -> object:
        if not self._stream_lock.acquire(blocking=False):
            raise TtsError("This Piper engine already has an active synthesis stream.")
        self._next_token += 1
        self._active_token = self._next_token
        return self._active_token

    def end_stream(self, token: object) -> None:
        if self._active_token == token:
            self._active_token = None
            self._stream_lock.release()

    def synthesize_to_wav(
        self,
        text: str,
        speed: float,
        output_path: Path,
        cancel_event: threading.Event,
        timeout_seconds: float,
    ) -> AudioFormat:
        if cancel_event.is_set():
            raise SynthesisCancelled("Synthesis was cancelled before the next narration unit.")
        if not text.strip():
            raise TtsError("Cannot synthesize an empty narration unit.")
        if not self.capabilities.minimum_speed <= speed <= self.capabilities.maximum_speed:
            raise TtsError(
                f"Piper speed must be between {self.capabilities.minimum_speed:g} and "
                f"{self.capabilities.maximum_speed:g}."
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_worker(cancel_event)
        request_id = uuid.uuid4().hex
        response = client.synthesize(
            request_id,
            text,
            speed,
            self.variation,
            output_path,
            timeout=timeout_seconds,
            cancel_event=cancel_event,
        )
        audio_format = AudioFormat(
            response.get("sample_rate", 0),
            response.get("channels", 0),
            response.get("sample_width_bytes", 0),
        )
        if audio_format != self.capabilities.audio_format:
            output_path.unlink(missing_ok=True)
            self.cancel_active()
            raise TtsError("Piper returned audio with a format different from its model configuration.")
        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise TtsError("Piper reported success but did not create a non-empty audio chunk.")
        return audio_format

    def cancel_active(self) -> None:
        with self._worker_lock:
            worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()

    def close(self) -> None:
        self.cancel_active()

    def _get_worker(self, cancel_event: threading.Event) -> _PiperWorkerClient:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive:
                worker = self._worker
                created = False
            else:
                if cancel_event.is_set():
                    raise SynthesisCancelled("Synthesis was cancelled before Piper startup.")
                worker = _PiperWorkerClient(self.model_path, self.config_path)
                self._worker = worker
                created = True
        try:
            worker.wait_ready(self.load_timeout_seconds, cancel_event)
            if created:
                self.model_load_count += 1
        except BaseException:
            if created:
                with self._worker_lock:
                    if self._worker is worker:
                        self._worker = None
                worker.stop()
            raise
        return worker


class KokoroEngine:
    """Optional local Kokoro ONNX adapter. Requires kokoro-onnx and local model files."""

    def __init__(self, model_dir: Path, voice: str = "af_sarah") -> None:
        self.model_dir = model_dir.expanduser().resolve()
        self.model_path = self.model_dir / "kokoro-v1.0.onnx"
        self.voices_path = self.model_dir / "voices-v1.0.bin"
        if not self.model_path.is_file() or not self.voices_path.is_file():
            raise TtsError(
                f"Kokoro files are not installed. Expected {self.model_path.name} and {self.voices_path.name} in {self.model_dir}."
            )
        try:
            import importlib.metadata
            from kokoro_onnx import Kokoro
            self._runtime_version = importlib.metadata.version("kokoro-onnx")
            self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        except Exception as exc:
            raise TtsError(
                "Kokoro runtime is unavailable. Install kokoro-onnx in Sonara's Python environment (Python 3.10–3.13). "
                f"Details: {exc}"
            ) from exc
        self.voice = voice
        self.capabilities = EngineCapabilities(
            engine="Kokoro", engine_version=self._runtime_version, voice=voice,
            language="en-us", model_available=True, audio_format=AudioFormat(24000, 1, 2),
            minimum_speed=0.5, maximum_speed=2.0,
            supported_controls=("speed", "voice"),
            unsupported_controls=("Piper variation", "speaker diarization", "GPU selection"),
            supports_inflight_cancellation=False, device="CPU",
        )
        self.cache_identity = ":".join(("kokoro", self._runtime_version, _sha256_file(self.model_path), _sha256_file(self.voices_path), voice))
        self._active = threading.Event()
        self._stream_lock = threading.Lock()

    def begin_stream(self) -> object:
        if not self._stream_lock.acquire(blocking=False):
            raise TtsError("This Kokoro engine already has an active synthesis stream.")
        return object()

    def end_stream(self, token: object) -> None:
        self._stream_lock.release()

    def cancel_active(self) -> None:
        # kokoro-onnx does not expose cancellation during an inference call.
        self._active.set()

    def close(self) -> None:
        """Release the adapter; Kokoro owns no persistent subprocess."""
        return None

    def synthesize_to_wav(self, text: str, speed: float, output_path: Path, cancel_event: threading.Event, timeout_seconds: float) -> AudioFormat:
        if cancel_event.is_set():
            raise SynthesisCancelled("Synthesis was cancelled before the next narration unit.")
        if not self.capabilities.minimum_speed <= speed <= self.capabilities.maximum_speed:
            raise TtsError("Kokoro speed must be between 0.5 and 2.0.")
        try:
            import numpy as np
            samples, sample_rate = self._kokoro.create(text, voice=self.voice, speed=speed, lang="en-us")
            audio = np.asarray(samples, dtype=np.float32)
            if audio.ndim > 1:
                audio = audio.reshape(-1)
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(int(sample_rate))
                wav.writeframes(pcm)
            actual = AudioFormat(int(sample_rate), 1, 2)
            if actual != self.capabilities.audio_format:
                self.capabilities = EngineCapabilities(**{**self.capabilities.__dict__, "audio_format": actual})
            if cancel_event.is_set():
                output_path.unlink(missing_ok=True)
                raise SynthesisCancelled("Synthesis was cancelled.")
            return actual
        except SynthesisCancelled:
            raise
        except Exception as exc:
            if "Nothing to synthesize" in str(exc) and "produced no phonemes" in str(exc):
                # Keep source/audio chunk indices aligned for PDF artifacts such
                # as table separators that contain no speakable phonemes.
                output_path.parent.mkdir(parents=True, exist_ok=True)
                audio_format = self.capabilities.audio_format
                silence_frames = max(1, int(audio_format.sample_rate * 0.1))
                with wave.open(str(output_path), "wb") as wav:
                    wav.setnchannels(audio_format.channels)
                    wav.setsampwidth(audio_format.sample_width_bytes)
                    wav.setframerate(audio_format.sample_rate)
                    wav.writeframes(b"\x00" * silence_frames * audio_format.channels * audio_format.sample_width_bytes)
                return audio_format
            output_path.unlink(missing_ok=True)
            raise TtsError(f"Kokoro synthesis failed: {exc}") from exc


class _PiperWorkerClient:
    def __init__(self, model_path: Path, config_path: Path) -> None:
        worker_script = Path(__file__).with_name("piper_worker.py")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(worker_script), str(model_path), str(config_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise TtsError(f"Could not start the local Piper worker: {exc}") from exc
        self._messages: queue.Queue[dict | None] = queue.Queue(maxsize=8)
        self._stop_lock = threading.Lock()
        self._ready = False
        self._reader = threading.Thread(target=self._read_stdout, name="sonara-piper-protocol", daemon=True)
        self._reader.start()

    def wait_ready(self, load_timeout_seconds: float, cancel_event: threading.Event) -> None:
        if self._ready:
            return
        ready = self._next_message(load_timeout_seconds, cancel_event)
        if ready.get("type") != "ready":
            self.stop()
            raise TtsError(ready.get("error", "Piper worker failed to load the voice."))
        self._ready = True

    @property
    def is_alive(self) -> bool:
        return self.process.poll() is None

    def synthesize(
        self,
        request_id: str,
        text: str,
        speed: float,
        variation: str,
        output_path: Path,
        *,
        timeout: float,
        cancel_event: threading.Event,
    ) -> dict:
        if not self.is_alive or self.process.stdin is None:
            raise TtsError("Piper worker is not running.")
        request = {
            "id": request_id,
            "text": text,
            "speed": speed,
            "variation": variation,
            "output_path": str(output_path),
        }
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise TtsError("Could not send a synthesis request to the Piper worker.") from exc
        response = self._next_message(timeout, cancel_event)
        if response.get("id") != request_id:
            raise TtsError("Piper worker returned a response for the wrong narration unit.")
        if not response.get("ok"):
            output_path.unlink(missing_ok=True)
            raise TtsError(f"Piper synthesis failed: {response.get('error', 'unknown worker error')}")
        return response

    def _next_message(self, timeout: float, cancel_event: threading.Event) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event.is_set():
                raise SynthesisCancelled("Synthesis was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.stop()
                raise TtsError(f"Piper worker did not respond within {timeout:g} seconds.")
            try:
                message = self._messages.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if not self.is_alive:
                    raise TtsError(f"Piper worker exited with status {self.process.returncode}.")
                continue
            if message is None:
                raise TtsError(f"Piper worker exited with status {self.process.poll()}.")
            return message

    def _read_stdout(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    message = {"type": "fatal", "error": "Piper worker returned invalid protocol JSON."}
                self._messages.put(message)
        finally:
            if self.process.stdout is not None:
                self.process.stdout.close()
            try:
                self._messages.put(None, timeout=1)
            except queue.Full:
                pass

    def stop(self) -> None:
        with self._stop_lock:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            if self._reader is not threading.current_thread():
                self._reader.join(timeout=2)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
