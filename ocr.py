"""Pluggable OCR adapter for scanned documents in Sonara.

Provides CPU-first OCR fallback for image-only or scanned PDFs using Poppler's
`pdftoppm` and `tesseract`. Includes hardware-independent mockability,
bounding box translation (DPI pixels to PDF points), and per-page caching.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
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


def get_ocr_cache_dir() -> Path:
    """Return local filesystem cache directory for OCR results."""
    cache_dir = Path(tempfile.gettempdir()) / "sonara_ocr_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def render_pdf_page_to_png(
    pdf_path: Path,
    page_number: int,
    output_prefix: Path,
    dpi: int = DEFAULT_OCR_DPI,
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
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=60,
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
    timeout_seconds: int = 60,
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
        raise OcrError(f"Tesseract OCR timed out after {timeout_seconds} seconds.") from exc
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


def extract_scanned_pdf(
    pdf_path: Path,
    language: str = "eng",
    dpi: int = DEFAULT_OCR_DPI,
    use_cache: bool = True,
) -> Document:
    """Extract a scanned PDF via pdftoppm rendering and Tesseract OCR."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Document does not exist: {pdf_path}")

    if not is_tesseract_available():
        raise TesseractNotFoundError(
            "No selectable text was found. This appears to be a scanned or image-based PDF, "
            "but Tesseract OCR is not installed. To enable OCR for scanned documents, "
            "please install 'tesseract-ocr' (e.g. 'sudo apt install tesseract-ocr' or 'brew install tesseract')."
        )

    file_hash = compute_file_sha256(pdf_path)
    cache_dir = get_ocr_cache_dir() if use_cache else None

    # Probe page count with pdfinfo or pdftoppm
    page_count = 1
    if shutil.which("pdfinfo"):
        try:
            info_proc = subprocess.run(
                ["pdfinfo", str(pdf_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=10,
            )
            for line in info_proc.stdout.decode("utf-8", errors="replace").splitlines():
                if line.startswith("Pages:"):
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[1].strip().isdigit():
                        page_count = max(1, int(parts[1].strip()))
                        break
        except Exception:
            pass

    all_blocks: list[DocumentBlock] = []
    notes: list[ExtractionNote] = []

    with tempfile.TemporaryDirectory(prefix="sonara-ocr-") as tmp:
        tmp_dir = Path(tmp)
        for page_num in range(1, page_count + 1):
            cache_file = (
                cache_dir / f"{file_hash}_p{page_num}_{dpi}_{language}.tsv"
                if cache_dir
                else None
            )

            tsv_text: str | None = None
            if cache_file and cache_file.is_file():
                try:
                    tsv_text = cache_file.read_text(encoding="utf-8")
                except Exception:
                    tsv_text = None

            if tsv_text is None:
                png_prefix = tmp_dir / f"page_{page_num}"
                png_path = render_pdf_page_to_png(pdf_path, page_num, png_prefix, dpi=dpi)
                tsv_text = run_tesseract_tsv(png_path, language=language)

                if cache_file:
                    try:
                        cache_file.write_text(tsv_text, encoding="utf-8")
                    except Exception:
                        pass

            page_blocks = parse_tesseract_tsv(tsv_text, page_number=page_num, dpi=dpi)
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
