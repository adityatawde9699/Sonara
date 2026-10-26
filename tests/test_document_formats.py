"""Unit tests for native TXT, DOCX, and EPUB document format extractors."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from document import (
    extract_txt_document,
    extract_docx_document,
    extract_epub_document,
    MAX_DOCUMENT_BYTES,
)


def create_minimal_docx(paragraphs: list[tuple[str, str | None]] = None, tables: list[list[list[str]]] = None) -> bytes:
    """Helper to generate a structurally valid in-memory DOCX file."""
    if paragraphs is None:
        paragraphs = [("Introduction", "Heading1"), ("This is the body paragraph.", None)]
    
    body_xml_parts = []
    for text, style in paragraphs:
        style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body_xml_parts.append(
            f'<w:p>{style_xml}<w:r><w:t>{text}</w:t></w:r></w:p>'
        )
    
    if tables:
        for table in tables:
            rows_xml = []
            for row in table:
                cells_xml = []
                for cell_text in row:
                    cells_xml.append(
                        f'<w:tc><w:p><w:r><w:t>{cell_text}</w:t></w:r></w:p></w:tc>'
                    )
                rows_xml.append(f'<w:tr>{"".join(cells_xml)}</w:tr>')
            body_xml_parts.append(f'<w:tbl>{"".join(rows_xml)}</w:tbl>')

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        f'<w:body>{"".join(body_xml_parts)}</w:body>\n'
        '</w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return buf.getvalue()


def create_minimal_epub(chapters: list[tuple[str, str]] = None) -> bytes:
    """Helper to generate a structurally valid in-memory EPUB file."""
    if chapters is None:
        chapters = [
            ("ch1.xhtml", "<h1>Chapter 1</h1><p>Welcome to Sonara.</p>"),
            ("ch2.xhtml", "<h2>Chapter 2</h2><p>Here is another passage.</p>"),
        ]

    container_xml = (
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>'
    )

    manifest_items = []
    spine_items = []
    for i, (filename, _) in enumerate(chapters):
        item_id = f"item_{i}"
        manifest_items.append(f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="{item_id}"/>')

    opf_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">\n'
        '  <manifest>\n'
        f'    {"".join(manifest_items)}\n'
        '  </manifest>\n'
        '  <spine>\n'
        f'    {"".join(spine_items)}\n'
        '  </spine>\n'
        '</package>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        for filename, content in chapters:
            html = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml">\n'
                f'<body>{content}</body>\n'
                '</html>'
            )
            zf.writestr(f"OEBPS/{filename}", html)
    return buf.getvalue()


class DocumentFormatsTests(unittest.TestCase):
    def test_txt_extraction_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            txt_path = Path(temp) / "sample.txt"
            txt_path.write_text(
                "# Title of Document\n\n"
                "First paragraph describing Sonara reading system.\n\n"
                "- Item 1\n"
                "- Item 2\n\n"
                "> A memorable quote from the text.\n",
                encoding="utf-8",
            )
            doc = extract_txt_document(txt_path)
            self.assertEqual(doc.source_name, "sample.txt")
            self.assertEqual(len(doc.blocks), 4)
            self.assertEqual(doc.blocks[0].kind, "heading")
            self.assertEqual(doc.blocks[0].text, "# Title of Document")
            self.assertEqual(doc.blocks[1].kind, "paragraph")
            self.assertEqual(doc.blocks[2].kind, "list_item")
            self.assertEqual(doc.blocks[3].kind, "quote")
            self.assertEqual(doc.page_count, 1)
            self.assertGreater(len(doc.source_sha256), 0)

    def test_txt_extraction_latin1_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            txt_path = Path(temp) / "french.txt"
            txt_path.write_bytes("Bienvenue au café, c'est délicieux.\n\nDeuxième paragraphe.".encode("latin-1"))
            doc = extract_txt_document(txt_path)
            self.assertIn("café", doc.text)
            self.assertEqual(len(doc.blocks), 2)

    def test_txt_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            txt_path = Path(temp) / "empty.txt"
            txt_path.write_text("   \n\n  \n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No readable text"):
                extract_txt_document(txt_path)

    def test_docx_extraction_valid(self):
        data = create_minimal_docx(
            paragraphs=[
                ("Header Title", "Heading1"),
                ("First body paragraph with detailed speech text.", None),
            ],
            tables=[
                [["Cell A1", "Cell B1"], ["Cell A2", "Cell B2"]]
            ]
        )
        with tempfile.TemporaryDirectory() as temp:
            docx_path = Path(temp) / "test.docx"
            docx_path.write_bytes(data)
            doc = extract_docx_document(docx_path)
            self.assertEqual(doc.source_name, "test.docx")
            self.assertEqual(len(doc.blocks), 4)  # 2 paragraphs + 2 table rows
            self.assertEqual(doc.blocks[0].kind, "heading")
            self.assertEqual(doc.blocks[0].text, "Header Title")
            self.assertEqual(doc.blocks[1].kind, "paragraph")
            self.assertIn("Cell A1 | Cell B1", doc.blocks[2].text)
            self.assertIn("Cell A2 | Cell B2", doc.blocks[3].text)

    def test_docx_invalid_zip_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            docx_path = Path(temp) / "corrupt.docx"
            docx_path.write_bytes(b"not a valid zip file")
            with self.assertRaisesRegex(ValueError, "not a valid DOCX zip archive"):
                extract_docx_document(docx_path)

    def test_epub_extraction_valid(self):
        data = create_minimal_epub([
            ("chapter_one.xhtml", "<h1>Introduction</h1><p>Audiobook synthesis begins here.</p>"),
            ("chapter_two.xhtml", "<h2>Controls</h2><p>Seek, pause, and adjust speed.</p>"),
        ])
        with tempfile.TemporaryDirectory() as temp:
            epub_path = Path(temp) / "book.epub"
            epub_path.write_bytes(data)
            doc = extract_epub_document(epub_path)
            self.assertEqual(doc.source_name, "book.epub")
            self.assertEqual(len(doc.blocks), 4)
            self.assertEqual(doc.blocks[0].kind, "heading")
            self.assertEqual(doc.blocks[0].text, "Introduction")
            self.assertEqual(doc.blocks[1].text, "Audiobook synthesis begins here.")
            self.assertEqual(doc.blocks[2].kind, "heading")
            self.assertEqual(doc.blocks[2].text, "Controls")
            self.assertEqual(doc.blocks[3].text, "Seek, pause, and adjust speed.")

    def test_epub_missing_container_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
        with tempfile.TemporaryDirectory() as temp:
            epub_path = Path(temp) / "bad.epub"
            epub_path.write_bytes(buf.getvalue())
            with self.assertRaisesRegex(ValueError, "missing META-INF/container.xml"):
                extract_epub_document(epub_path)


if __name__ == "__main__":
    unittest.main()
