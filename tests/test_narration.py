import json
import unittest

from document import Document, DocumentBlock, SourceBox
from narration import NarrationError, PronunciationOverride, build_narration_plan


def make_document(*blocks):
    return Document(
        schema_version=1,
        source_name="narration-fixture.pdf",
        source_sha256="a" * 64,
        extractor="unit-test",
        extractor_version="1",
        page_count=1,
        blocks=tuple(
            DocumentBlock(
                id=f"block-{index}",
                kind=kind,
                kind_source=kind_source,
                order=index,
                text=text,
                source=SourceBox(1, 612, 792, 72, 72 + index * 20, 500, 90 + index * 20),
            )
            for index, (kind, kind_source, text) in enumerate(blocks)
        ),
        notes=(),
    )


class NarrationSegmentationTests(unittest.TestCase):
    def test_sentence_spans_cover_original_text_and_handle_abbreviations_decimals(self):
        original = "Dr. Ada measures 3.14 cm. She cites e.g. a study. It works!"
        document = make_document(("paragraph", "poppler_block", original))
        plan = build_narration_plan(document)
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "Dr. Ada measures three point one four centimeters.",
            "She cites for example a study.",
            "It works!",
        ])
        self.assertEqual("".join(unit.source_text for unit in plan.units), original)
        self.assertEqual(plan.units[0].pause_after_ms, 300)
        # End-of-paragraph spacing takes precedence over the terminal mark.
        self.assertEqual(plan.units[-1].pause_after_ms, 520)

    def test_question_ellipsis_and_closing_quote_boundaries(self):
        text = '“Ready?” she asked. Wait… Then go!'
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            '“Ready?” she asked.',
            "Wait…",
            "Then go!",
        ])
        self.assertEqual(plan.units[0].content_type, "dialogue_candidate")
        self.assertEqual(plan.units[1].pause_after_ms, 520)

    def test_heading_remains_one_unit_and_list_marker_is_not_a_sentence(self):
        document = make_document(
            ("heading", "relative_line_height", "Chapter 1. A long title."),
            ("list_item", "text_marker", "1. First point. Second point."),
        )
        plan = build_narration_plan(document)
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "Chapter 1. A long title.",
            "1. First point.",
            "Second point.",
        ])
        self.assertEqual(plan.units[0].content_type, "heading")
        self.assertEqual(plan.units[0].pause_after_ms, 720)
        self.assertEqual(plan.units[1].content_type, "list_item")
        self.assertEqual(plan.units[1].pause_after_ms, 300)

    def test_quote_and_speaker_labels_are_hints_not_voice_assignments(self):
        document = make_document(
            ("quote", "quote_delimiters", "“A quoted passage.”"),
            ("paragraph", "poppler_block", "Ada: We should begin."),
        )
        plan = build_narration_plan(document)
        self.assertEqual(plan.units[0].content_type, "quotation")
        self.assertEqual(plan.units[1].content_type, "dialogue_candidate")
        self.assertIn("finite abbreviation list", plan.notes[0].message)

    def test_safe_whitespace_normalization_preserves_source_and_hyphenation(self):
        text = "A\tshort paragraph.\n\ninter-\nnational study.  "
        block = make_document(("paragraph", "poppler_block", text)).blocks[0]
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "A short paragraph.",
            "inter-\nnational study.",
        ])
        self.assertEqual("".join(unit.source_text for unit in plan.units), text)
        self.assertEqual(block.text, text)
        self.assertIn("line_end_hyphenation_preserved", {note.code for note in plan.notes})

    def test_urls_and_emails_do_not_split_at_internal_periods(self):
        text = "Visit https://example.com/docs. Email reader@example.org. Done."
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "Visit https://example.com/docs.",
            "Email reader@example.org.",
            "Done.",
        ])

    def test_unicode_multilingual_and_additional_abbreviations_preserve_coverage(self):
        text = "At 3 p.m., Dr. Li meets in the U.S. Café. Bonjour — 你好！"
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "At 3 p.m., Dr. Li meets in the U.S. Café.",
            "Bonjour — 你好！",
        ])
        self.assertEqual("".join(unit.source_text for unit in plan.units), text)

    def test_multiple_blocks_preserve_order_and_full_source_coverage(self):
        document = make_document(
            ("paragraph", "poppler_block", "First block. Another sentence."),
            ("footnote", "bottom_page_position_and_number_marker", "1. Footnote text."),
        )
        plan = build_narration_plan(document)
        self.assertEqual([unit.order for unit in plan.units], list(range(3)))
        for block in document.blocks:
            block_units = [unit for unit in plan.units if unit.source_block_id == block.id]
            self.assertEqual("".join(unit.source_text for unit in block_units), block.text)
            cursor = 0
            for unit in block_units:
                self.assertEqual(unit.source_start, cursor)
                self.assertEqual(block.text[unit.source_start:unit.source_end], unit.source_text)
                cursor = unit.source_end
            self.assertEqual(cursor, len(block.text))

    def test_boundary_case_corpus_always_covers_each_source_character_once(self):
        fragments = [
            "Alpha.", "Dr. B.", "3.14?", "Wait…", "Yes!", "e.g. item",
            "https://example.org/a.b", "你好。", "“quoted!” she said.", "tail",
        ]
        for index in range(1, len(fragments) + 1):
            text = "  ".join(fragments[:index])
            with self.subTest(text=text):
                document = make_document(("paragraph", "poppler_block", text))
                block = document.blocks[0]
                units = build_narration_plan(document).units
                self.assertEqual("".join(unit.source_text for unit in units), block.text)
                expected_start = 0
                for unit in units:
                    self.assertEqual(unit.source_start, expected_start)
                    self.assertEqual(unit.source_text, block.text[unit.source_start:unit.source_end])
                    expected_start = unit.source_end
                self.assertEqual(expected_start, len(block.text))


class PronunciationOverrideTests(unittest.TestCase):
    def test_override_changes_only_spoken_layer_and_records_reversible_source_spans(self):
        original = "CRISPR can help. CRISPR remains source text."
        document = make_document(("paragraph", "poppler_block", original))
        override = PronunciationOverride("crispr", "CRISPR", "crisper")
        plan = build_narration_plan(document, [override])
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "crisper can help.",
            "crisper remains source text.",
        ])
        applications = [application for unit in plan.units for application in unit.applied_overrides]
        self.assertEqual(len(applications), 2)
        for application in applications:
            self.assertEqual(original[application.source_start:application.source_end], application.matched_source_text)
            self.assertEqual(application.source_term, "CRISPR")
            self.assertEqual(application.replacement, "crisper")
        self.assertEqual(document.blocks[0].text, original)
        self.assertEqual("".join(unit.source_text for unit in plan.units), original)
        self.assertEqual(json.loads(plan.to_json())["schema_version"], 1)

    def test_english_abbreviations_and_measurements_only_change_spoken_text(self):
        original = "e.g. 3.5 km/h, 1 kg, and 22,050 Hz."
        document = make_document(("paragraph", "poppler_block", original))
        unit = build_narration_plan(document, language="en_US").units[0]
        self.assertEqual(
            unit.spoken_text,
            "for example three point five kilometers per hour, one kilogram, and twenty-two thousand fifty hertz.",
        )
        self.assertEqual(unit.source_text, original)
        self.assertEqual(document.blocks[0].text, original)
        for change in unit.applied_overrides:
            self.assertEqual(original[change.source_start:change.source_end], change.matched_source_text)

    def test_ambiguous_date_and_numeric_citation_rules_are_opt_in_and_reversible(self):
        original = "Published 2026-10-27; see [12, 14]."
        document = make_document(("paragraph", "poppler_block", original))
        unchanged = build_narration_plan(document, language="en_US")
        self.assertEqual(unchanged.units[0].spoken_text, original)

        expanded = build_narration_plan(
            document,
            language="en_US",
            expand_dates=True,
            expand_citations=True,
        )
        unit = expanded.units[0]
        self.assertEqual(
            unit.spoken_text,
            "Published October twenty-seventh, twenty twenty-six; see references twelve and fourteen.",
        )
        self.assertEqual(unit.source_text, original)
        self.assertEqual(len(unit.applied_overrides), 2)
        for change in unit.applied_overrides:
            self.assertEqual(original[change.source_start:change.source_end], change.matched_source_text)

    def test_unavailable_language_does_not_apply_english_rules(self):
        original = "e.g. 5 km."
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", original)), language="de_DE")
        self.assertEqual(plan.units[0].spoken_text, original)

    def test_override_word_boundaries_and_case_sensitivity(self):
        text = "art and partial ART."
        document = make_document(("paragraph", "poppler_block", text))
        sensitive = build_narration_plan(
            document,
            [PronunciationOverride("case", "art", "articulated", case_sensitive=True)],
        )
        self.assertEqual(sensitive.units[0].spoken_text, "articulated and partial ART.")
        insensitive = build_narration_plan(
            document,
            [PronunciationOverride("ignore-case", "art", "articulated")],
        )
        self.assertEqual(insensitive.units[0].spoken_text, "articulated and partial articulated.")

    def test_unmatched_override_is_an_actionable_error(self):
        document = make_document(("paragraph", "poppler_block", "No matching term here."))
        with self.assertRaisesRegex(NarrationError, "did not match source text"):
            build_narration_plan(document, [PronunciationOverride("unknown", "SonaraTerm", "spoken")])

    def test_overlapping_overrides_are_rejected_instead_of_order_dependent(self):
        document = make_document(("paragraph", "poppler_block", "Interleukin 6 is discussed."))
        overrides = [
            PronunciationOverride("short", "Interleukin", "interleukin"),
            PronunciationOverride("long", "Interleukin 6", "interleukin six"),
        ]
        with self.assertRaisesRegex(NarrationError, "overlaps"):
            build_narration_plan(document, overrides)

    def test_duplicate_override_ids_or_terms_are_rejected(self):
        document = make_document(("paragraph", "poppler_block", "Read Sonara."))
        with self.assertRaisesRegex(NarrationError, "ids must be unique"):
            build_narration_plan(document, [
                PronunciationOverride("same", "Sonara", "so-nara"),
                PronunciationOverride("same", "reader", "reader"),
            ])
        with self.assertRaisesRegex(NarrationError, "same source phrase"):
            build_narration_plan(document, [
                PronunciationOverride("one", "Sonara", "so-nara"),
                PronunciationOverride("two", "sonara", "sona-ra"),
            ])

    def test_override_cannot_silently_span_sentence_or_block_boundary(self):
        document = make_document(("paragraph", "poppler_block", "Read Sonara. Then continue."))
        with self.assertRaisesRegex(NarrationError, "did not match source text"):
            build_narration_plan(document, [PronunciationOverride("cross", "Sonara. Then", "changed")])
        two_blocks = make_document(
            ("paragraph", "poppler_block", "Read Sonara."),
            ("paragraph", "poppler_block", "Then continue."),
        )
        with self.assertRaisesRegex(NarrationError, "did not match source text"):
            build_narration_plan(
                two_blocks,
                [PronunciationOverride("cross-block", "Sonara. Then", "changed")],
            )


if __name__ == "__main__":
    unittest.main()
