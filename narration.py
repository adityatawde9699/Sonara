"""Deterministic narration planning that never rewrites source document text."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from document import MARKDOWN_EXTRACTOR, Document, DocumentBlock, ExtractionNote


NARRATION_SCHEMA_VERSION = 1
NARRATION_RULESET_VERSION = "rules-7"

# Keep a natural paragraph together for narration, but bound synthesis latency
# and memory for unusually large blocks (common in PDF extraction).
_MAX_PASSAGE_CHARS = 1_200
_MAX_PASSAGE_WORDS = 180

_ABBREVIATIONS = {
    "approx", "capt", "cmdr", "dept", "dr", "e.g", "eq", "etc", "fig", "gen",
    "i.e", "inc", "jr", "lt", "mr", "mrs", "ms", "no", "ph.d", "prof", "ref",
    "rev", "sen", "sr", "st", "vs", "u.k", "u.s", "a.m", "p.m",
}
_CLOSERS = "\"'’”)]}»"
_DIALOGUE_ATTRIBUTION = re.compile(
    r"[\"“‘].+?[\"”’]\s*[,—-]?\s*"
    r"(?:[A-Za-z]+\s+)?(?:said|says|asked|asks|replied|replies|whispered|shouted|answered|continued)\b",
    re.IGNORECASE,
)
_SPEAKER_LABEL = re.compile(r"^[A-Z][\w .'-]{0,32}:\s+")
_URL_OR_EMAIL = re.compile(
    r"(?:\b(?:https?://|www\.)\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VoiceProfile:
    """Per-voice narration timing and Piper variation presets.

    Values come from synthesizing one fixed six-sentence passage with each
    bundled voice (see docs/BENCHMARKS.md, "Voice profiles"):

    - Tempo differs by about 35%: ryan and lessac speak about 3.3 words per
      second of speech, bryce and john about 2.45. Pauses scale with the square
      root of that ratio so slower voices get proportionally calmer gaps
      without stretching them as much as the speech itself.
    - Pitch contour did not change measurably with noise settings (semitone
      spread moved by under 0.2). The settings change rhythm and timbre:
      noise_w sets how much phoneme timing varies, noise_scale how much the
      waveform does. john's timing is already unstable at its default
      noise_w of 0.8 (run-to-run duration spread 0.4 to 0.7 s versus under
      0.2 s for the others), so its "more" stays lower and its "less" goes
      lower still.

    These presets are measured, not listener-validated; listening_eval.py can
    produce a blind comparison pack for that.
    """

    voice: str
    pause_scale: float = 1.0
    sentence_pause_ms: int = 200
    # (noise_scale, noise_w_scale) for each variation preset; None defers to
    # the worker's proportional default for voices without measurements.
    less: tuple[float, float] | None = None
    more: tuple[float, float] | None = None

    def noise_scales(self, variation: str) -> tuple[float, float] | None:
        if variation == "less":
            return self.less
        if variation == "more":
            return self.more
        return None


_VOICE_PROFILES = {
    profile.voice: profile
    for profile in (
        VoiceProfile("en_US-ryan-medium", 1.0, 200, less=(0.5, 0.5), more=(0.8, 1.0)),
        VoiceProfile("en_US-lessac-medium", 1.0, 200, less=(0.5, 0.5), more=(0.8, 1.0)),
        VoiceProfile("en_US-bryce-medium", 1.15, 230, less=(0.5, 0.5), more=(0.8, 1.0)),
        VoiceProfile("en_US-john-medium", 1.15, 230, less=(0.5, 0.4), more=(0.75, 0.85)),
    )
}


def voice_profile(voice: str | None) -> VoiceProfile:
    """Return the measured profile for a voice, or neutral timing for any other voice."""
    if voice and voice in _VOICE_PROFILES:
        return _VOICE_PROFILES[voice]
    return VoiceProfile(voice or "")


class NarrationError(ValueError):
    """An invalid or ambiguous narration instruction that needs user correction."""


@dataclass(frozen=True)
class PronunciationOverride:
    """A reversible source phrase -> spoken phrase substitution."""

    id: str
    source_text: str
    spoken_text: str
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("pronunciation override id must not be empty")
        if not _normalize_with_map(self.source_text)[0]:
            raise ValueError("pronunciation override source text must not be empty")
        if not _normalize_with_map(self.spoken_text)[0]:
            raise ValueError("pronunciation override spoken text must not be empty")


@dataclass(frozen=True)
class OverrideApplication:
    """Visible record of a spoken-only substitution and its original block span."""

    override_id: str
    source_term: str
    replacement: str
    matched_source_text: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class NarrationUnit:
    """One ordered spoken unit mapped to a contiguous source-block character span."""

    id: str
    order: int
    source_block_id: str
    source_start: int
    source_end: int
    source_text: str
    spoken_text: str
    content_type: str
    block_kind_source: str
    pause_after_ms: int
    applied_overrides: tuple[OverrideApplication, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.source_block_id:
            raise ValueError("narration units require stable unit and source block ids")
        if self.order < 0 or self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("narration unit order and source span are invalid")
        if len(self.source_text) != self.source_end - self.source_start:
            raise ValueError("narration unit source text must exactly match its exclusive-end span")
        if not self.spoken_text.strip():
            raise ValueError("narration unit spoken text must not be empty")
        if self.pause_after_ms < 0:
            raise ValueError("pause duration must not be negative")


@dataclass(frozen=True)
class NarrationNote:
    code: str
    message: str
    source_block_id: str | None = None


@dataclass(frozen=True)
class NarrationPlan:
    schema_version: int
    ruleset_version: str
    document_source_sha256: str
    units: tuple[NarrationUnit, ...]
    extraction_notes: tuple[ExtractionNote, ...]
    notes: tuple[NarrationNote, ...]

    def __post_init__(self) -> None:
        if self.schema_version != NARRATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported narration schema version: {self.schema_version}")
        if any(unit.order != index for index, unit in enumerate(self.units)):
            raise ValueError("narration unit order must be contiguous from zero")
        if len({unit.id for unit in self.units}) != len(self.units):
            raise ValueError("narration unit ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ruleset_version": self.ruleset_version,
            "document_source_sha256": self.document_source_sha256,
            "units": [asdict(unit) for unit in self.units],
            "extraction_notes": [asdict(note) for note in self.extraction_notes],
            "notes": [asdict(note) for note in self.notes],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def build_narration_plan(
    document: Document,
    pronunciation_overrides: Iterable[PronunciationOverride] = (),
    *,
    language: str = "en_US",
    expand_dates: bool = False,
    expand_citations: bool = False,
    voice: str | None = None,
) -> NarrationPlan:
    """Plan speech units with complete source coverage and separate spoken text.

    Source blocks are the primary passage boundary: sentences in a paragraph
    stay together so playback does not pause after every sentence. Very long
    blocks are split at sentence or whitespace boundaries. The supported
    abbreviation set is finite; URLs, equations, citations, code, and uncommon
    abbreviations may need review. No model rewrites or drops text.
    """
    overrides = tuple(pronunciation_overrides)
    _validate_overrides(overrides)
    pause_scale = voice_profile(voice).pause_scale
    markdown = document.extractor == MARKDOWN_EXTRACTOR
    units: list[NarrationUnit] = []
    notes: list[NarrationNote] = [NarrationNote(
        "deterministic_segmentation_scope",
        "Sentence boundaries use punctuation and a finite abbreviation list. Review equations, citations, code, URLs, and uncommon abbreviations.",
    )]
    matched_overrides: set[str] = set()

    for block in document.blocks:
        spans = _source_spans(block)
        if not spans:
            raise NarrationError(f"Source block {block.id} did not produce a narration span.")
        cursor = 0
        block_has_hyphenation = False
        for start, end in spans:
            if start != cursor or end <= start:
                raise NarrationError(f"Narration spans do not cover source block {block.id} contiguously.")
            source_text = block.text[start:end]
            spoken_base, source_offsets = _normalize_with_map(source_text)
            if not spoken_base:
                raise NarrationError(f"Source block {block.id} contains a whitespace-only narration span.")
            spoken_text, applications = _apply_spoken_changes(
                spoken_base,
                source_offsets,
                start,
                block,
                overrides,
                language=language,
                expand_dates=expand_dates,
                expand_citations=expand_citations,
                markdown=markdown,
            )
            # Piper does not accept SSML prosody. Keep semantic blocks as
            # separate synthesis units and use punctuation plus inter-unit
            # silence to give headings a distinct, complete cadence.
            content_type = _content_type(block, source_text.strip())
            if content_type == "heading" and spoken_text[-1:] not in ".!?…":
                spoken_text += "."
            elif content_type == "table_row":
                # Cell boundaries are meaningful when a table is spoken;
                # a short pause is clearer than reading a vertical bar.
                # A separator-only row ("| | |") keeps its text: it has no
                # phonemes, so the engine writes a short silent chunk and the
                # unit stays aligned with its source.
                spoken_text = re.sub(r"\s*\|\s*", "; ", spoken_text).strip(" ;") or spoken_text
            matched_overrides.update(application.override_id for application in applications)
            unit_id = _unit_id(block, start, end, source_text)
            units.append(NarrationUnit(
                id=unit_id,
                order=len(units),
                source_block_id=block.id,
                source_start=start,
                source_end=end,
                source_text=source_text,
                spoken_text=spoken_text,
                content_type=content_type,
                block_kind_source=block.kind_source,
                pause_after_ms=round(_pause_after(source_text, content_type, end == len(block.text)) * pause_scale),
                applied_overrides=tuple(applications),
            ))
            if re.search(r"[-‐‑]\s*\n\s*[a-z]", source_text):
                block_has_hyphenation = True
            cursor = end

        if cursor != len(block.text):
            raise NarrationError(f"Narration spans omitted source characters in block {block.id}.")
        if block_has_hyphenation:
            notes.append(NarrationNote(
                "line_end_hyphenation_preserved",
                "A line-end hyphen was retained in spoken text because joining or removing it could change the source word.",
                block.id,
            ))

    unmatched = [override.id for override in overrides if override.id not in matched_overrides]
    if unmatched:
        raise NarrationError(
            "Pronunciation override(s) did not match source text inside a narration unit: " + ", ".join(unmatched)
        )

    return NarrationPlan(
        schema_version=NARRATION_SCHEMA_VERSION,
        ruleset_version=NARRATION_RULESET_VERSION,
        document_source_sha256=document.source_sha256,
        units=tuple(units),
        extraction_notes=document.notes,
        notes=tuple(notes),
    )


# Latin, CJK full-width and Devanagari (danda, double danda) sentence ends.
_FULL_WIDTH_ENDS = frozenset("。！？")
_SENTENCE_ENDS = frozenset(".?!…") | _FULL_WIDTH_ENDS | frozenset("।॥")


def _source_spans(block: DocumentBlock) -> list[tuple[int, int]]:
    text = block.text
    if block.kind == "heading":
        return [(0, len(text))] if text else []

    list_marker = re.match(r"^\s*(?:\d{1,3}|[A-Za-z])[.)](?=\s)", text)
    protected_url_dots: set[int] = set()
    for match in _URL_OR_EMAIL.finditer(text):
        end = match.end()
        while end > match.start() and text[end - 1] in ".,!?;:)\u201d\u2019\u00bb":
            end -= 1
        protected_url_dots.update(index for index in range(match.start(), end) if text[index] == ".")

    boundaries: list[int] = []
    index = 0
    while index < len(text):
        if text[index] not in _SENTENCE_ENDS:
            index += 1
            continue
        if text[index] == ".":
            if index in protected_url_dots or _is_decimal_point(text, index):
                index += 1
                continue
            if list_marker and list_marker.start() <= index < list_marker.end():
                index += 1
                continue
            if _is_abbreviation_period(text, index):
                index += 1
                continue

        end = index + 1
        while end < len(text) and text[end] in _SENTENCE_ENDS:
            end += 1
        while end < len(text) and text[end] in _CLOSERS:
            end += 1
        # Chinese and Japanese put no space after a full stop, so a full-width
        # terminator ends a sentence on its own.
        if end == len(text) or text[end].isspace() or text[end - 1] in _FULL_WIDTH_ENDS or text[index] in _FULL_WIDTH_ENDS:
            next_text = end
            while next_text < len(text) and text[next_text].isspace():
                next_text += 1
            # A quote followed by a conventional speech attribution belongs
            # to the same spoken unit (for example, “Ready?” she asked.).
            if _is_dialogue_attribution(text, next_text):
                index = end
                continue
            end = next_text
            boundaries.append(end)
            index = end
        else:
            index = end

    spans: list[tuple[int, int]] = []
    start = 0
    for end in boundaries:
        if end > start:
            spans.append((start, end))
            start = end
    if start < len(text):
        spans.append((start, len(text)))
    if not spans and text:
        spans.append((0, len(text)))
    return _coalesce_passage_spans(text, spans)


def _coalesce_passage_spans(text: str, sentence_spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Join sentence spans into paragraph-sized passages with a safe upper bound."""
    if not sentence_spans:
        return []

    bounded: list[tuple[int, int]] = []
    for start, end in sentence_spans:
        cursor = start
        while end - cursor > _MAX_PASSAGE_CHARS or _spoken_word_count(text[cursor:end]) > _MAX_PASSAGE_WORDS:
            # Prefer a sentence boundary; for one exceptionally long sentence,
            # cut near the limit at whitespace without dropping any source text.
            limit = min(cursor + _MAX_PASSAGE_CHARS, end)
            word_limited = _word_limit_end(text, cursor, end, _MAX_PASSAGE_WORDS)
            limit = min(limit, word_limited)
            split = text.rfind(" ", cursor + 1, limit + 1)
            if split <= cursor:
                split = text.find(" ", limit, end)
            if split < 0 or split >= end:
                break
            bounded.append((cursor, split + 1))
            cursor = split + 1
        if cursor < end:
            bounded.append((cursor, end))

    passages: list[tuple[int, int]] = []
    current_start, current_end = bounded[0]
    for start, end in bounded[1:]:
        combined = text[current_start:end]
        if (len(combined) <= _MAX_PASSAGE_CHARS
                and _spoken_word_count(combined) <= _MAX_PASSAGE_WORDS):
            current_end = end
        else:
            passages.append((current_start, current_end))
            current_start, current_end = start, end
    passages.append((current_start, current_end))
    return passages


_WORD = re.compile(r"\S+")
# Han ideographs and kana: each is about one spoken syllable, so each counts
# as a word when bounding a passage. Without this a Chinese paragraph of
# 1,000 characters (several minutes of speech) would be a single passage.
_CJK_CHARACTER = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _spoken_word_count(text: str) -> int:
    return len(_CJK_CHARACTER.sub(" ", text).split()) + len(_CJK_CHARACTER.findall(text))


def _word_limit_end(text: str, start: int, end: int, max_words: int) -> int:
    # Stop at the limit instead of collecting every remaining word.
    for count, word in enumerate(_WORD.finditer(text, start, end), 1):
        if count == max_words:
            return end if _WORD.search(text, word.end(), end) is None else word.end()
    return end


_ATTRIBUTION_VERB = re.compile(
    r"(?:(?:he|she|they|i|we)\s+)?(?:said|says|asked|asks|replied|replies|whispered|shouted|answered|continued)\b",
    re.IGNORECASE,
)


def _is_dialogue_attribution(text: str, index: int) -> bool:
    # Match in place: slicing text[index:] here made sentence splitting quadratic.
    return index < len(text) and _ATTRIBUTION_VERB.match(text, index) is not None


def _is_decimal_point(text: str, index: int) -> bool:
    return index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit()


_ABBREVIATION_MAX_LEN = max(len(abbreviation) for abbreviation in _ABBREVIATIONS)
_ASCII_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _is_abbreviation_period(text: str, index: int) -> bool:
    """Return whether the period at ``index`` ends a known abbreviation.

    The token is the run of ASCII letters and dots just before the period,
    starting and ending with a letter. The scan is bounded by the longest
    abbreviation, so each period costs O(1) rather than O(len(text)).
    """
    if index == 0 or text[index - 1] not in _ASCII_LETTERS:
        return False
    first_letter = index - 1
    cursor = index - 1
    while cursor > 0 and (text[cursor - 1] in _ASCII_LETTERS or text[cursor - 1] == "."):
        cursor -= 1
        if text[cursor] != ".":
            # Leading dots are not part of the token; only letters extend it.
            if index - cursor > _ABBREVIATION_MAX_LEN:
                return False
            first_letter = cursor
    return text[first_letter:index].casefold() in _ABBREVIATIONS


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse safe whitespace while retaining offsets into the source string."""
    output: list[str] = []
    source_offsets: list[int] = []
    index = 0
    while index < len(text):
        char = text[index]
        if not char.isspace():
            output.append(char)
            source_offsets.append(index)
            index += 1
            continue

        end = index + 1
        while end < len(text) and text[end].isspace():
            end += 1
        if output and end < len(text):
            previous = output[-1]
            next_char = text[end]
            preserve_hyphen_break = (
                "\n" in text[index:end]
                and previous in "-‐‑"
                and next_char.islower()
            )
            output.append("\n" if preserve_hyphen_break else " ")
            source_offsets.append(index)
        index = end
    return "".join(output), source_offsets


def _validate_overrides(overrides: tuple[PronunciationOverride, ...]) -> None:
    ids = [override.id for override in overrides]
    if len(set(ids)) != len(ids):
        raise NarrationError("Pronunciation override ids must be unique.")
    normalized_terms = [_normalize_with_map(override.source_text)[0].casefold() for override in overrides]
    if len(set(normalized_terms)) != len(normalized_terms):
        raise NarrationError("Pronunciation overrides must not define the same source phrase more than once.")


def _apply_spoken_changes(
    spoken_base: str,
    source_offsets: list[int],
    unit_source_start: int,
    block: DocumentBlock,
    overrides: tuple[PronunciationOverride, ...],
    *,
    language: str,
    expand_dates: bool,
    expand_citations: bool,
    markdown: bool = False,
) -> tuple[str, list[OverrideApplication]]:
    explicit: list[tuple[int, int, str, str, str, str]] = []
    for override in overrides:
        term = _normalize_with_map(override.source_text)[0]
        flags = 0 if override.case_sensitive else re.IGNORECASE
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags)
        explicit.extend((match.start(), match.end(), override.id, override.source_text,
                         _normalize_with_map(override.spoken_text)[0], match.group())
                        for match in pattern.finditer(spoken_base))

    explicit.sort(key=lambda item: (item[0], item[1], item[2]))
    previous_end = -1
    for start, end, override_id, _, _, _ in explicit:
        if start < previous_end:
            raise NarrationError(
                f"Pronunciation override {override_id!r} overlaps another override in source block {block.id}."
            )
        previous_end = end

    explicit_spans = [(start, end) for start, end, *_ in explicit]
    automatic = _automatic_spoken_rules(
        spoken_base,
        language=language,
        expand_dates=expand_dates,
        expand_citations=expand_citations,
    )
    if markdown:
        automatic = sorted(automatic + _markdown_spoken_rules(spoken_base), key=lambda item: (item[0], -(item[1] - item[0])))
    candidates = explicit + [
        item for item in automatic
        if not any(item[0] < end and item[1] > start for start, end in explicit_spans)
    ]
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    matches: list[tuple[int, int, str, str, str, str]] = []
    for candidate in candidates:
        if matches and candidate[0] < matches[-1][1]:
            # User rules win collisions; otherwise prefer the longest automatic match.
            previous = matches[-1]
            candidate_is_explicit = not candidate[2].startswith("auto:")
            previous_is_explicit = not previous[2].startswith("auto:")
            if candidate_is_explicit and not previous_is_explicit:
                matches[-1] = candidate
            continue
        matches.append(candidate)

    output: list[str] = []
    applications: list[OverrideApplication] = []
    cursor = 0
    for match_start, match_end, rule_id, source_term, replacement, matched_text in matches:
        output.append(spoken_base[cursor:match_start])
        output.append(replacement)
        source_start = unit_source_start + source_offsets[match_start]
        source_end = unit_source_start + source_offsets[match_end - 1] + 1
        applications.append(OverrideApplication(
            override_id=rule_id,
            source_term=source_term,
            replacement=replacement,
            matched_source_text=block.text[source_start:source_end],
            source_start=source_start,
            source_end=source_end,
        ))
        cursor = match_end
    output.append(spoken_base[cursor:])
    spoken = "".join(output)
    if any(not application.replacement for application in applications):
        # Deleted markup can leave doubled or edge spaces; line breaks stay.
        spoken = re.sub(r"[ \t]{2,}", " ", spoken).strip(" \t")
    if not spoken:
        # Deleting markup left nothing to say (for example a lone "---" rule);
        # keep the text so the unit still maps to a short silent chunk.
        return spoken_base, []
    return spoken, applications


_MARKDOWN_MARKER_RULES = (
    # (rule id, pattern, group to delete or replace, replacement)
    ("heading", r"^#{1,6}[ \t]+", 0, ""),
    ("heading_closer", r"[ \t]+#+[ \t]*$", 0, ""),
    ("setext_underline", r"\s+(?:={3,}|-{3,})\s*$", 0, ""),
    ("list_marker", r"^[*+-][ \t]+", 0, ""),
    ("quote_marker", r"^>[ \t]?", 0, ""),
    ("horizontal_rule", r"^(?:[*_-][ \t]*){3,}$", 0, "—"),
)
_MARKDOWN_PAIRED = (
    # Emphasis and code: delete the delimiters, keep the words between them.
    ("strong", r"(?<![\w*])(\*\*)(?=\S)[^*\n]+?(?<=\S)(\*\*)(?![\w*])"),
    ("strong", r"(?<![\w_])(__)(?=\S)[^_\n]+?(?<=\S)(__)(?![\w_])"),
    ("emphasis", r"(?<![\w*])(\*)(?=[^\s*])[^*\n]+?(?<=[^\s*])(\*)(?![\w*])"),
    ("emphasis", r"(?<![\w_])(_)(?=[^\s_])[^_\n]+?(?<=[^\s_])(_)(?![\w_])"),
    ("code", r"(`+)(?=[^`\s])[^`\n]+?(?<=[^`\s])(\1)"),
)


def _markdown_spoken_rules(text: str) -> list[tuple[int, int, str, str, str, str]]:
    """Delete Markdown markup from spoken text; the source keeps it.

    Only markers are removed, so rules for the words inside ("**Dr. Smith**")
    still apply. A link is spoken as its text, an image as its alt text.
    """
    found: list[tuple[int, int, str, str, str, str]] = []

    def add(rule: str, start: int, end: int, value: str) -> None:
        matched = text[start:end]
        found.append((start, end, f"auto:markdown:{rule}", matched, value, matched))

    for rule, pattern, group, value in _MARKDOWN_MARKER_RULES:
        for match in re.finditer(pattern, text):
            add(rule, match.start(group), match.end(group), value)
    for rule, pattern in _MARKDOWN_PAIRED:
        for match in re.finditer(pattern, text):
            add(rule, match.start(1), match.end(1), "")
            add(rule, match.start(2), match.end(2), "")
    for match in re.finditer(r"(?P<bang>!?)(?P<open>\[)(?P<label>[^\]\n]*)(?P<close>\]\([^)\s]*(?:\s+\"[^\"]*\")?\))", text):
        rule = "image" if match.group("bang") else "link"
        add(rule, match.start(), match.end("open"), "")
        add(rule, match.start("close"), match.end("close"), "")
    return found


def _automatic_spoken_rules(
    text: str,
    *,
    language: str,
    expand_dates: bool,
    expand_citations: bool,
) -> list[tuple[int, int, str, str, str, str]]:
    """Return reversible English-only spoken substitutions with local source spans.

    Every rule fixes a reading the bundled espeak-ng front end gets wrong or
    splits badly: an abbreviation period left in spoken text makes Piper end a
    sentence (and insert a sentence pause) in the middle of "Dr. Smith".
    Rules that need context (years, ranges, times, Roman numerals) only fire
    in that context, so ambiguous numbers are left for the voice to read.
    """
    normalized_language = language.replace("-", "_").casefold()
    if normalized_language not in {"en_us", "en_gb", "en"}:
        return []
    found: list[tuple[int, int, str, str, str, str]] = []

    def add(rule_id: str, start: int, end: int, value: str | None) -> None:
        matched = text[start:end]
        if value and value != matched:
            found.append((start, end, f"auto:{normalized_language}:{rule_id}", matched, value, matched))

    def collect(rule_id: str, pattern: str, replacement, flags: int = re.IGNORECASE, *, group: int | str = 0) -> None:
        for match in re.finditer(pattern, text, flags):
            value = replacement(match)
            # Case-insensitive rules keep a capital (sentence start); case-sensitive
            # rules spell their replacement exactly.
            if value and flags & re.IGNORECASE and match.group(group)[:1].isupper() and value[:1].islower():
                value = value[:1].upper() + value[1:]
            add(rule_id, match.start(group), match.end(group), value)

    def sentence_final(match: re.Match[str], value: str) -> str:
        # The abbreviation period may also end the sentence; keep it then.
        following = text[match.end():]
        if not following.strip() or re.match(r"\s+[\"“‘(\[]?[A-Z]", following):
            return value + "."
        return value

    # Lexicon: whole-word, case-sensitive terms the voice front end misreads.
    for term, spoken in _LEXICON.items():
        collect(f"lexicon.{term}", rf"(?<![\w.-]){re.escape(term)}(?![\w-])", lambda _, spoken=spoken: spoken, 0)

    for token, spoken in (
        (r"e\.g\.", "for example"),
        (r"i\.e\.", "that is"),
        (r"vs\.", "versus"),
        (r"approx\.", "approximately"),
        (r"cf\.", "compare"),
        (r"viz\.", "namely"),
        (r"w\.r\.t\.", "with respect to"),
        (r"a\.k\.a\.", "also known as"),
    ):
        collect(f"abbreviation.{token.replace(chr(92), '').replace('.', '')}", rf"(?<!\w){token}(?!\w)",
                lambda _, spoken=spoken: spoken)
    for token, spoken in ((r"etc\.", "and so on"), (r"et al\.", "et al"), (r"resp\.", "respectively")):
        collect(f"abbreviation.{token.replace(chr(92), '').replace('.', '').replace(' ', '')}", rf"(?<!\w){token}(?!\w)",
                lambda match, spoken=spoken: sentence_final(match, spoken))
    collect("abbreviation.w/o", r"(?<!\w)w/o(?!\w)", lambda _: "without")
    collect("abbreviation.w/", r"(?<!\w)w/(?=\s)", lambda _: "with")
    collect("abbreviation.and/or", r"(?<!\w)and/or(?!\w)", lambda _: "and or")

    # Titles before a capitalized name; name suffixes after one.
    collect(
        "abbreviation.title",
        r"\b(?P<title>Dr|Mr|Mrs|Ms|Mx|Prof|Gen|Capt|Lt|Sgt|Col|Rev|Sen|Rep|Gov|Pres|Fr)\.(?=\s+[A-Z])",
        lambda match: _TITLES[match.group("title")], 0,
    )
    collect(
        "abbreviation.suffix",
        r"(?<=[a-z]\s)(?P<suffix>Jr|Sr)\.|(?<=[a-z],\s)(?P<suffix2>Jr|Sr)\.",
        lambda match: sentence_final(match, "Junior" if (match.group("suffix") or match.group("suffix2")) == "Jr" else "Senior"),
        0,
    )
    collect("abbreviation.saint_or_street", r"\bSt\.", lambda match: _saint_or_street(text, match), 0)

    # Reference abbreviations before a number: "Fig. 3", "pp. 10-12", "No. 5".
    collect(
        "abbreviation.reference",
        r"\b(?P<abbr>Figs?|Eqs?|Vols?|Nos?|Chs?|Chap|Secs?|Sect|Pts?|Refs?|Tabs?|App)\.(?=\s*\(?\d)",
        lambda match: _REFERENCE_ABBREVIATIONS[match.group("abbr").casefold()],
    )
    collect("abbreviation.pages", r"(?<!\w)pp\.(?=\s*\d)", lambda _: "pages", 0)
    collect("abbreviation.page", r"(?<!\w)p\.(?=\s*\d)", lambda _: "page", 0)
    collect("abbreviation.circa", r"(?<!\w)(?:ca|c)\.(?=\s*\d{3,4}\b)", lambda _: "circa", 0)

    # Dates written with a month name, then years and decades in context.
    collect("date.month", _MONTH_DATE, lambda match: _speak_month_date(match, normalized_language), 0)
    collect("date.day_month", _DAY_MONTH_DATE, _speak_day_month_date, 0)
    collect(
        "abbreviation.month",
        r"\b(?P<month>Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.(?=\s+\d)",
        lambda match: _month_name(match.group("month")), 0,
    )
    collect("number.year", _YEAR_IN_CONTEXT, lambda match: _speak_year_in_context(text, match))
    collect(
        "number.year_range",
        _YEAR_RANGE,
        lambda match: _speak_year_range(match.group("start"), match.group("dash"), match.group("end")),
    )
    collect(
        "number.year_citation",
        r"(?:(?<=\()|(?<=[,;] ))(?P<year>1[5-9]\d\d|20\d\d)(?P<suffix>[a-z])?(?=[),;])",
        _speak_citation_year,
        0,
    )
    collect(
        "number.decade",
        r"(?<![\w.,$€£¥])(?:(?P<prefix>the|early|late|mid|mid-|their|his|her|my|your|our)(?P<space>\s+|(?<=-)))?"
        r"(?P<decade>(?:1[1-9]|20)\d0|'?[1-9]0)s\b",
        _speak_decade,
    )

    # Money, times, number ranges, fractions and symbols.
    collect("number.currency", _CURRENCY, _speak_currency, 0)
    collect("number.time", _TIME, lambda match: _speak_time(text, match))
    for match in re.finditer(
        r"(?<![\w.,/:$€£¥-])(?P<a>\d+(?:\.\d+)?)(?P<dash>\s*[–—-]\s*)(?P<b>\d+(?:\.\d+)?)(?![\w.,/:-]?\d)", text,
    ):
        dash = match.group("dash").strip()
        if dash != "-" or _RANGE_HYPHEN_CONTEXT.search(text[:match.start("dash")]):
            add("number.range", match.start("dash"), match.end("dash"), " to ")
    collect("number.fraction", _FRACTION, _speak_fraction)
    collect("number.multiplier", r"(?<![\w.])(?P<n>\d+(?:\.\d+)?)x(?!\w)", lambda match: f"{match.group('n')} times", 0)
    collect("number.dimensions", r"(?<![\w.])(?P<a>\d+)\s?[x×]\s?(?P<b>\d+)(?![\w.]?\d)",
            lambda match: f"{match.group('a')} by {match.group('b')}", 0)
    collect(
        "number.version",
        r"(?<![\w.])(?:(?P<prefix>v)(?P<short>\d+(?:\.\d+){1,3})|(?P<version>\d+(?:\.\d+){2,3}))(?![\w.]?\d)",
        _speak_version, 0,
    )
    collect("symbol.approximately", r"~\s?(?=\d)", lambda _: "about ", 0)
    collect("symbol.number", r"(?<![\w&])#(?=\d)", lambda _: "number ", 0)

    # Roman numerals after a counting word or a regnal name.
    collect("number.roman", _ROMAN_AFTER_KEYWORD, _speak_roman_after_keyword, 0)
    collect("number.regnal", _REGNAL, _speak_regnal, 0)

    collect(
        "unit",
        r"(?<![\w.])(?P<number>\d[\d,]*(?:\.\d+)?)(?P<space>\s*)(?P<unit>km/h|m/s|km|cm|mm|kg|mg|g|mph|mi|ft|in|kHz|MHz|GHz|Hz|MiB|GiB|MB|GB|ms|min|s|h|°C|°F|%)(?!\w)",
        lambda match: _speak_unit_match(match, normalized_language),
    )

    if expand_dates:
        collect("date.iso", r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?!\d)", _speak_iso_date)
    if expand_citations:
        collect(
            "citation.numeric",
            r"\[(?P<refs>\s*\d+(?:\s*[,;–-]\s*\d+)*\s*)\]",
            lambda match: _speak_numeric_citation(match.group("refs")),
        )
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    return found


# Terms espeak-ng (the Piper front end) mispronounces, keyed case-sensitively.
# Each entry was checked against the bundled phonemizer; terms it already reads
# well (NASA, SQL, GitHub, JSON, nginx, macOS, ...) are deliberately absent.
_LEXICON = {
    "LaTeX": "lay tek",
    "TeX": "tek",
    "SaaS": "sass",
    "PaaS": "pass",
    "PostgreSQL": "post gress Q L",
    "IoT": "I O T",
    "IEEE": "I triple E",
    "ACM": "A C M",
    "Qt": "cute",
    "CLI": "C L I",
    "IDE": "I D E",
    "IDEs": "I D Es",
    "arXiv": "archive",
    "PyPI": "pie P I",
    "x86": "x eighty-six",
    "x86_64": "x eighty-six sixty-four",
    "CI/CD": "C I C D",
    "LLaMA": "llama",
}

_TITLES = {
    "Dr": "Doctor", "Mr": "Mister", "Mrs": "Missus", "Ms": "Miz", "Mx": "Mix", "Prof": "Professor",
    "Gen": "General", "Capt": "Captain", "Lt": "Lieutenant", "Sgt": "Sergeant", "Col": "Colonel",
    "Rev": "Reverend", "Sen": "Senator", "Rep": "Representative", "Gov": "Governor",
    "Pres": "President", "Fr": "Father",
}

_REFERENCE_ABBREVIATIONS = {
    "fig": "figure", "figs": "figures", "eq": "equation", "eqs": "equations", "vol": "volume",
    "vols": "volumes", "no": "number", "nos": "numbers", "ch": "chapter", "chs": "chapters",
    "chap": "chapter", "sec": "section", "secs": "sections", "sect": "section", "pt": "part",
    "pts": "parts", "ref": "reference", "refs": "references", "tab": "table", "app": "appendix",
}


_SENTENCE_STARTERS = frozenset(
    "A An And As At But For He Her His I If In It Its On Our She So That The Their Then There These They "
    "This Those To We When Where While You".split()
)


def _saint_or_street(text: str, match: re.Match[str]) -> str | None:
    """"St. Louis" is a saint; "Main St." is a street, possibly ending the sentence."""
    after_street_name = re.search(r"[A-Z][\w'’-]*\s$", text[:match.start()]) is not None
    following = re.match(r"\s+[\"“(]?([A-Z][\w'’-]*)", text[match.end():])
    if following and not (after_street_name and following.group(1) in _SENTENCE_STARTERS):
        return "Saint"
    if not after_street_name:
        return None
    ends_sentence = following is not None or not text[match.end():].strip()
    return "Street." if ends_sentence else "Street"


_MONTH_PATTERN = (
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)"
)
_MONTH_DATE = (
    rf"\b{_MONTH_PATTERN}(?:\s+(?P<day>[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?(?P<comma>,)?)?"
    r"(?:\s+(?P<year>1[1-9]\d\d|20\d\d))?(?![\w,]?\d)"
)
_DAY_MONTH_DATE = (
    rf"\b(?P<day>[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+{_MONTH_PATTERN}(?:,?\s+(?P<year>1[1-9]\d\d|20\d\d))?(?![\w,]?\d)"
)


def _month_name(value: str) -> str:
    prefix = value.rstrip(".")[:3].casefold()
    return next(month for month in _MONTHS if month[:3].casefold() == prefix)


def _speak_month_date(match: re.Match[str], language: str) -> str | None:
    if not match.group("day") and not match.group("year"):
        return None
    parts = [_month_name(match.group("month"))]
    if match.group("day"):
        day = _ordinal_words(int(match.group("day")))
        parts.append(f"the {day}" if language == "en_gb" else day)
    spoken = " ".join(parts)
    if match.group("year"):
        spoken += ("," if match.group("day") else "") + " " + _year_words(int(match.group("year")))
    elif match.group("comma"):
        spoken += ","
    return spoken


def _speak_day_month_date(match: re.Match[str]) -> str:
    spoken = f"the {_ordinal_words(int(match.group('day')))} of {_month_name(match.group('month'))}"
    if match.group("year"):
        spoken += f", {_year_words(int(match.group('year')))}"
    return spoken


_YEAR_PREPOSITIONS = (
    r"c\.|ca\.|in|since|by|until|till|from|during|circa|before|after|around|year|of|early|late|mid|spring|summer|"
    "autumn|fall|winter|between|and|to|through"
)
_YEAR_IN_CONTEXT = (
    rf"(?<![\w.])(?P<word>{_YEAR_PREPOSITIONS})(?P<space>\s+)(?P<year>1[1-9]\d\d|20\d\d)"
    r"(?:(?P<dash>\s*[–—]\s*|-)(?P<end>1[1-9]\d\d|20\d\d|\d\d))?(?![\w,.]?\d)(?!s\b)(?!\s*(?:%|percent))"
)
_YEAR_RANGE = (
    r"(?<![\w.,/:$€£¥-])(?P<start>1[1-9]\d\d|20\d\d)(?P<dash>\s*[–—-]\s*)(?P<end>1[1-9]\d\d|20\d\d|\d\d)(?![\w.,/:-]?\d)"
)
# Words that may follow a year; any other lowercase word suggests a count ("in 1500 samples").
_AFTER_YEAR_WORDS = frozenset(
    "a an and as at before but by during for he her his i in it its on or our she so than that the their "
    "them then there they this to until was we were when where which while who with".split()
)


def _speak_year_in_context(text: str, match: re.Match[str]) -> str | None:
    year = int(match.group("year"))
    following = re.match(r"\s+([A-Za-z]+)", text[match.end():])
    if following and following.group(1).islower() and following.group(1) not in _AFTER_YEAR_WORDS:
        return None
    if match.group("word").casefold() in {"and", "to", "through", "of"}:
        # Only after another year or a date phrase: "between 1990 and 2000", "the summer of 1969".
        before = text[:match.start()]
        if not re.search(r"(?:\b(?:1[1-9]\d\d|20\d\d)|between|spring|summer|autumn|fall|winter|end|start|beginning|middle)\s*$", before, re.IGNORECASE):
            return None
    word = match.group("word")
    word = "circa" if word.casefold() in {"c.", "ca."} else word
    if match.group("end"):
        spoken_range = _speak_year_range(match.group("year"), match.group("dash"), match.group("end"))
        return f"{word}{match.group('space')}{spoken_range}" if spoken_range else None
    if 2000 <= year <= 2009 and word == match.group("word"):
        return None  # espeak already says "two thousand five".
    return f"{word}{match.group('space')}{_year_words(year)}"


def _speak_citation_year(match: re.Match[str]) -> str | None:
    """Author-date citations: "(2020)", "(1998a, 2003)"."""
    year = int(match.group("year"))
    if 2000 <= year <= 2009 and not match.group("suffix"):
        return None
    if match.string[match.start() - 1] != "(" and not re.search(r"\([^()]*$", match.string[:match.start()]):
        return None  # Only inside parentheses.
    return _year_words(year) + (f" {match.group('suffix').upper()}" if match.group("suffix") else "")


def _speak_year_range(start_text: str, dash: str, end_text: str) -> str | None:
    start = int(start_text)
    end = int(end_text) if len(end_text) == 4 else start // 100 * 100 + int(end_text)
    if not start < end <= start + 200:
        return None
    if dash.strip() == "-" and len(end_text) != 4:
        return None  # "2024-05" is more often a year-month.
    end_words = _year_words(end) if len(end_text) == 4 else _integer_words(int(end_text)) if int(end_text) >= 10 else f"oh {_integer_words(int(end_text))}"
    return f"{_year_words(start)} to {end_words}"


def _speak_decade(match: re.Match[str]) -> str | None:
    decade = match.group("decade").lstrip("'")
    if len(decade) == 2 and not (match.group("prefix") or match.group("decade").startswith("'")):
        return None
    words = _year_words(int(decade)) if len(decade) == 4 else _integer_words(int(decade))
    if words.endswith("y"):
        words = words[:-1] + "ies"
    else:
        words += "s"
    prefix = match.group("prefix") or ""
    return f"{prefix}{match.group('space') or ''}{words}"


_CURRENCY = (
    r"(?<![\w$€£¥])(?P<symbol>[$€£¥])\s?(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?"
    r"(?:(?P<scale_space>\s?)(?P<scale>thousand|million|billion|trillion|K|M|B|bn|Bn|BN)\b)?"
)
_CURRENCY_NAMES = {
    "$": ("dollar", "dollars", "cent", "cents"),
    "€": ("euro", "euros", "cent", "cents"),
    "£": ("pound", "pounds", "penny", "pence"),
    "¥": ("yen", "yen", None, None),
}
_CURRENCY_SCALES = {"k": "thousand", "m": "million", "b": "billion", "bn": "billion"}


def _speak_currency(match: re.Match[str]) -> str:
    singular, plural, minor_singular, minor_plural = _CURRENCY_NAMES[match.group("symbol")]
    whole = int(match.group("whole").replace(",", ""))
    fraction = match.group("fraction")
    scale = match.group("scale")
    if scale:
        scale_word = _CURRENCY_SCALES.get(scale.casefold(), scale.casefold())
        return f"{_number_words(match.group('whole') + (fraction or ''))} {scale_word} {plural}"
    if fraction and len(fraction) == 3 and minor_plural:
        cents = int(fraction[1:])
        major = f"{_integer_words(whole)} {singular if whole == 1 else plural}"
        minor = f"{_integer_words(cents)} {minor_singular if cents == 1 else minor_plural}"
        if cents == 0:
            return major
        return minor if whole == 0 else f"{major} and {minor}"
    if fraction:
        return f"{_number_words(match.group('whole') + fraction)} {plural}"
    return f"{_integer_words(whole)} {singular if whole == 1 else plural}"


_TIME = r"(?<![\w:.])(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?![\d:])(?P<meridiem>\s*(?P<letter>[ap])\.?m\.?(?!\w))?"
_TIME_CONTEXT = re.compile(r"\b(?:at|by|from|until|till|before|after|around|about|since|to|and|or|between)\s*$", re.IGNORECASE)


def _speak_time(text: str, match: re.Match[str]) -> str | None:
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    meridiem = match.group("meridiem")
    if not meridiem and not _TIME_CONTEXT.search(text[:match.start()]):
        return None  # Could be a ratio, score or verse reference.
    if meridiem and not 1 <= hour <= 12:
        return None
    if minute == 0:
        spoken = _integer_words(hour) if meridiem else (
            f"{_integer_words(hour)} o'clock" if hour <= 12 else f"{_integer_words(hour)} hundred")
    elif minute < 10:
        spoken = f"{_integer_words(hour)} oh {_integer_words(minute)}"
    else:
        spoken = f"{_integer_words(hour)} {_integer_words(minute)}"
    if meridiem:
        spoken += " AM" if match.group("letter").casefold() == "a" else " PM"
        if match.group("meridiem").endswith(".") and not re.match(r"\s+[a-z]", text[match.end():]):
            spoken += "."
    return spoken


_RANGE_HYPHEN_CONTEXT = re.compile(
    r"(?:\b(?:pp\.|pages?|p\.|nos?\.|chapters?|sections?|verses?|lines?|figures?|figs\.|items?|steps?|ages?|aged|"
    r"rows?|columns?|slides?|weeks?|days?|years?|months?|levels?|grades?|between|from)|§§?)\s*\d+(?:\.\d+)?$",
    re.IGNORECASE,
)

_FRACTION = r"(?<![\w/.,])(?:(?P<whole>\d+)\s+)?(?P<numerator>[1-9])/(?P<denominator>[2-9]|1[0-6])(?![\w/.,]?\d)"
_FRACTION_DENOMINATORS = {2: ("half", "halves"), 4: ("quarter", "quarters")}


def _speak_fraction(match: re.Match[str]) -> str | None:
    numerator, denominator = int(match.group("numerator")), int(match.group("denominator"))
    if numerator >= denominator:
        return None
    singular, plural = _FRACTION_DENOMINATORS.get(denominator, (None, None))
    if singular is None:
        singular = _ordinal_words(denominator)
        plural = singular + "s"
    fraction = f"{_integer_words(numerator)} {singular if numerator == 1 else plural}"
    if match.group("whole"):
        if numerator == 1:
            return f"{_integer_words(int(match.group('whole')))} and a {singular}"
        return f"{_integer_words(int(match.group('whole')))} and {fraction}"
    return fraction


def _speak_version(match: re.Match[str]) -> str:
    parts = (match.group("short") or match.group("version")).split(".")
    spoken = " point ".join(_integer_words(int(part)) for part in parts)
    return f"version {spoken}" if match.group("prefix") else spoken


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman_value(value: str) -> int | None:
    total = 0
    for index, letter in enumerate(value):
        current = _ROMAN_VALUES[letter]
        following = _ROMAN_VALUES[value[index + 1]] if index + 1 < len(value) else 0
        total += -current if current < following else current
    return total if 0 < total <= 100 and _to_roman(total) == value else None


def _to_roman(value: int) -> str:
    result = []
    for number, letters in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while value >= number:
            result.append(letters)
            value -= number
    return "".join(result)


_ROMAN_KEYWORDS = (
    "Chapter|Part|Volume|Vol\\.|Book|Act|Scene|Section|Appendix|Phase|Stage|Level|Class|Type|Article|Title|"
    "Annex|Grade|Round|Season|Episode|Schedule|Tier|World War|Super Bowl|Vatican"
)
_ROMAN_AFTER_KEYWORD = rf"\b(?P<keyword>{_ROMAN_KEYWORDS})\s+(?P<roman>[IVXLC]+)\b(?![.'’]?\w)"
_REGNAL_NAMES = (
    "Henry|Edward|George|William|Richard|James|Charles|John|Louis|Philip|Elizabeth|Mary|Anne|Victor|Peter|"
    "Paul|Pius|Benedict|Gregory|Leo|Innocent|Clement|Urban|Boniface|Frederick|Ferdinand|Alexander|Nicholas|"
    "Catherine|Ivan|Napoleon|Ramesses|Constantine|Otto|Wilhelm|Gustav|Carl|Alfonso|Juan|Felipe|Pedro|"
    "Manuel|Haakon|Olav|Harald|Christian|Frederik|Mehmed|Selim|Murad|Suleiman|Isabella|David|Malcolm|Robert"
)
_REGNAL = rf"\b(?P<name>{_REGNAL_NAMES})\s+(?P<roman>[IVX]+)\b(?![.'’]?\w)"


def _pronoun_follows(match: re.Match[str]) -> bool:
    """True when a bare "I" is followed by a lowercase word, as in "Part I describe"."""
    return match.group("roman") == "I" and re.match(r"\s+[a-z]", match.string[match.end():]) is not None


def _speak_roman_after_keyword(match: re.Match[str]) -> str | None:
    value = _roman_value(match.group("roman"))
    if value is None or _pronoun_follows(match):
        return None
    keyword = match.group("keyword")
    keyword = "Volume" if keyword == "Vol." else keyword
    return f"{keyword} {_integer_words(value)}"


def _speak_regnal(match: re.Match[str]) -> str | None:
    value = _roman_value(match.group("roman"))
    if value is None or value > 30 or _pronoun_follows(match):
        return None
    return f"{match.group('name')} the {_ordinal_words(value)}"


def _speak_unit_match(match: re.Match[str], language: str) -> str | None:
    unit = match.group("unit")
    number = match.group("number")
    if unit == "in" and match.group("space"):
        return None  # "ranked 3 in the world" is not inches.
    if unit == "s" and not match.group("space") and re.fullmatch(r"(?:1[1-9]|20)\d0", number):
        return None  # "1990s" is a decade.
    return _speak_measurement(number, unit, language)


_SMALL_NUMBERS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                  "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                  "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (10**3, "thousand"))


def _integer_words(value: int) -> str:
    if value < 20:
        return _SMALL_NUMBERS[value]
    if value < 100:
        return _TENS[value // 10] + (f"-{_SMALL_NUMBERS[value % 10]}" if value % 10 else "")
    if value < 1000:
        remainder = value % 100
        return f"{_SMALL_NUMBERS[value // 100]} hundred" + (f" {_integer_words(remainder)}" if remainder else "")
    for scale, name in _SCALES:
        if value >= scale:
            quotient, remainder = divmod(value, scale)
            return f"{_integer_words(quotient)} {name}" + (f" {_integer_words(remainder)}" if remainder else "")
    return " ".join(_SMALL_NUMBERS[int(digit)] for digit in str(value))


def _number_words(value: str) -> str:
    normalized = value.replace(",", "")
    if "." not in normalized:
        return _integer_words(int(normalized))
    whole, fraction = normalized.split(".", 1)
    return f"{_integer_words(int(whole))} point " + " ".join(_SMALL_NUMBERS[int(digit)] for digit in fraction)


_UNIT_NAMES = {
    "km/h": ("kilometer per hour", "kilometers per hour"), "m/s": ("meter per second", "meters per second"),
    "km": ("kilometer", "kilometers"), "cm": ("centimeter", "centimeters"),
    "mm": ("millimeter", "millimeters"), "kg": ("kilogram", "kilograms"),
    "mg": ("milligram", "milligrams"), "g": ("gram", "grams"),
    "mph": ("mile per hour", "miles per hour"), "mi": ("mile", "miles"),
    "ft": ("foot", "feet"), "in": ("inch", "inches"), "hz": ("hertz", "hertz"),
    "khz": ("kilohertz", "kilohertz"), "mhz": ("megahertz", "megahertz"),
    "ghz": ("gigahertz", "gigahertz"), "mib": ("mebibyte", "mebibytes"),
    "gib": ("gibibyte", "gibibytes"), "mb": ("megabyte", "megabytes"),
    "gb": ("gigabyte", "gigabytes"), "ms": ("millisecond", "milliseconds"),
    "min": ("minute", "minutes"), "s": ("second", "seconds"), "h": ("hour", "hours"),
    "°c": ("degree Celsius", "degrees Celsius"), "°f": ("degree Fahrenheit", "degrees Fahrenheit"),
    "%": ("percent", "percent"),
}


def _speak_measurement(number: str, unit: str, language: str) -> str:
    spoken_number = _number_words(number)
    singular = number.replace(",", "") in {"1", "1.0"}
    forms = _UNIT_NAMES[unit.casefold()]
    if language == "en_gb":
        forms = tuple(form.replace("kilometer", "kilometre").replace("centimeter", "centimetre").replace("millimeter", "millimetre") for form in forms)
    return f"{spoken_number} {forms[0 if singular else 1]}"


def _ordinal_words(value: int) -> str:
    cardinal = _integer_words(value)
    endings = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
               "nine": "ninth", "twelve": "twelfth"}
    last = cardinal.rsplit(" ", 1)[-1]
    if last in endings:
        return cardinal[: -len(last)] + endings[last]
    if last.endswith("y"):
        return cardinal[: -1] + "ieth"
    return cardinal + "th"


def _year_words(year: int) -> str:
    """Read a year the usual English way: "eighteen hundred", "nineteen oh five", "twenty twenty-four"."""
    if 2000 <= year <= 2009:
        return "two thousand" + (f" {_integer_words(year % 1000)}" if year % 1000 else "")
    if not 1100 <= year <= 2099:
        return _integer_words(year)
    century, remainder = divmod(year, 100)
    if remainder == 0:
        return f"{_integer_words(century)} hundred"
    if remainder < 10:
        return f"{_integer_words(century)} oh {_integer_words(remainder)}"
    return f"{_integer_words(century)} {_integer_words(remainder)}"


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def _speak_iso_date(match: re.Match[str]) -> str:
    year, month, day = (int(match.group(name)) for name in ("year", "month", "day"))
    try:
        date(year, month, day)
    except ValueError:
        return match.group()
    return f"{_MONTHS[month - 1]} {_ordinal_words(day)}, {_year_words(year)}"


def _speak_numeric_citation(value: str) -> str:
    range_match = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", value)
    if range_match:
        return f"references {_integer_words(int(range_match.group(1)))} through {_integer_words(int(range_match.group(2)))}"
    references = re.findall(r"\d+", value)
    spoken = [_integer_words(int(reference)) for reference in references]
    if len(spoken) == 1:
        return f"reference {spoken[0]}"
    return "references " + ", ".join(spoken[:-1]) + f" and {spoken[-1]}"


def _content_type(block: DocumentBlock, source_text: str) -> str:
    if block.kind == "heading":
        return "heading"
    if block.kind == "list_item":
        return "list_item"
    if block.kind == "footnote":
        return "footnote"
    if "table_row" in block.kind_source:
        return "table_row"
    if _SPEAKER_LABEL.match(source_text) or _DIALOGUE_ATTRIBUTION.search(source_text):
        return "dialogue_candidate"
    if block.kind == "quote" or (
        source_text.startswith(("\"", "“", "‘"))
        and source_text.endswith(("\"", "”", "’"))
    ):
        return "quotation"
    return "paragraph"


def _pause_after(source_text: str, content_type: str, block_end: bool) -> int:
    if content_type == "heading":
        return 720
    if content_type == "table_row":
        return 520 if block_end else 380
    ending = source_text.rstrip()
    if ending.endswith(("...", "…")):
        pause = 520
    elif ending.endswith("?"):
        pause = 420
    elif ending.endswith("!"):
        pause = 360
    elif ending.endswith((";", ":")):
        pause = 340
    elif ending.endswith(("—", "–")):
        pause = 360
    elif ending.endswith(","):
        pause = 240
    elif ending.endswith("."):
        pause = 300
    else:
        pause = 280
    if content_type == "list_item":
        return pause + (80 if block_end else 0)
    if content_type == "footnote":
        return pause + (50 if block_end else 0)
    if content_type in {"quotation", "dialogue_candidate"} and block_end:
        return max(pause, 460)
    if block_end:
        return max(pause, 520)
    return pause


def _unit_id(block: DocumentBlock, start: int, end: int, source_text: str) -> str:
    signature = f"{block.id}\0{start}\0{end}\0{source_text}".encode("utf-8")
    return f"{block.id}-u{start:05d}-{hashlib.sha256(signature).hexdigest()[:10]}"
