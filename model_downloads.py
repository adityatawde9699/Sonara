"""Download Sonara's speech models into the user's data directory.

Installers ship without voice models (they are large and separately licensed),
so the desktop app offers to fetch them. Every file comes from a fixed upstream
revision over HTTPS, is capped at its published size, and is accepted only if
its SHA-256 matches the pinned value. A file is written to a temporary name and
moved into place only after it verifies, so an interrupted or tampered download
never leaves a usable-looking model behind.

The Tauri app runs ``model_downloads.py install <model> --dest <dir>`` and
reads one JSON object per line from stdout:

    {"event": "progress", "model": ..., "received": n, "total": n}
    {"event": "done", "model": ...}
    {"event": "error", "model": ..., "message": ...}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from tts_engine import PINNED_PIPER_VOICES

_PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US"
_KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
_CHUNK = 1024 * 1024
_TIMEOUT_SECONDS = 60
_PROGRESS_STEP = 4 * 1024 * 1024


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Model:
    id: str
    kind: str  # "piper" or "kokoro"
    label: str
    files: tuple[ModelFile, ...]

    @property
    def total_size(self) -> int:
        return sum(file.size for file in self.files)


# Upstream sizes, from the Hugging Face file metadata for revision v1.0.0.
_PIPER_SIZES: dict[str, tuple[int, int]] = {
    "en_US-ryan-medium": (63_201_294, 4_883),
    "en_US-lessac-medium": (63_201_294, 4_885),
    "en_US-bryce-medium": (63_531_379, 4_966),
    "en_US-john-medium": (63_531_379, 4_965),
}
_PIPER_LABELS = {
    "en_US-ryan-medium": "Ryan (American English, male)",
    "en_US-lessac-medium": "Lessac (American English, female)",
    "en_US-bryce-medium": "Bryce (American English, male)",
    "en_US-john-medium": "John (American English, male)",
}


def _piper_model(voice: str) -> Model:
    model_sha, config_sha = PINNED_PIPER_VOICES[voice]
    model_size, config_size = _PIPER_SIZES[voice]
    speaker = voice.split("-")[1]
    base = f"{_PIPER_BASE}/{speaker}/medium/{voice}"
    return Model(
        id=voice,
        kind="piper",
        label=_PIPER_LABELS[voice],
        files=(
            ModelFile(f"{voice}.onnx", f"{base}.onnx", model_size, model_sha),
            ModelFile(f"{voice}.onnx.json", f"{base}.onnx.json", config_size, config_sha),
        ),
    )


# SHA-256 values are the digests GitHub publishes for these release assets.
KOKORO = Model(
    id="kokoro",
    kind="kokoro",
    label="Kokoro v1.0 (multilingual)",
    files=(
        ModelFile(
            "kokoro-v1.0.onnx",
            f"{_KOKORO_BASE}/kokoro-v1.0.onnx",
            325_505_369,
            "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
        ),
        ModelFile(
            "voices-v1.0.bin",
            f"{_KOKORO_BASE}/voices-v1.0.bin",
            28_214_398,
            "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        ),
    ),
)

CATALOG: dict[str, Model] = {KOKORO.id: KOKORO, **{voice: _piper_model(voice) for voice in _PIPER_SIZES}}


class DownloadError(RuntimeError):
    pass


def is_installed(model: Model, directory: Path) -> bool:
    """True when every file is present at its published size.

    Hashes are checked at load (Piper) and after download; hashing 350 MB on
    every status query would make the settings panel slow.
    """
    for file in model.files:
        path = directory / file.name
        try:
            if not path.is_file() or path.stat().st_size != file.size:
                return False
        except OSError:
            return False
    return True


def _ssl_context() -> ssl.SSLContext:
    # The frozen runtime cannot rely on the OS certificate store (macOS has
    # none for OpenSSL), so prefer certifi's bundle when it is available.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not newurl.lower().startswith("https://"):
            raise DownloadError(f"Refused a redirect to a non-HTTPS address: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_context()),
        _HttpsOnlyRedirects(),
    )


Progress = Callable[[int, int], None]


def _download_file(
    file: ModelFile,
    directory: Path,
    *,
    opener: urllib.request.OpenerDirector,
    on_progress: Progress,
    already: int,
    total: int,
) -> None:
    if not file.url.startswith("https://"):
        raise DownloadError(f"{file.name} has a non-HTTPS source.")
    destination = directory / file.name
    partial = directory / f".{file.name}.part"
    digest = hashlib.sha256()
    received = 0
    last_report = 0
    request = urllib.request.Request(file.url, headers={"User-Agent": "Sonara model installer"})
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response, open(partial, "wb") as output:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                received += len(chunk)
                if received > file.size:
                    raise DownloadError(f"{file.name} is larger than its published size; download refused.")
                digest.update(chunk)
                output.write(chunk)
                if received - last_report >= _PROGRESS_STEP:
                    last_report = received
                    on_progress(already + received, total)
            output.flush()
            os.fsync(output.fileno())
    except urllib.error.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"Could not download {file.name}: the server answered {error.code}.") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        partial.unlink(missing_ok=True)
        reason = getattr(error, "reason", error)
        raise DownloadError(f"Could not download {file.name}: {reason}.") from error
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if received != file.size:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"{file.name} download was incomplete ({received} of {file.size} bytes).")
    if digest.hexdigest() != file.sha256:
        partial.unlink(missing_ok=True)
        raise DownloadError(f"{file.name} failed its integrity check (SHA-256 mismatch); it was not installed.")
    os.replace(partial, destination)
    on_progress(already + received, total)


def install(
    model: Model,
    directory: Path,
    *,
    on_progress: Progress = lambda received, total: None,
    opener: urllib.request.OpenerDirector | None = None,
) -> None:
    """Download and verify every file of ``model`` into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    opener = opener or _opener()
    total = model.total_size
    done = 0
    for file in model.files:
        path = directory / file.name
        if path.is_file() and path.stat().st_size == file.size and _sha256(path) == file.sha256:
            done += file.size
            on_progress(done, total)
            continue
        _download_file(file, directory, opener=opener, on_progress=on_progress, already=done, total=total)
        done += file.size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status(piper_dir: Path, kokoro_dir: Path) -> list[dict[str, object]]:
    rows = []
    for model in CATALOG.values():
        directory = kokoro_dir if model.kind == "kokoro" else piper_dir
        rows.append({
            "id": model.id,
            "kind": model.kind,
            "label": model.label,
            "sizeBytes": model.total_size,
            "installed": is_installed(model, directory),
        })
    return rows


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Sonara speech models.")
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("model", choices=sorted(CATALOG))
    install_parser.add_argument("--dest", type=Path, required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--piper-dir", type=Path, required=True)
    status_parser.add_argument("--kokoro-dir", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "status":
        print(json.dumps(status(args.piper_dir, args.kokoro_dir), sort_keys=True))
        return 0

    model = CATALOG[args.model]
    try:
        install(
            model,
            args.dest,
            on_progress=lambda received, total: _emit(
                {"event": "progress", "model": model.id, "received": received, "total": total}
            ),
        )
    except DownloadError as error:
        _emit({"event": "error", "model": model.id, "message": str(error)})
        return 1
    except OSError as error:
        _emit({"event": "error", "model": model.id, "message": f"Could not write the model files: {error}"})
        return 1
    _emit({"event": "done", "model": model.id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
