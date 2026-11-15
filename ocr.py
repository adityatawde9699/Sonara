"""OCR adapter for scanned documents in Sonara.

Provides a CPU-only OCR fallback for image-only or scanned PDFs using Poppler's
`pdftoppm` and `tesseract`, with bounding-box translation (DPI pixels to PDF
points) and a per-user, per-page result cache. Work is bounded by a page cap,
a total time budget, and a render-size cap.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from document import (
    Document,
    DocumentBlock,
    ExtractionNote,
    SourceBox,
    SCHEMA_VERSION,
    compute_file_sha256,
)

DEFAULT_OCR_DPI = 150
PDF_POINTS_PER_INCH = 72.0

# Resource bounds for untrusted PDFs. A crafted file can claim any page count
# or page size, so each is capped before any rendering starts.
MAX_OCR_PAGES = 500
MAX_OCR_SECONDS = 30 * 60
PER_PAGE_TIMEOUT_SECONDS = 60
# About 40 megapixels: a US Letter page at 150 dpi is ~2.1 MP, so this only
# lowers the resolution of pages far larger than any normal document.
MAX_RENDER_PIXELS = 40_000_000
MAX_CACHE_ENTRY_BYTES = 32 * 1024 * 1024
DEFAULT_PAGE_SIZE_PTS = (612.0, 792.0)


class OcrError(Exception):
    """Raised when OCR extraction fails."""


class TesseractNotFoundError(OcrError):
    """Raised when OCR is required but tesseract is not installed."""


def is_tesseract_available() -> bool:
    """Return True if tesseract executable is discovered in PATH."""
    loc = shutil.which("tesseract")
    if not loc:
        return False
    return Path(loc).name.lower().startswith("tesseract")


def is_pdftoppm_available() -> bool:
    """Return True if pdftoppm executable is discovered in PATH."""
    loc = shutil.which("pdftoppm")
    if not loc:
        return False
    return Path(loc).name.lower().startswith("pdftoppm")


def _default_cache_root() -> Path:
    override = os.environ.get("SONARA_OCR_CACHE_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "Sonara" / "ocr-cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Sonara" / "ocr"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "sonara" / "ocr"


def get_ocr_cache_dir() -> Path:
    """Return a private, per-user directory for cached OCR results.

    The cache used to live at a fixed path in the shared temp directory, where
    another local user could pre-create it and plant text that Sonara would
    then speak. It is now per-user, created 0700, and checked for ownership.
    """
    cache_dir = _default_cache_root()
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = os.lstat(cache_dir)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise OcrError(f"OCR cache path is not a real directory: {cache_dir}")
    if os.name == "posix":
        if info.st_uid != os.getuid():
            raise OcrError(f"OCR cache directory is owned by another user: {cache_dir}")
        if stat.S_IMODE(info.st_mode) & 0o077:
            os.chmod(cache_dir, 0o700)
    return cache_dir


def _read_cache_entry(path: Path) -> str | None:
    """Read a cache file without following symlinks; return None if unusable."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CACHE_ENTRY_BYTES:
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read(MAX_CACHE_ENTRY_BYTES + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)


def _write_cache_entry(path: Path, text: str) -> None:
    """Write atomically with private permissions; failures leave no cache entry."""
    data = text.encode("utf-8")
    if len(data) > MAX_CACHE_ENTRY_BYTES:
        return
    temp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass


_BBOX_PAGE = re.compile(r"<page\b[^>]*>", re.IGNORECASE)
_ATTR_WIDTH = re.compile(r"\bwidth=\"([0-9.]+)\"")
_ATTR_HEIGHT = re.compile(r"\bheight=\"([0-9.]+)\"")


def page_sizes_from_bbox_layout(markup: str) -> list[tuple[float, float]]:
    """Return (width, height) in points for each page of Poppler bbox-layout output.

    Sonara runs ``pdftotext -bbox-layout`` before falling back to OCR, and that
    output lists every page, including pages with no text. Reusing it avoids
    depending on ``pdfinfo``, which the packaged builds do not ship.
    """
    sizes: list[tuple[float, float]] = []
    for tag in _BBOX_PAGE.findall(markup):
        width = _ATTR_WIDTH.search(tag)
        height = _ATTR_HEIGHT.search(tag)
        try:
            sizes.append((float(width.group(1)), float(height.group(1))) if width and height else DEFAULT_PAGE_SIZE_PTS)
        except ValueError:
            sizes.append(DEFAULT_PAGE_SIZE_PTS)
    return sizes


_PDFINFO_PAGES = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)
_PDFINFO_PAGE_SIZE = re.compile(r"^Page\s+(\d+)\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)", re.MULTILINE)


def probe_page_sizes_with_pdfinfo(pdf_path: Path) -> list[tuple[float, float]]:
    """Return per-page sizes using ``pdfinfo``; raise OcrError instead of guessing."""
    executable = shutil.which("pdfinfo")
    if not executable:
        raise OcrError("pdfinfo (poppler-utils) is required to count pages for OCR.")
    try:
        proc = subprocess.run(
            [executable, "-f", "1", "-l", str(MAX_OCR_PAGES + 1), str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError("pdfinfo timed out while counting pages.") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise OcrError(f"pdfinfo could not read the PDF: {exc}") from exc
    output = proc.stdout.decode("utf-8", errors="replace")
    pages_match = _PDFINFO_PAGES.search(output)
    if not pages_match:
        raise OcrError("pdfinfo did not report a page count.")
    page_count = int(pages_match.group(1))
    if page_count < 1:
        raise OcrError("pdfinfo reported a PDF with no pages.")
    sizes = {int(m.group(1)): (float(m.group(2)), float(m.group(3))) for m in _PDFINFO_PAGE_SIZE.finditer(output)}
    return [sizes.get(page, DEFAULT_PAGE_SIZE_PTS) for page in range(1, page_count + 1)]


def effective_dpi(page_size_pts: tuple[float, float], dpi: int = DEFAULT_OCR_DPI) -> int:
    """Lower the render DPI if a page would exceed MAX_RENDER_PIXELS."""
    width_in = max(page_size_pts[0], 1.0) / PDF_POINTS_PER_INCH
    height_in = max(page_size_pts[1], 1.0) / PDF_POINTS_PER_INCH
    pixels = (width_in * dpi) * (height_in * dpi)
    if pixels <= MAX_RENDER_PIXELS:
        return dpi
    return max(1, math.floor(dpi * math.sqrt(MAX_RENDER_PIXELS / pixels)))


def render_pdf_page_to_png(
    pdf_path: Path,
    page_number: int,
    output_prefix: Path,
    dpi: int = DEFAULT_OCR_DPI,
    timeout_seconds: float = PER_PAGE_TIMEOUT_SECONDS,
) -> Path:
    """Render a single PDF page to a PNG file using pdftoppm."""
    if not is_pdftoppm_available():
        raise OcrError("pdftoppm (poppler-utils) is required to render scanned PDF pages for OCR.")

    cmd = [
        "pdftoppm",
        "-png",
        "-r", str(dpi),
        "-f", str(page_number),
        "-l", str(page_number),
        str(pdf_path),
        str(output_prefix),
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"Rendering page {page_number} timed out.") from exc
    except subprocess.CalledProcessError as exc:
        stderr_msg = exc.stderr.decode("utf-8", errors="replace").strip()
        raise OcrError(f"pdftoppm failed on page {page_number}: {stderr_msg}") from exc

    # pdftoppm outputs files named <output_prefix>-1.png or <output_prefix>-01.png
    candidates = sorted(output_prefix.parent.glob(f"{output_prefix.name}-*.png"))
    if not candidates:
        raise OcrError(f"pdftoppm did not produce a PNG for page {page_number}.")
    return candidates[0]


def run_tesseract_tsv(
    image_path: Path,
    language: str = "eng",
    timeout_seconds: float = PER_PAGE_TIMEOUT_SECONDS,
) -> str:
    """Run tesseract on an image and return raw TSV output."""
    if not is_tesseract_available():
        raise TesseractNotFoundError(
            "Tesseract OCR is not installed. To extract text from scanned documents, "
            "install 'tesseract-ocr' (e.g. 'sudo apt install tesseract-ocr' or 'brew install tesseract')."
        )

    cmd = [
        "tesseract",
        str(image_path),
        "stdout",
        "-l", language,
        "--psm", "1",
        "tsv",
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=timeout_seconds,
        )
        return proc.stdout.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"Tesseract OCR timed out after {timeout_seconds:.0f} seconds.") from exc
    except subprocess.CalledProcessError as exc:
        stderr_msg = exc.stderr.decode("utf-8", errors="replace").strip()
        raise OcrError(f"Tesseract OCR failed: {stderr_msg}") from exc


def parse_tesseract_tsv(
    tsv_content: str,
    page_number: int,
    dpi: int = DEFAULT_OCR_DPI,
) -> list[DocumentBlock]:
    """Parse Tesseract TSV output into schema-v1 DocumentBlocks with scaled PDF point boxes."""
    reader = csv.DictReader(io.StringIO(tsv_content), delimiter="\t")
    scale = PDF_POINTS_PER_INCH / float(dpi)

    paragraphs: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for row in reader:
        # level: 1=page, 2=block, 3=par, 4=line, 5=word
        level = row.get("level")
        if level != "5":
            continue

        text = (row.get("text") or "").strip()
        if not text:
            continue

        try:
            block_num = int(row.get("block_num", "0"))
            par_num = int(row.get("par_num", "0"))
            left = float(row.get("left", "0"))
            top = float(row.get("top", "0"))
            width = float(row.get("width", "0"))
            height = float(row.get("height", "0"))
            conf = float(row.get("conf", "-1"))
        except (ValueError, TypeError):
            continue

        key = (block_num, par_num)
        if key not in paragraphs:
            paragraphs[key] = []

        paragraphs[key].append({
            "text": text,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "conf": conf,
        })

    blocks: list[DocumentBlock] = []
    block_seq = 0

    for (b_num, p_num), words in paragraphs.items():
        if not words:
            continue

        combined_text = " ".join(w["text"] for w in words).strip()
        if not combined_text:
            continue

        x_min = min(w["left"] for w in words) * scale
        y_min = min(w["top"] for w in words) * scale
        x_max = max(w["left"] + w["width"] for w in words) * scale
        y_max = max(w["top"] + w["height"] for w in words) * scale

        # Heuristic page bounds: assume standard letter or estimate from max coords
        page_width = max(612.0, x_max + 36.0)
        page_height = max(792.0, y_max + 36.0)

        box = SourceBox(
            page=page_number,
            page_width=round(page_width, 1),
            page_height=round(page_height, 1),
            x_min=round(x_min, 1),
            y_min=round(y_min, 1),
            x_max=round(x_max, 1),
            y_max=round(y_max, 1),
        )

        block_id = f"p{page_number}-ocr-{b_num:03d}-{p_num:03d}"
        blocks.append(
            DocumentBlock(
                id=block_id,
                kind="paragraph",
                kind_source="ocr_tesseract",
                order=block_seq,
                text=combined_text,
                source=box,
            )
        )
        block_seq += 1

    return blocks


# Mean Tesseract word confidence (0-100) below which a page's text is likely
# to contain misreadings worth warning about.
LOW_CONFIDENCE_THRESHOLD = 60.0


def tsv_mean_confidence(tsv_content: str) -> float | None:
    """Return the mean word confidence of a Tesseract TSV page, or None if it has no words."""
    total = 0.0
    count = 0
    for row in csv.DictReader(io.StringIO(tsv_content), delimiter="\t"):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        try:
            confidence = float(row.get("conf", "-1"))
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            total += confidence
            count += 1
    return total / count if count else None


def extract_scanned_pdf(
    pdf_path: Path,
    language: str = "eng",
    dpi: int = DEFAULT_OCR_DPI,
    use_cache: bool = True,
    page_sizes: list[tuple[float, float]] | None = None,
) -> Document:
    """Extract a scanned PDF via pdftoppm rendering and Tesseract OCR.

    ``page_sizes`` gives each page's (width, height) in points. Sonara passes
    them from its ``pdftotext -bbox-layout`` pass; when omitted they are probed
    with ``pdfinfo``. A failed probe raises rather than silently reading only
    the first page.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Document does not exist: {pdf_path}")

    if not is_tesseract_available():
        raise TesseractNotFoundError(
            "No selectable text was found. This appears to be a scanned or image-based PDF, "
            "but Tesseract OCR is not installed. To enable OCR for scanned documents, "
            "please install 'tesseract-ocr' (e.g. 'sudo apt install tesseract-ocr' or 'brew install tesseract')."
        )

    sizes = list(page_sizes) if page_sizes else probe_page_sizes_with_pdfinfo(pdf_path)
    page_count = len(sizes)
    if page_count > MAX_OCR_PAGES:
        raise OcrError(
            f"This scanned PDF has {page_count} pages; OCR is limited to {MAX_OCR_PAGES} pages per document."
        )

    file_hash = compute_file_sha256(pdf_path)
    cache_dir: Path | None = None
    if use_cache:
        try:
            cache_dir = get_ocr_cache_dir()
        except (OSError, RuntimeError, OcrError):
            cache_dir = None  # OCR still works; it just is not cached.

    deadline = time.monotonic() + MAX_OCR_SECONDS
    all_blocks: list[DocumentBlock] = []
    notes: list[ExtractionNote] = []

    with tempfile.TemporaryDirectory(prefix="sonara-ocr-") as tmp:
        tmp_dir = Path(tmp)
        for page_num, page_size in enumerate(sizes, start=1):
            page_dpi = effective_dpi(page_size, dpi)
            cache_file = (
                cache_dir / f"{file_hash}_p{page_num}_{page_dpi}_{language}.tsv"
                if cache_dir
                else None
            )

            tsv_text = _read_cache_entry(cache_file) if cache_file else None

            if tsv_text is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OcrError(
                        f"OCR stopped after {MAX_OCR_SECONDS // 60} minutes at page {page_num} of {page_count}."
                    )
                step_timeout = min(PER_PAGE_TIMEOUT_SECONDS, remaining)
                png_prefix = tmp_dir / f"page_{page_num}"
                png_path = render_pdf_page_to_png(
                    pdf_path, page_num, png_prefix, dpi=page_dpi, timeout_seconds=step_timeout
                )
                tsv_text = run_tesseract_tsv(
                    png_path,
                    language=language,
                    timeout_seconds=max(1.0, min(PER_PAGE_TIMEOUT_SECONDS, deadline - time.monotonic())),
                )
                png_path.unlink(missing_ok=True)  # Keep at most one rendered page on disk.

                if cache_file:
                    _write_cache_entry(cache_file, tsv_text)

            page_blocks = parse_tesseract_tsv(tsv_text, page_number=page_num, dpi=page_dpi)
            if page_dpi < dpi:
                notes.append(
                    ExtractionNote(
                        code="ocr_reduced_resolution",
                        message=f"Page {page_num} is unusually large and was read at {page_dpi} dpi instead of {dpi}.",
                        page=page_num,
                    )
                )
            if not page_blocks:
                notes.append(
                    ExtractionNote(
                        code="ocr_empty_page",
                        message=f"Page {page_num} yielded no recognizable text through OCR.",
                        page=page_num,
                    )
                )
            else:
                all_blocks.extend(page_blocks)
                confidence = tsv_mean_confidence(tsv_text)
                if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
                    notes.append(
                        ExtractionNote(
                            code="ocr_low_confidence",
                            message=(
                                f"Page {page_num} was hard to read (OCR confidence {confidence:.0f}%); "
                                "some words may be misread. Check it in Preview narration."
                            ),
                            page=page_num,
                        )
                    )

    if not all_blocks:
        raise ValueError(
            "OCR was executed, but no recognizable text was detected in this document."
        )

    # Re-index order contiguously from zero
    reindexed_blocks = [
        DocumentBlock(
            id=block.id,
            kind=block.kind,
            kind_source=block.kind_source,
            order=idx,
            text=block.text,
            source=block.source,
        )
        for idx, block in enumerate(all_blocks)
    ]

    return Document(
        schema_version=SCHEMA_VERSION,
        source_name=pdf_path.name,
        source_sha256=file_hash,
        extractor="tesseract_ocr",
        extractor_version="1.0",
        page_count=page_count,
        blocks=tuple(reindexed_blocks),
        notes=tuple(notes),
    )
