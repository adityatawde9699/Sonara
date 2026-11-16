import json
import unittest

from document import Document, DocumentBlock, SourceBox
from narration import NarrationError, PronunciationOverride, build_narration_plan, voice_profile


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
    def test_sentences_stay_together_in_a_natural_paragraph_passage(self):
        original = "Dr. Ada measures 3.14 cm. She cites e.g. a study. It works!"
        document = make_document(("paragraph", "poppler_block", original))
        plan = build_narration_plan(document)
        self.assertEqual(len(plan.units), 1)
        self.assertEqual(plan.units[0].spoken_text,
            "Doctor Ada measures three point one four centimeters. She cites for example a study. It works!")
        self.assertEqual("".join(unit.source_text for unit in plan.units), original)
        # A pause belongs after the paragraph, not each sentence.
        self.assertEqual(plan.units[0].pause_after_ms, 520)

    def test_long_single_paragraph_plans_in_linear_time(self):
        # The abbreviation check used to rescan the text before every period,
        # so an 80 KB paragraph took about 20 s. It should take well under 1 s now.
        import time
        from narration import _MAX_PASSAGE_CHARS
        original = "Dr. Ada said hi. " * 12_000  # about 200 KB in one block
        started = time.perf_counter()
        plan = build_narration_plan(make_document(("paragraph", "txt_paragraph", original)))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 10.0)
        self.assertEqual("".join(unit.source_text for unit in plan.units), original)
        self.assertTrue(all(len(unit.source_text) <= _MAX_PASSAGE_CHARS for unit in plan.units))

    def test_question_ellipsis_and_closing_quote_boundaries(self):
        text = '“Ready?” she asked. Wait… Then go!'
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual(len(plan.units), 1)
        self.assertEqual(plan.units[0].spoken_text, '“Ready?” she asked. Wait… Then go!')
        self.assertEqual(plan.units[0].content_type, "dialogue_candidate")
        self.assertEqual(plan.units[0].pause_after_ms, 460)

    def test_heading_remains_one_unit_and_list_marker_is_not_a_sentence(self):
        document = make_document(
            ("heading", "relative_line_height", "Chapter 1. A long title."),
            ("list_item", "text_marker", "1. First point. Second point."),
        )
        plan = build_narration_plan(document)
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "Chapter 1. A long title.",
            "1. First point. Second point.",
        ])
        self.assertEqual(plan.units[0].content_type, "heading")
        self.assertEqual(plan.units[0].pause_after_ms, 720)
        self.assertEqual(plan.units[1].content_type, "list_item")
        self.assertEqual(plan.units[1].pause_after_ms, 380)

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
            "A short paragraph. inter-\nnational study.",
        ])
        self.assertEqual("".join(unit.source_text for unit in plan.units), text)
        self.assertEqual(block.text, text)
        self.assertIn("line_end_hyphenation_preserved", {note.code for note in plan.notes})

    def test_urls_and_emails_do_not_split_at_internal_periods(self):
        text = "Visit https://example.com/docs. Email reader@example.org. Done."
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "Visit https://example.com/docs. Email reader@example.org. Done.",
        ])

    def test_unicode_multilingual_and_additional_abbreviations_preserve_coverage(self):
        text = "At 3 p.m., Dr. Li meets in the U.S. Café. Bonjour — 你好！"
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)))
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "At 3 p.m., Doctor Li meets in the U.S. Café. Bonjour — 你好！",
        ])
        self.assertEqual("".join(unit.source_text for unit in plan.units), text)

    def test_multiple_blocks_preserve_order_and_full_source_coverage(self):
        document = make_document(
            ("paragraph", "poppler_block", "First block. Another sentence."),
            ("footnote", "bottom_page_position_and_number_marker", "1. Footnote text."),
        )
        plan = build_narration_plan(document)
        self.assertEqual([unit.order for unit in plan.units], list(range(2)))
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

    def test_long_paragraph_is_split_at_safe_boundaries_without_losing_source_text(self):
        sentences = [f"Sentence {index} carries enough words to make this a realistic spoken passage." for index in range(36)]
        original = " ".join(sentences)
        document = make_document(("paragraph", "poppler_block", original))
        units = build_narration_plan(document).units
        self.assertGreater(len(units), 1)
        self.assertEqual("".join(unit.source_text for unit in units), original)
        self.assertTrue(all(len(unit.source_text.split()) <= 180 for unit in units))
        self.assertTrue(all(unit.source_text.rstrip().endswith(".") for unit in units[:-1]))


class PronunciationOverrideTests(unittest.TestCase):
    def test_override_changes_only_spoken_layer_and_records_reversible_source_spans(self):
        original = "CRISPR can help. CRISPR remains source text."
        document = make_document(("paragraph", "poppler_block", original))
        override = PronunciationOverride("crispr", "CRISPR", "crisper")
        plan = build_narration_plan(document, [override])
        self.assertEqual([unit.spoken_text for unit in plan.units], [
            "crisper can help. crisper remains source text.",
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

    def test_override_can_span_sentences_but_not_source_block_boundaries(self):
        document = make_document(("paragraph", "poppler_block", "Read Sonara. Then continue."))
        plan = build_narration_plan(document, [PronunciationOverride("cross", "Sonara. Then", "changed")])
        self.assertEqual(plan.units[0].spoken_text, "Read changed continue.")
        two_blocks = make_document(
            ("paragraph", "poppler_block", "Read Sonara."),
            ("paragraph", "poppler_block", "Then continue."),
        )
        with self.assertRaisesRegex(NarrationError, "did not match source text"):
            build_narration_plan(
                two_blocks,
                [PronunciationOverride("cross-block", "Sonara. Then", "changed")],
            )


def spoken(text, **kwargs):
    plan = build_narration_plan(make_document(("paragraph", "poppler_block", text)), **kwargs)
    return " ".join(unit.spoken_text for unit in plan.units)


class TableRowTests(unittest.TestCase):
    def test_cells_are_read_with_short_pauses_and_separator_rows_do_not_fail(self):
        document = make_document(
            ("paragraph", "docx_table_row", "Name | Score"),
            ("paragraph", "docx_table_row", "| | |"),
        )
        plan = build_narration_plan(document)
        self.assertEqual([unit.spoken_text for unit in plan.units], ["Name; Score", "| | |"])
        self.assertEqual({unit.content_type for unit in plan.units}, {"table_row"})


class MarkdownSpokenTextTests(unittest.TestCase):
    def _plan(self, *blocks, extractor="Native Markdown reader"):
        document = make_document(*blocks)
        return build_narration_plan(Document(**{**document.__dict__, "extractor": extractor}))

    def test_markup_is_removed_from_spoken_text_only(self):
        source = "Use **bold**, `code` and [the docs](https://example.com) with **Dr. Smith**."
        plan = self._plan(("heading", "txt_markdown_heading", "## Results ##"), ("paragraph", "txt_paragraph", source))
        self.assertEqual([unit.spoken_text for unit in plan.units],
                         ["Results.", "Use bold, code and the docs with Doctor Smith."])
        self.assertEqual(plan.units[1].source_text, source)
        self.assertIn("auto:markdown:link", {change.override_id for change in plan.units[1].applied_overrides})

    def test_a_rule_line_keeps_a_silent_unit_and_plain_text_is_untouched(self):
        plan = self._plan(("paragraph", "txt_paragraph", "---"), ("paragraph", "txt_paragraph", "snake_case and 2*3*4."))
        self.assertEqual([unit.spoken_text for unit in plan.units], ["—", "snake_case and 2*3*4."])
        txt = self._plan(("paragraph", "txt_paragraph", "Keep **stars** in .txt"), extractor="Native TXT reader")
        self.assertEqual(txt.units[0].spoken_text, "Keep **stars** in .txt")


class SpokenNormalizationTests(unittest.TestCase):
    """Each case is a reading the bundled espeak-ng front end gets wrong without the rule."""

    def assertSpoken(self, cases):
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(spoken(source), expected)

    def test_abbreviations_lose_the_period_that_would_split_a_sentence(self):
        self.assertSpoken([
            ("Dr. Smith met Mr. Jones.", "Doctor Smith met Mister Jones."),
            ("He lives on Main St. in St. Louis.", "He lives on Main Street in Saint Louis."),
            ("She lived on Elm St. Then she left.", "She lived on Elm Street. Then she left."),
            ("See Fig. 3, Eq. (2) and pp. 10-12.", "See Figure 3, Equation (2) and pages 10 to 12."),
            ("Read p. 4 of Vol. 2, No. 5.", "Read page 4 of Volume 2, Number 5."),
            ("Smith et al. (2020) agree.", "Smith et al (twenty twenty) agree."),
            ("Apples, pears, etc. Then more.", "Apples, pears, and so on. Then more."),
            ("Ask John Smith Jr. about it.", "Ask John Smith Junior about it."),
            ("Compare cf. the result, viz. this.", "Compare compare the result, namely this."),
        ])

    def test_ambiguous_units_and_decades_are_not_misread(self):
        self.assertSpoken([
            ("Ranked 3 in the world.", "Ranked 3 in the world."),
            ("A 12in pipe and 5 s.", "A twelve inches pipe and five seconds."),
            ("The 1990s and the 80s.", "The nineteen nineties and the eighties."),
            ("In the mid-60s and '70s.", "In the mid-sixties and seventies."),
        ])

    def test_years_are_read_as_years_only_in_context(self):
        self.assertSpoken([
            ("In 1905 and since 1800.", "In nineteen oh five and since eighteen hundred."),
            ("It ended by 2024.", "It ended by twenty twenty-four."),
            ("From 1990–1995 it grew.", "From nineteen ninety to nineteen ninety-five it grew."),
            ("Between 1990 and 2010.", "Between nineteen ninety and twenty ten."),
            ("Built c. 1500.", "Built circa fifteen hundred."),
            # A count, not a year: left for the voice.
            ("We used 1500 samples, in 1500 trials.", "We used 1500 samples, in 1500 trials."),
            ("On January 5, 2024 and 5 March 2021.",
             "On January fifth, twenty twenty-four and the fifth of March, twenty twenty-one."),
        ])

    def test_money_times_ranges_fractions_and_symbols(self):
        self.assertSpoken([
            ("It cost $5.99 or $1.2 million.", "It cost five dollars and ninety-nine cents or one point two million dollars."),
            ("Pay €30, £4.50 or $0.99.", "Pay thirty euros, four pounds and fifty pence or ninety-nine cents."),
            ("Meet at 10:05 am or 3:00 p.m. today.", "Meet at ten oh five AM or three PM today."),
            ("Arrive at 14:30.", "Arrive at fourteen thirty."),
            ("A 3:2 win.", "A 3:2 win."),
            ("Pages 10–20; call 555-1234.", "Pages 10 to 20; call 555-1234."),
            ("Add 1/2 cup, then 2 3/4 cups.", "Add one half cup, then two and three quarters cups."),
            ("Born 1/2/2024, scored 10/10.", "Born 1/2/2024, scored 10/10."),
            ("About ~5 km, the #1 hit, 4x faster at 1920x1080.",
             "About about five kilometers, the number 1 hit, 4 times faster at 1920 by 1080."),
            ("Version 2.10.3 or v2.1.", "Version two point ten point three or version two point one."),
        ])

    def test_roman_numerals_after_counting_words_and_regnal_names(self):
        self.assertSpoken([
            ("Chapter IV and World War II.", "Chapter four and World War two."),
            ("Henry VIII and Elizabeth I.", "Henry the eighth and Elizabeth the first."),
            ("In Part I describe it.", "In Part I describe it."),
            ("Call Chapter VIIII.", "Call Chapter VIIII."),
        ])

    def test_lexicon_terms_are_whole_word_and_case_sensitive(self):
        self.assertSpoken([
            ("Use LaTeX on x86_64 with the CLI.", "Use lay tek on x eighty-six sixty-four with the C L I."),
            ("Two IDEs and an IDE.", "Two I D Es and an I D E."),
            ("A latex glove and a client.", "A latex glove and a client."),
        ])

    def test_normalization_is_recorded_against_source_text(self):
        plan = build_narration_plan(make_document(("paragraph", "poppler_block", "Dr. Li paid $5.99.")))
        changes = {change.matched_source_text: change for change in plan.units[0].applied_overrides}
        self.assertEqual(set(changes), {"Dr.", "$5.99"})
        self.assertEqual(changes["$5.99"].override_id, "auto:en_us:number.currency")
        self.assertEqual(plan.units[0].source_text, "Dr. Li paid $5.99.")

    def test_user_overrides_still_win_over_the_lexicon(self):
        override = PronunciationOverride("latex", "LaTeX", "lah tech", case_sensitive=True)
        self.assertEqual(spoken("Use LaTeX.", pronunciation_overrides=[override]), "Use lah tech.")

    def test_other_languages_are_not_rewritten(self):
        self.assertEqual(spoken("Dr. Smith paid $5.99.", language="de_DE"), "Dr. Smith paid $5.99.")


class VoiceProfileTests(unittest.TestCase):
    def test_slower_voices_get_proportionally_longer_pauses(self):
        document = make_document(("heading", "poppler_block", "Results"), ("paragraph", "poppler_block", "It works."))
        ryan = build_narration_plan(document, voice="en_US-ryan-medium")
        john = build_narration_plan(document, voice="en_US-john-medium")
        unknown = build_narration_plan(document, voice="en_US-amy-low")
        self.assertEqual([unit.pause_after_ms for unit in ryan.units], [720, 520])
        self.assertEqual([unit.pause_after_ms for unit in john.units], [828, 598])
        self.assertEqual([unit.pause_after_ms for unit in unknown.units], [720, 520])

    def test_profiles_define_variation_presets_within_piper_range(self):
        for name in ("en_US-ryan-medium", "en_US-lessac-medium", "en_US-bryce-medium", "en_US-john-medium"):
            profile = voice_profile(name)
            self.assertIsNone(profile.noise_scales("voice_default"))
            less, more = profile.noise_scales("less"), profile.noise_scales("more")
            for values in (less, more):
                self.assertTrue(all(0 <= value <= 1 for value in values))
            self.assertLess(less[1], more[1])
        # john's timing is unstable at high noise_w, so its "more" stays lower.
        self.assertLess(voice_profile("en_US-john-medium").more[1], voice_profile("en_US-ryan-medium").more[1])
        self.assertIsNone(voice_profile("unknown").noise_scales("more"))


if __name__ == "__main__":
    unittest.main()


class MultilingualSegmentationTests(unittest.TestCase):
    def test_chinese_sentences_split_without_spaces_and_passages_stay_short(self):
        text = "火车早上九点出发，乘客在车站等候。" * 60
        plan = build_narration_plan(make_document(("paragraph", "test", text)), language="zh_CN")
        self.assertGreater(len(plan.units), 4)
        # Each passage ends at a full stop and stays near the 180-word bound.
        self.assertTrue(all(unit.source_text.endswith("。") for unit in plan.units))
        self.assertTrue(all(len(unit.source_text) <= 200 for unit in plan.units))
        self.assertEqual("".join(unit.source_text for unit in plan.units), text)

    def test_hindi_danda_ends_a_sentence(self):
        sentence = "ट्रेन सुबह नौ बजे निकलती है और यात्री इंतजार करते हैं। "
        plan = build_narration_plan(make_document(("paragraph", "test", (sentence * 60).strip())), language="hi_IN")
        self.assertTrue(all(unit.source_text.rstrip().endswith("।") for unit in plan.units))

    def test_english_rules_do_not_rewrite_other_languages(self):
        text = "Le 3 mai, il faisait 20 °C. Voir [3]."
        plan = build_narration_plan(
            make_document(("paragraph", "test", text)), language="fr_FR", expand_dates=True, expand_citations=True,
        )
        self.assertEqual(plan.units[0].spoken_text, text)
