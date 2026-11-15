"""Tests for Sonara pluggable OCR architecture, Tesseract fallback, and caching."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from document import Document, SCHEMA_VERSION
import os
import stat

import ocr
from ocr import (
    MAX_OCR_PAGES,
    OcrError,
    TesseractNotFoundError,
    extract_scanned_pdf,
    is_pdftoppm_available,
    is_tesseract_available,
    effective_dpi,
    get_ocr_cache_dir,
    page_sizes_from_bbox_layout,
    parse_tesseract_tsv,
    probe_page_sizes_with_pdfinfo,
)
import sonara


MOCK_TSV_OUTPUT = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
1\t1\t0\t0\t0\t0\t0\t0\t1200\t1600\t-1\t
2\t1\t1\t0\t0\t0\t100\t150\t800\t200\t-1\t
3\t1\t1\t1\t0\t0\t100\t150\t800\t200\t-1\t
4\t1\t1\t1\t1\t0\t100\t150\t800\t40\t-1\t
5\t1\t1\t1\t1\t1\t100\t150\t120\t40\t95\tScanned
5\t1\t1\t1\t1\t2\t230\t150\t150\t40\t96\tDocument
5\t1\t1\t1\t1\t3\t390\t150\t100\t40\t94\tTitle
4\t1\t1\t1\t2\t0\t100\t200\t800\t40\t-1\t
5\t1\t1\t1\t2\t1\t100\t200\t80\t40\t92\tSecond
5\t1\t1\t1\t2\t2\t190\t200\t70\t40\t93\tline.
2\t1\t2\t0\t0\t0\t100\t400\t800\t150\t-1\t
3\t1\t2\t1\t0\t0\t100\t400\t800\t150\t-1\t
4\t1\t2\t1\t1\t0\t100\t400\t800\t40\t-1\t
5\t1\t2\t1\t1\t1\t100\t400\t110\t40\t91\tParagraph
5\t1\t2\t1\t1\t2\t220\t400\t60\t40\t90\ttwo.
"""


class OcrTests(unittest.TestCase):
    def test_detection_functions_match_system(self):
        self.assertEqual(is_pdftoppm_available(), shutil.which("pdftoppm") is not None)
        self.assertEqual(is_tesseract_available(), shutil.which("tesseract") is not None)

    def test_parse_tesseract_tsv_extracts_paragraphs_and_boxes(self):
        blocks = parse_tesseract_tsv(MOCK_TSV_OUTPUT, page_number=1, dpi=150)
        self.assertEqual(len(blocks), 2)

        # Block 1
        self.assertEqual(blocks[0].text, "Scanned Document Title Second line.")
        self.assertEqual(blocks[0].kind, "paragraph")
        self.assertEqual(blocks[0].kind_source, "ocr_tesseract")
        self.assertEqual(blocks[0].source.page, 1)
        # Coordinate scaling: 150 DPI -> 72 DPI points (factor = 72/150 = 0.48)
        self.assertAlmostEqual(blocks[0].source.x_min, 100 * 0.48, delta=0.5)
        self.assertAlmostEqual(blocks[0].source.y_min, 150 * 0.48, delta=0.5)

        # Block 2
        self.assertEqual(blocks[1].text, "Paragraph two.")
        self.assertEqual(blocks[1].source.page, 1)

    def test_extract_scanned_pdf_missing_tesseract_raises_informative_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "empty.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

            with patch("ocr.is_tesseract_available", return_value=False):
                with self.assertRaises(TesseractNotFoundError) as ctx:
                    extract_scanned_pdf(pdf_path)
                self.assertIn("Tesseract OCR is not installed", str(ctx.exception))
                self.assertIn("install 'tesseract-ocr'", str(ctx.exception))

    def test_extract_scanned_pdf_with_mocked_tesseract_and_caching(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample_scan.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")

            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()

            mock_render = MagicMock(return_value=Path(tmp) / "page-1.png")
            mock_run_tess = MagicMock(return_value=MOCK_TSV_OUTPUT)

            with (
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.get_ocr_cache_dir", return_value=cache_dir),
                patch("ocr.render_pdf_page_to_png", mock_render),
                patch("ocr.run_tesseract_tsv", mock_run_tess),
            ):
                # First run: should execute OCR and write to cache
                doc = extract_scanned_pdf(pdf_path, use_cache=True, page_sizes=[(612.0, 792.0)])
                self.assertIsInstance(doc, Document)
                self.assertEqual(doc.schema_version, SCHEMA_VERSION)
                self.assertEqual(doc.extractor, "tesseract_ocr")
                self.assertEqual(len(doc.blocks), 2)
                self.assertEqual(mock_run_tess.call_count, 1)

                # Check cache file was created
                cache_files = list(cache_dir.glob("*.tsv"))
                self.assertEqual(len(cache_files), 1)

                # Second run: should hit cache and NOT invoke tesseract again
                doc2 = extract_scanned_pdf(pdf_path, use_cache=True, page_sizes=[(612.0, 792.0)])
                self.assertEqual(len(doc2.blocks), 2)
                self.assertEqual(doc2.blocks[0].text, doc.blocks[0].text)
                self.assertEqual(mock_run_tess.call_count, 1)

    def test_sonara_fallback_to_ocr_when_no_text_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "scanned_doc.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

            mock_doc = Document(
                schema_version=SCHEMA_VERSION,
                source_name="scanned_doc.pdf",
                source_sha256="a" * 64,
                extractor="tesseract_ocr",
                extractor_version="1.0",
                page_count=1,
                blocks=(),
                notes=(),
            )

            # When Tesseract is available, it invokes extract_scanned_pdf
            with (
                patch("sonara.parse_bbox_layout", side_effect=ValueError("No selectable text was found.")),
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.extract_scanned_pdf", return_value=mock_doc) as mock_ocr,
                patch("shutil.which", return_value="/usr/bin/pdftotext"),
                patch("sonara._run_bounded", return_value=(b"<html/>", b"", 0, None)),
            ):
                doc = sonara.extract_pdf_document(pdf_path)
                self.assertEqual(doc.extractor, "tesseract_ocr")
                self.assertEqual(mock_ocr.call_count, 1)

            # When Tesseract is NOT available, it raises informative SonaraError
            with (
                patch("sonara.parse_bbox_layout", side_effect=ValueError("No selectable text was found.")),
                patch("ocr.is_tesseract_available", return_value=False),
                patch("shutil.which", return_value="/usr/bin/pdftotext"),
                patch("sonara._run_bounded", return_value=(b"<html/>", b"", 0, None)),
            ):
                with self.assertRaises(sonara.SonaraError) as ctx:
                    sonara.extract_pdf_document(pdf_path)
                self.assertIn("No selectable text was found", str(ctx.exception))
                self.assertIn("Tesseract OCR is not installed", str(ctx.exception))

    def test_empty_page_emits_extraction_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "two_pages.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")

            tsv_page1 = MOCK_TSV_OUTPUT
            tsv_page2 = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"

            def fake_tess(img_path, **kwargs):
                if "page_2" in str(img_path):
                    return tsv_page2
                return tsv_page1

            with (
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.render_pdf_page_to_png", side_effect=lambda p, num, prefix, **kw: Path(tmp) / f"page_{num}.png"),
                patch("ocr.run_tesseract_tsv", side_effect=fake_tess),
                patch("ocr.subprocess.run") as mock_info,
                patch("ocr.shutil.which", return_value="/usr/bin/pdfinfo"),
            ):
                mock_info.return_value = MagicMock(stdout=b"Pages: 2\n")
                doc = extract_scanned_pdf(pdf_path, use_cache=False)
                self.assertEqual(len(doc.notes), 1)
                self.assertEqual(doc.notes[0].code, "ocr_empty_page")
                self.assertEqual(doc.notes[0].page, 2)
                self.assertIn("Page 2 yielded no recognizable text", doc.notes[0].message)


class OcrResourceBoundsTests(unittest.TestCase):
    def _pdf(self, tmp: str) -> Path:
        pdf_path = Path(tmp) / "scan.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%EOF\n")
        return pdf_path

    def test_page_sizes_come_from_bbox_layout_including_blank_pages(self):
        markup = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
            '<page width="612.000000" height="792.000000"></page>'
            '<page width="595.276000" height="841.890000"/>'
            "</doc></body></html>"
        )
        self.assertEqual(page_sizes_from_bbox_layout(markup), [(612.0, 792.0), (595.276, 841.89)])
        self.assertEqual(page_sizes_from_bbox_layout("<html/>"), [])

    def test_every_page_is_read_not_only_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            rendered = []
            with (
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.render_pdf_page_to_png", side_effect=lambda p, num, prefix, **kw: rendered.append(num) or Path(tmp) / f"page_{num}.png"),
                patch("ocr.run_tesseract_tsv", return_value=MOCK_TSV_OUTPUT),
            ):
                doc = extract_scanned_pdf(self._pdf(tmp), use_cache=False, page_sizes=[(612.0, 792.0)] * 3)
            self.assertEqual(rendered, [1, 2, 3])
            self.assertEqual(doc.page_count, 3)

    def test_pdfinfo_failure_raises_instead_of_reading_one_page(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("ocr.shutil.which", return_value="/usr/bin/pdfinfo"),
                patch("ocr.subprocess.run", side_effect=subprocess.CalledProcessError(1, "pdfinfo")),
            ):
                with self.assertRaises(OcrError):
                    probe_page_sizes_with_pdfinfo(self._pdf(tmp))
            with patch("ocr.shutil.which", return_value=None):
                with self.assertRaises(OcrError):
                    probe_page_sizes_with_pdfinfo(self._pdf(tmp))

    def test_page_count_above_cap_is_refused_before_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            render = MagicMock()
            with (
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.render_pdf_page_to_png", render),
            ):
                with self.assertRaisesRegex(OcrError, "limited to"):
                    extract_scanned_pdf(self._pdf(tmp), use_cache=False, page_sizes=[(612.0, 792.0)] * (MAX_OCR_PAGES + 1))
            render.assert_not_called()

    def test_oversized_page_renders_at_reduced_dpi(self):
        self.assertEqual(effective_dpi((612.0, 792.0), 150), 150)
        huge = (14_400.0, 14_400.0)  # 200 x 200 inches
        reduced = effective_dpi(huge, 150)
        self.assertLess(reduced, 150)
        self.assertLessEqual((200 * reduced) ** 2, ocr.MAX_RENDER_PIXELS)

    def test_time_budget_stops_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("ocr.is_tesseract_available", return_value=True),
                patch("ocr.MAX_OCR_SECONDS", 0),
                patch("ocr.render_pdf_page_to_png") as render,
            ):
                with self.assertRaisesRegex(OcrError, "OCR stopped"):
                    extract_scanned_pdf(self._pdf(tmp), use_cache=False, page_sizes=[(612.0, 792.0)])
            render.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_cache_dir_is_private_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cache"
            with patch.dict(os.environ, {"SONARA_OCR_CACHE_DIR": str(target)}):
                cache = get_ocr_cache_dir()
            self.assertEqual(stat.S_IMODE(os.stat(cache).st_mode), 0o700)

            link = Path(tmp) / "link"
            link.symlink_to(target)
            with patch.dict(os.environ, {"SONARA_OCR_CACHE_DIR": str(link)}):
                with self.assertRaises(OcrError):
                    get_ocr_cache_dir()

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_symlinked_cache_entry_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "planted.tsv"
            planted.write_text("attacker text", encoding="utf-8")
            entry = Path(tmp) / "entry.tsv"
            entry.symlink_to(planted)
            self.assertIsNone(ocr._read_cache_entry(entry))
            ocr._write_cache_entry(Path(tmp) / "real.tsv", "ok")
            self.assertEqual(ocr._read_cache_entry(Path(tmp) / "real.tsv"), "ok")
            self.assertEqual(stat.S_IMODE(os.stat(Path(tmp) / "real.tsv").st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
