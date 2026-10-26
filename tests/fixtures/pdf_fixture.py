"""Generate a tiny deterministic one-page PDF using only the Python stdlib."""

from __future__ import annotations

import argparse
from pathlib import Path


EXPECTED_TEXT = (
    "Sonara reads local documents aloud. It keeps punctuation, too!\n\n"
    "Can the reader preserve paragraph boundaries? We will verify it.\n\n"
    "Numbers stay visible: 3.14, 22050 Hz, and one final sentence."
)


def _pdf_string(text: str) -> bytes:
    # This fixture intentionally uses ASCII text and a built-in PDF font.
    encoded = text.encode("ascii")
    escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + escaped + b")"


def make_pdf(path: Path) -> Path:
    """Write a valid, deterministic PDF with three separate text paragraphs."""
    sentences = EXPECTED_TEXT.split("\n\n")
    commands = [b"BT /F1 12 Tf 72 740 Td"]
    for index, sentence in enumerate(sentences):
        if index:
            # A larger baseline gap makes paragraph separation visible to Poppler.
            commands.append(b"0 -30 Td")
        commands.append(_pdf_string(sentence) + b" Tj")
    commands.append(b"ET")
    stream = b" ".join(commands)

    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(output)
    return path


def make_corpus_pdf(path: Path, pages: list[list[tuple[float, float, float, str, str]]], image_pages: set[int] | None = None) -> Path:
    """Make a tiny PDF from (x, y, font_size, font, text) text runs.

    Coordinates use PDF points with the origin at the bottom-left. Page numbers
    in ``image_pages`` are one-based; those pages contain a real 1x1 raster image
    and no selectable text, modeling a scanned page without external assets.
    """
    import zlib

    image_pages = image_pages or set()
    page_count = len(pages)
    catalog_ref, pages_ref = 1, 2
    page_refs = list(range(3, 3 + page_count))
    stream_refs = list(range(3 + page_count, 3 + 2 * page_count))
    font_regular_ref, font_bold_ref = 3 + 2 * page_count, 4 + 2 * page_count
    image_ref = 5 + 2 * page_count
    objects: dict[int, bytes] = {
        catalog_ref: f"<< /Type /Catalog /Pages {pages_ref} 0 R >>".encode("ascii"),
        pages_ref: (
            f"<< /Type /Pages /Kids [{' '.join(f'{ref} 0 R' for ref in page_refs)}] "
            f"/Count {page_count} >>"
        ).encode("ascii"),
        font_regular_ref: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        font_bold_ref: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }

    for page_index, (runs, page_ref, stream_ref) in enumerate(zip(pages, page_refs, stream_refs), start=1):
        commands: list[bytes] = []
        for x, y, font_size, font, text in runs:
            encoded = _pdf_string(text)[1:-1]
            commands.append(
                f"BT /{font} {font_size:g} Tf {x:g} {y:g} Td ".encode("ascii")
                + b"(" + encoded + b") Tj ET"
            )
        if page_index in image_pages:
            commands.append(b"q 240 0 0 320 180 200 cm /Im0 Do Q")
        stream = b"\n".join(commands)
        objects[stream_ref] = (
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
        resources = (
            f"/Font << /F1 {font_regular_ref} 0 R /F2 {font_bold_ref} 0 R >>"
        )
        if page_index in image_pages:
            resources += f" /XObject << /Im0 {image_ref} 0 R >>"
        objects[page_ref] = (
            f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << {resources} >> /Contents {stream_ref} 0 R >>"
        ).encode("ascii")

    if image_pages:
        pixels = zlib.compress(b"\x99\x99\x99")
        objects[image_ref] = (
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "
            + str(len(pixels)).encode("ascii") + b" >>\nstream\n" + pixels + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0] * (max(objects) + 1)
    for number in range(1, max(objects) + 1):
        body = objects.get(number)
        if body is None:
            continue
        offsets[number] = len(output)
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        entry = f"{offset:010d} 00000 n \n".encode("ascii") if offset else b"0000000000 00000 f \n"
        output.extend(entry)
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root {catalog_ref} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(output)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="where to write the generated test PDF")
    destination = parser.parse_args().output
    destination.parent.mkdir(parents=True, exist_ok=True)
    make_pdf(destination)
    print(destination)
