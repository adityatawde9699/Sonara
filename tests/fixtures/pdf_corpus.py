"""Self-authored PDF extraction corpus with explicit expected content/order."""

from __future__ import annotations

from pathlib import Path

from fixtures.pdf_fixture import EXPECTED_TEXT, make_corpus_pdf, make_pdf


CORPUS = {
    "one_column": {
        "description": "Three paragraphs with punctuation, numbers, and paragraph gaps.",
        "expected_text": EXPECTED_TEXT,
        "page_count": 1,
    },
    "two_columns": {
        "description": "Two columns with same-baseline text regions; order must be explicit and flagged for review.",
        "expected_text": "LEFT-FIRST\n\nRIGHT-FIRST\n\nLEFT-SECOND\n\nRIGHT-SECOND",
        "page_count": 1,
        "notes": {"side_by_side_reading_order_uncertain"},
    },
    "structure": {
        "description": "Large heading, numbered list, simple aligned table, and bottom-page footnote.",
        "expected_text": "Study Notes\n\nA short introduction to this section.\n\n1. First listed point.\n\n2. Second listed point.\n\nName\n\nValue\n\nAda\n\n42\n\nGrace\n\n37\n\n1. Source note for the table.",
        "page_count": 1,
        "notes": {"side_by_side_reading_order_uncertain"},
        "kinds": {"heading", "list_item"},
    },
    "line_hyphenation": {
        "description": "A line-end hyphen is preserved and identified rather than silently joined.",
        "expected_text": "The inter-\nnational example follows.",
        "page_count": 1,
        "notes": {"possible_line_end_hyphenation"},
    },
    "mixed_text_and_image": {
        "description": "Selectable text on page one and a raster-only page two.",
        "expected_text": "Page one has searchable text.",
        "page_count": 2,
        "notes": {"page_without_selectable_text"},
    },
    "repeated_passage": {
        "description": "Two identical passages remain present and produce a duplicate warning.",
        "expected_text": "Repeated source paragraph.\n\nRepeated source paragraph.",
        "page_count": 1,
        "notes": {"possible_duplicate_text"},
    },
}


def generate_corpus(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {name: directory / f"{name}.pdf" for name in CORPUS}
    make_pdf(paths["one_column"])
    make_corpus_pdf(
        paths["two_columns"],
        [[
            (72, 730, 12, "F1", "LEFT-FIRST"),
            (72, 700, 12, "F1", "LEFT-SECOND"),
            (330, 730, 12, "F1", "RIGHT-FIRST"),
            (330, 700, 12, "F1", "RIGHT-SECOND"),
        ]],
    )
    make_corpus_pdf(
        paths["structure"],
        [[
            (72, 740, 18, "F2", "Study Notes"),
            (72, 708, 12, "F1", "A short introduction to this section."),
            (72, 678, 12, "F1", "1. First listed point."),
            (72, 654, 12, "F1", "2. Second listed point."),
            (72, 620, 12, "F2", "Name"),
            (300, 620, 12, "F2", "Value"),
            (72, 600, 12, "F1", "Ada"),
            (300, 600, 12, "F1", "42"),
            (72, 580, 12, "F1", "Grace"),
            (300, 580, 12, "F1", "37"),
            (72, 80, 8, "F1", "1. Source note for the table."),
        ]],
    )
    make_corpus_pdf(
        paths["line_hyphenation"],
        [[
            (72, 720, 12, "F1", "The inter-"),
            (72, 704, 12, "F1", "national example follows."),
        ]],
    )
    make_corpus_pdf(
        paths["mixed_text_and_image"],
        [[(72, 720, 12, "F1", "Page one has searchable text.")], []],
        image_pages={2},
    )
    make_corpus_pdf(
        paths["repeated_passage"],
        [[
            (72, 720, 12, "F1", "Repeated source paragraph."),
            (72, 680, 12, "F1", "Repeated source paragraph."),
        ]],
    )
    return paths


def write_malformed_pdf(path: Path) -> Path:
    path.write_bytes(b"not a valid PDF")
    return path
