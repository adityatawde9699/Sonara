"""Shared, source-mapped representation for extracted documents."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
import zipfile


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SourceBox:
    """One-based page number and Poppler coordinates in PDF points."""

    page: int
    page_width: float
    page_height: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("source page numbers are one-based")
        if self.page_width <= 0 or self.page_height <= 0:
            raise ValueError("source page dimensions must be positive")
        coordinates = (self.page_width, self.page_height, self.x_min, self.y_min, self.x_max, self.y_max)
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("source coordinates and page dimensions must be finite")
        if self.x_max < self.x_min or self.y_max < self.y_min:
            raise ValueError("source box maximum coordinates must not precede minima")


@dataclass(frozen=True)
class DocumentBlock:
    """A text block in Poppler's reported reading order."""

    id: str
    kind: str
    kind_source: str
    order: int
    text: str
    source: SourceBox

    def __post_init__(self) -> None:
        if not self.id or not self.text.strip():
            raise ValueError("document blocks require an id and non-empty text")
        if self.order < 0:
            raise ValueError("document block order must be zero-based and non-negative")


@dataclass(frozen=True)
class ExtractionNote:
    """An explicit extraction caveat; notes never cause source text to be dropped."""

    code: str
    message: str
    page: int | None = None
    block_id: str | None = None


@dataclass(frozen=True)
class Document:
    """Versioned document metadata, blocks, locations, and extraction warnings."""

    schema_version: int
    source_name: str
    source_sha256: str
    extractor: str
    extractor_version: str
    page_count: int
    blocks: tuple[DocumentBlock, ...]
    notes: tuple[ExtractionNote, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported document schema version: {self.schema_version}")
        if self.page_count < 1:
            raise ValueError("document page count must be positive")
        if any(block.order != index for index, block in enumerate(self.blocks)):
            raise ValueError("document block order must be contiguous from zero")
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("document block ids must be unique")
        if any(block.source.page > self.page_count for block in self.blocks):
            raise ValueError("document block references a page outside the document")

    @property
    def text(self) -> str:
        """Return source text in document order with paragraph boundaries."""
        return "\n\n".join(block.text for block in self.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "page_count": self.page_count,
            "blocks": [asdict(block) for block in self.blocks],
            "notes": [asdict(note) for note in self.notes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def parse_bbox_layout(
    xhtml: str,
    *,
    source_name: str,
    source_sha256: str,
    extractor_version: str,
) -> Document:
    """Parse Poppler ``-bbox-layout`` XHTML without guessing missing structure."""
    try:
        root = ElementTree.fromstring(xhtml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Poppler returned invalid bbox-layout XML: {exc}") from exc

    def local_name(element: ElementTree.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    pages = [element for element in root.iter() if local_name(element) == "page"]
    if not pages:
        raise ValueError("Poppler bbox-layout output contained no pages")

    all_blocks: list[DocumentBlock] = []
    notes: list[ExtractionNote] = []
    line_heights: list[float] = []

    # Gather page-local text and geometry first so only strong, relative evidence
    # is used for the optional heading/list/quote labels below.
    page_items: list[list[tuple[str, SourceBox, list[float]]]] = []
    for page_number, page in enumerate(pages, start=1):
        try:
            page_width = float(page.attrib["width"])
            page_height = float(page.attrib["height"])
        except (KeyError, ValueError) as exc:
            raise ValueError("Poppler bbox-layout page is missing valid dimensions") from exc
        items: list[tuple[str, SourceBox, list[float]]] = []
        for element in page.iter():
            if local_name(element) != "block":
                continue
            lines: list[str] = []
            heights: list[float] = []
            for line in element.iter():
                if local_name(line) != "line":
                    continue
                words = [
                    "".join(word.itertext()).strip()
                    for word in line.iter()
                    if local_name(word) == "word"
                ]
                words = [word for word in words if word]
                if words:
                    lines.append(" ".join(words))
                    try:
                        heights.append(float(line.attrib["yMax"]) - float(line.attrib["yMin"]))
                    except (KeyError, ValueError) as exc:
                        raise ValueError("Poppler bbox-layout line is missing valid coordinates") from exc
            text = "\n".join(lines).strip()
            if not text:
                continue
            try:
                box = SourceBox(
                    page=page_number,
                    page_width=page_width,
                    page_height=page_height,
                    x_min=float(element.attrib["xMin"]),
                    y_min=float(element.attrib["yMin"]),
                    x_max=float(element.attrib["xMax"]),
                    y_max=float(element.attrib["yMax"]),
                )
            except (KeyError, ValueError) as exc:
                raise ValueError("Poppler bbox-layout block is missing valid coordinates") from exc
            items.append((text, box, heights))
            line_heights.extend(heights)
        page_items.append(items)

    if not line_heights:
        raise ValueError("No selectable text was found. This may be a scanned PDF.")
    median_line_height = statistics.median(line_heights)

    seen_text: dict[str, str] = {}
    for page_number, (page, items) in enumerate(zip(pages, page_items), start=1):
        if not items:
            notes.append(ExtractionNote(
                "page_without_selectable_text",
                "This page contains no selectable text; it may be blank or scanned, and its image content is not read.",
                page_number,
            ))
            continue

        page_width = float(page.attrib.get("width", "0"))
        page_height = float(page.attrib.get("height", "0"))
        page_boxes = [box for _, box, _ in items]
        ambiguous_layout = False
        for index, first in enumerate(page_boxes):
            for second in page_boxes[index + 1:]:
                vertical_overlap = min(first.y_max, second.y_max) - max(first.y_min, second.y_min)
                shorter_height = min(first.y_max - first.y_min, second.y_max - second.y_min)
                horizontal_gap = max(first.x_min, second.x_min) - min(first.x_max, second.x_max)
                if (
                    shorter_height > 0
                    and vertical_overlap / shorter_height >= 0.5
                    and horizontal_gap >= page_width * 0.08
                ):
                    ambiguous_layout = True
                    break
            if ambiguous_layout:
                break
        if ambiguous_layout:
            notes.append(ExtractionNote(
                "side_by_side_reading_order_uncertain",
                "Text regions share vertical space but are separated horizontally; this may be a multi-column or table layout. Review the page reading order.",
                page_number,
            ))

        for text, box, heights in items:
            order = len(all_blocks)
            digest = hashlib.sha256(
                f"{page_number}\0{order}\0{box.x_min:.3f}\0{box.y_min:.3f}\0{text}".encode("utf-8")
            ).hexdigest()[:12]
            block_id = f"p{page_number:04d}-b{order:05d}-{digest}"
            kind, kind_source = _classify_block(text, heights, median_line_height)
            if box.y_min >= page_height * 0.82 and re.match(r"^\d+[.)]\s+", text):
                kind = "footnote"
                kind_source = "bottom_page_position_and_number_marker"
            block = DocumentBlock(block_id, kind, kind_source, order, text, box)
            all_blocks.append(block)

            normalized = " ".join(text.split()).casefold()
            if normalized in seen_text:
                notes.append(ExtractionNote(
                    "possible_duplicate_text",
                    f"This block repeats text from block {seen_text[normalized]}; repeated source text was preserved.",
                    page_number,
                    block_id,
                ))
            else:
                seen_text[normalized] = block_id

            lines = text.splitlines()
            if any(
                line.rstrip().endswith(("-", "‐", "‑")) and index + 1 < len(lines)
                and lines[index + 1][:1].islower()
                for index, line in enumerate(lines)
            ):
                notes.append(ExtractionNote(
                    "possible_line_end_hyphenation",
                    "A line ends with a hyphen before a lowercase continuation; the text is preserved and was not silently joined.",
                    page_number,
                    block_id,
                ))

    if not all_blocks:
        raise ValueError("No selectable text was found. This may be a scanned PDF.")

    return Document(
        schema_version=SCHEMA_VERSION,
        source_name=source_name,
        source_sha256=source_sha256,
        extractor="Poppler pdftotext -bbox-layout",
        extractor_version=extractor_version,
        page_count=len(pages),
        blocks=tuple(all_blocks),
        notes=tuple(notes),
    )


def _classify_block(text: str, line_heights: list[float], median_line_height: float) -> tuple[str, str]:
    """Apply conservative labels when layout/text itself provides clear evidence."""
    if re.match(r"^(?:[•●▪◦‣⁃]|\d{1,3}[.)]|[A-Za-z][.)])\s+", text):
        return "list_item", "text_marker"
    if len(text) <= 160 and line_heights and max(line_heights) >= median_line_height * 1.3:
        return "heading", "relative_line_height"
    if text.startswith(("\"", "“", "‘")) and text.endswith(("\"", "”", "’")):
        return "quote", "quote_delimiters"
    return "paragraph", "poppler_block"


MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
# DOCX and EPUB are ZIP containers. The compressed-file limit above does not
# protect against a small archive whose members expand to an enormous size.
MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_TEXT_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 10_000
WORDS_PER_VIRTUAL_PAGE = 300
DEFAULT_VIRTUAL_PAGE_WIDTH = 612.0
DEFAULT_VIRTUAL_PAGE_HEIGHT = 792.0


def compute_file_sha256(path: Path) -> str:
    """Compute the SHA-256 digest of a local file in bounded chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65_536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_bounded_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    total_read: int = 0,
) -> bytes:
    """Read an archive member without trusting its declared uncompressed size."""
    info = archive.getinfo(name)
    if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
        raise ValueError(
            f"Archive member exceeds {MAX_ARCHIVE_MEMBER_BYTES // (1024 * 1024)} MiB limit: {name}"
        )
    if total_read + info.file_size > MAX_ARCHIVE_TEXT_BYTES:
        raise ValueError(
            f"Archive text exceeds {MAX_ARCHIVE_TEXT_BYTES // (1024 * 1024)} MiB total limit."
        )
    with archive.open(info, "r") as member:
        data = member.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
    if len(data) > MAX_ARCHIVE_MEMBER_BYTES:
        raise ValueError(
            f"Archive member exceeds {MAX_ARCHIVE_MEMBER_BYTES // (1024 * 1024)} MiB limit: {name}"
        )
    if total_read + len(data) > MAX_ARCHIVE_TEXT_BYTES:
        raise ValueError(
            f"Archive text exceeds {MAX_ARCHIVE_TEXT_BYTES // (1024 * 1024)} MiB total limit."
        )
    return data


def _validate_zip_entry_count(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    if len(names) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"Archive contains more than {MAX_ARCHIVE_ENTRIES} entries.")
    return names


MARKDOWN_EXTRACTOR = "Native Markdown reader"
MARKDOWN_SUFFIXES = (".md", ".markdown")
_TXT_LIST_MARKER = re.compile(r"^(?:[-*+•●▪]|\d{1,3}[.)])\s+")
_SETEXT_HEADING = re.compile(r"^[^\n]{1,120}\n(?:=+|-+)[ \t]*$")
_NUMBERED_HEADING = re.compile(r"^(?:(?:chapter|part|section|appendix)\s+\w+|\d+(?:\.\d+)*\.?\s+\S)", re.IGNORECASE)
_SMALL_TITLE_WORDS = frozenset("a an and as at but by for from in into nor of on or per the to vs via with".split())


def _looks_like_title(line: str) -> bool:
    """Short title-cased or all-caps line: "Results", "Related Work", "INTRODUCTION"."""
    words = re.findall(r"[^\W\d_][\w'’-]*", line)
    if not words or len(words) > 12:
        return False
    if line.isupper():
        return True
    significant = [word for word in words if word.casefold() not in _SMALL_TITLE_WORDS or word is words[0]]
    return all(word[:1].isupper() for word in significant)


def _classify_text_paragraph(para: str) -> tuple[str, str]:
    """Label a plain-text/Markdown paragraph from explicit markup or strong evidence only."""
    if re.match(r"^#{1,6}\s+\S", para):
        return "heading", "txt_markdown_heading"
    if _SETEXT_HEADING.match(para):
        return "heading", "txt_setext_heading"
    # List markers come before the heading check: "- Buy milk" is not a title.
    if _TXT_LIST_MARKER.match(para):
        return "list_item", "txt_list_marker"
    if para.startswith(("> ", "\"", "“", "‘")):
        return "quote", "txt_quote_delimiter"
    single_line = "\n" not in para and len(para) <= 80
    if single_line and not para.rstrip().endswith((".", "!", "?", ",", ";", ":", "…")):
        if _NUMBERED_HEADING.match(para) or _looks_like_title(para):
            return "heading", "txt_heading_heuristic"
    return "paragraph", "txt_paragraph"


def extract_txt_document(txt_path: Path) -> Document:
    """Extract plain text or markdown files into schema-v1 Document blocks."""
    if not txt_path.is_file():
        raise ValueError(f"Text file does not exist or is not a file: {txt_path}")
    if txt_path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"Text file exceeds {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB size limit.")

    raw_bytes = txt_path.read_bytes()
    # Decode with UTF-8 first, then try utf-8-sig and latin-1 fallback
    decoded_text: str | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            decoded_text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded_text is None:
        decoded_text = raw_bytes.decode("utf-8", errors="replace")

    normalized = decoded_text.replace("\r\n", "\n").replace("\r", "\n")
    raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]

    if not raw_paragraphs:
        raise ValueError(f"No readable text was found in text file: {txt_path.name}")

    blocks_data = [(para, *_classify_text_paragraph(para)) for para in raw_paragraphs]

    source_sha256 = compute_file_sha256(txt_path)
    return _build_virtual_paged_document(
        blocks_data=blocks_data,
        source_name=txt_path.name,
        source_sha256=source_sha256,
        # Narration strips Markdown markup from spoken text for this extractor.
        extractor=MARKDOWN_EXTRACTOR if txt_path.suffix.lower() in MARKDOWN_SUFFIXES else "Native TXT reader",
        extractor_version="1.0",
    )


def extract_docx_document(docx_path: Path) -> Document:
    """Extract Microsoft Word (.docx) documents in reading order using standard-library XML traversal."""
    if not docx_path.is_file():
        raise ValueError(f"DOCX does not exist or is not a file: {docx_path}")
    if docx_path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"DOCX file exceeds {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB size limit.")
    if not zipfile.is_zipfile(docx_path):
        raise ValueError(f"File is not a valid DOCX zip archive: {docx_path.name}")

    notes_xml: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            names = _validate_zip_entry_count(zf)
            if "word/document.xml" not in names:
                raise ValueError("Invalid DOCX archive: missing word/document.xml")
            xml_bytes = _read_bounded_zip_member(zf, "word/document.xml")
            total_read = len(xml_bytes)
            for part in ("footnotes", "endnotes"):
                member = f"word/{part}.xml"
                if member in names:
                    notes_xml[part] = _read_bounded_zip_member(zf, member, total_read=total_read)
                    total_read += len(notes_xml[part])
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError(f"Could not read DOCX archive: {exc}") from exc

    root = _parse_docx_xml(xml_bytes, "word/document.xml")
    body = root.find(f"{_W}body")
    if body is None:
        raise ValueError("Invalid DOCX structure: missing w:body element")

    blocks_data: list[tuple[str, str, str]] = []
    _collect_docx_blocks(body, blocks_data)
    # Footnotes and endnotes follow the body, in note order. Headers and
    # footers are page furniture repeated on every page and are not read.
    for part, label in (("footnotes", "footnote"), ("endnotes", "endnote")):
        if part not in notes_xml:
            continue
        for note in _parse_docx_xml(notes_xml[part], f"word/{part}.xml"):
            if note.tag != f"{_W}{label}" or note.get(f"{_W}type") in {"separator", "continuationSeparator", "continuationNotice"}:
                continue
            note_blocks: list[tuple[str, str, str]] = []
            _collect_docx_blocks(note, note_blocks)
            blocks_data.extend((text, "footnote", f"docx_{label}") for text, _, _ in note_blocks)

    if not blocks_data:
        raise ValueError(f"No readable text was found in DOCX file: {docx_path.name}")

    source_sha256 = compute_file_sha256(docx_path)
    return _build_virtual_paged_document(
        blocks_data=blocks_data,
        source_name=docx_path.name,
        source_sha256=source_sha256,
        extractor="Native DOCX reader",
        extractor_version="1.0",
    )


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Containers whose children are ordinary body content: content controls,
# custom XML, and tracked insertions/moves.
_DOCX_TRANSPARENT = {f"{_W}sdt", f"{_W}sdtContent", f"{_W}customXml", f"{_W}ins", f"{_W}moveTo", f"{_W}smartTag"}


def _parse_docx_xml(data: bytes, name: str) -> ElementTree.Element:
    # ElementTree never fetches external entities, and the bundled expat
    # (2.4+) rejects entity-expansion ("billion laughs") documents.
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Malformed DOCX XML in {name}: {exc}") from exc


def _docx_run_hidden(run: ElementTree.Element) -> bool:
    vanish = run.find(f"{_W}rPr/{_W}vanish")
    return vanish is not None and vanish.get(f"{_W}val", "true").lower() not in {"0", "false", "off"}


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for run in paragraph.iter(f"{_W}r"):
        if _docx_run_hidden(run):
            continue
        for child in run:
            if child.tag == f"{_W}t" and child.text:
                parts.append(child.text)
            elif child.tag == f"{_W}tab":
                parts.append("\t")
            elif child.tag in {f"{_W}br", f"{_W}cr"}:
                parts.append("\n")
    return "".join(parts).strip()


def _collect_docx_blocks(container: ElementTree.Element, blocks: list[tuple[str, str, str]]) -> None:
    for elem in container:
        if elem.tag in _DOCX_TRANSPARENT:
            _collect_docx_blocks(elem, blocks)
        elif elem.tag == f"{_W}p":
            text = _docx_paragraph_text(elem)
            if not text:
                continue
            kind, kind_source = "paragraph", "docx_paragraph"
            style = elem.find(f"{_W}pPr/{_W}pStyle")
            style_name = (style.get(f"{_W}val", "") if style is not None else "").lower()
            if "heading" in style_name or "title" in style_name:
                kind, kind_source = "heading", "docx_heading_style"
            elif elem.find(f"{_W}pPr/{_W}numPr") is not None:
                kind, kind_source = "list_item", "docx_list_style"
            blocks.append((text, kind, kind_source))
        elif elem.tag == f"{_W}tbl":
            # Direct rows only: a nested table is read as part of its cell.
            for row in elem.findall(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    paragraphs = [_docx_paragraph_text(p) for p in cell.iter(f"{_W}p")]
                    cell_text = " ".join(text for text in paragraphs if text)
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    blocks.append((" | ".join(cells), "paragraph", "docx_table_row"))


class _EpubHtmlExtractor(HTMLParser):
    """Robust HTML text parser for EPUB chapter documents."""

    _BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div", "section", "article", "aside")
    # Never narrated: code, styling, metadata, and ruby pronunciation glosses.
    _SKIPPED_TAGS = ("script", "style", "head", "template", "noscript", "rt", "rp")
    _NOTE_TYPES = {"footnote", "endnote", "rearnote", "note"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, str, str]] = []
        self._current_text: list[str] = []
        self._current_tag: str | None = None
        self._skip_depth = 0
        self._note_depth = 0
        self._open_notes: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if tag_lower in self._BLOCK_TAGS:
            self._flush_current()
            self._current_tag = tag_lower
            types = set(" ".join(value or "" for name, value in attrs if name in {"epub:type", "role"}).replace("doc-", "").split())
            is_note = bool(types & self._NOTE_TYPES)
            self._open_notes.append(is_note)
            self._note_depth += is_note

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (<br/>, <img/>) carry no text and open no element.
        if tag.lower() in self._BLOCK_TAGS:
            self._flush_current()

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag_lower in self._BLOCK_TAGS:
            self._flush_current()
            self._current_tag = None
            if self._open_notes:
                self._note_depth -= self._open_notes.pop()

    def handle_data(self, data: str) -> None:
        if data and not self._skip_depth:
            self._current_text.append(data)

    def _flush_current(self) -> None:
        full_text = " ".join("".join(self._current_text).split()).strip()
        self._current_text = []
        if not full_text:
            return
        tag = self._current_tag or "p"
        if self._note_depth:
            kind = "footnote"
            kind_source = "epub_footnote"
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            kind = "heading"
            kind_source = f"epub_{tag}"
        elif tag == "li":
            kind = "list_item"
            kind_source = "epub_list_item"
        elif tag == "blockquote":
            kind = "quote"
            kind_source = "epub_blockquote"
        else:
            kind = "paragraph"
            kind_source = "epub_paragraph"
        self.blocks.append((full_text, kind, kind_source))

    def close(self) -> None:
        super().close()
        self._flush_current()


def extract_epub_document(epub_path: Path) -> Document:
    """Extract EPUB documents by resolving OPF package, spine items, and chapter XHTML."""
    if not epub_path.is_file():
        raise ValueError(f"EPUB does not exist or is not a file: {epub_path}")
    if epub_path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"EPUB file exceeds {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB size limit.")
    if not zipfile.is_zipfile(epub_path):
        raise ValueError(f"File is not a valid EPUB zip archive: {epub_path.name}")

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            names = _validate_zip_entry_count(zf)
            if "META-INF/container.xml" not in names:
                raise ValueError("Invalid EPUB: missing META-INF/container.xml")
            container_xml = _read_bounded_zip_member(zf, "META-INF/container.xml")

            try:
                container_root = ElementTree.fromstring(container_xml)
            except ElementTree.ParseError as exc:
                raise ValueError(f"Malformed META-INF/container.xml: {exc}") from exc

            rootfile_path: str | None = None
            for elem in container_root.iter():
                if elem.tag.rsplit("}", 1)[-1] == "rootfile":
                    rootfile_path = elem.attrib.get("full-path")
                    if rootfile_path:
                        break
            if not rootfile_path:
                raise ValueError("Invalid EPUB: container.xml missing rootfile full-path")
            if rootfile_path not in names:
                raise ValueError(f"Invalid EPUB: OPF rootfile not found in archive: {rootfile_path}")

            opf_content = _read_bounded_zip_member(zf, rootfile_path)
            try:
                opf_root = ElementTree.fromstring(opf_content)
            except ElementTree.ParseError as exc:
                raise ValueError(f"Malformed OPF package XML: {exc}") from exc

            opf_dir = Path(rootfile_path).parent.as_posix()
            manifest: dict[str, str] = {}
            spine_idrefs: list[str] = []
            for elem in opf_root.iter():
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag == "item":
                    item_id = elem.attrib.get("id")
                    href = elem.attrib.get("href")
                    if item_id and href:
                        manifest[item_id] = href
                elif tag == "itemref":
                    idref = elem.attrib.get("idref")
                    if idref:
                        spine_idrefs.append(idref)

            if not spine_idrefs:
                spine_idrefs = [
                    item_id for item_id, href in manifest.items()
                    if href.lower().endswith((".xhtml", ".html", ".htm", ".xml"))
                ]

            blocks_data: list[tuple[str, str, str]] = []
            total_text_bytes = len(container_xml) + len(opf_content)
            for idref in spine_idrefs:
                href = manifest.get(idref)
                if not href:
                    continue
                full_href = f"{opf_dir}/{href}" if opf_dir and opf_dir != "." else href
                normalized_href = Path(full_href).as_posix()
                if normalized_href not in names:
                    matching = [name for name in names if name.endswith(href)]
                    if matching:
                        normalized_href = matching[0]
                    else:
                        continue

                chapter_bytes = _read_bounded_zip_member(
                    zf, normalized_href, total_read=total_text_bytes
                )
                total_text_bytes += len(chapter_bytes)
                chapter_str = chapter_bytes.decode("utf-8", errors="replace")
                parser = _EpubHtmlExtractor()
                parser.feed(chapter_str)
                parser.close()
                blocks_data.extend(parser.blocks)

    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError(f"Could not read EPUB archive: {exc}") from exc

    if not blocks_data:
        raise ValueError(f"No readable text was found in EPUB file: {epub_path.name}")

    source_sha256 = compute_file_sha256(epub_path)
    return _build_virtual_paged_document(
        blocks_data=blocks_data,
        source_name=epub_path.name,
        source_sha256=source_sha256,
        extractor="Native EPUB reader",
        extractor_version="1.0",
    )


def _build_virtual_paged_document(
    blocks_data: list[tuple[str, str, str]],
    source_name: str,
    source_sha256: str,
    extractor: str,
    extractor_version: str,
) -> Document:
    """Assign contiguous orders, unique IDs, and virtual pages to raw extracted blocks."""
    current_page = 1
    current_words = 0
    all_blocks: list[DocumentBlock] = []

    for order, (text, kind, kind_source) in enumerate(blocks_data):
        words_count = len(text.split())
        if current_words > 0 and (current_words + words_count > WORDS_PER_VIRTUAL_PAGE):
            current_page += 1
            current_words = 0
        current_words += words_count

        digest = hashlib.sha256(f"{current_page}\0{order}\0{text}".encode("utf-8")).hexdigest()[:12]
        block_id = f"p{current_page:04d}-b{order:05d}-{digest}"
        box = SourceBox(
            page=current_page,
            page_width=DEFAULT_VIRTUAL_PAGE_WIDTH,
            page_height=DEFAULT_VIRTUAL_PAGE_HEIGHT,
            x_min=54.0,
            y_min=54.0,
            x_max=558.0,
            y_max=738.0,
        )
        all_blocks.append(DocumentBlock(block_id, kind, kind_source, order, text, box))

    return Document(
        schema_version=SCHEMA_VERSION,
        source_name=source_name,
        source_sha256=source_sha256,
        extractor=extractor,
        extractor_version=extractor_version,
        page_count=max(1, current_page),
        blocks=tuple(all_blocks),
        notes=(),
    )
