"""Deterministic narration planning that never rewrites source document text."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from document import Document, DocumentBlock, ExtractionNote


NARRATION_SCHEMA_VERSION = 1
NARRATION_RULESET_VERSION = "rules-4"

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
            )
            matched_overrides.update(application.override_id for application in applications)
            content_type = _content_type(block, source_text.strip())
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
                pause_after_ms=_pause_after(source_text, content_type, end == len(block.text)),
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
        if text[index] not in ".?!…":
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
        while end < len(text) and text[end] in ".?!…":
            end += 1
        while end < len(text) and text[end] in _CLOSERS:
            end += 1
        if end == len(text) or text[end].isspace():
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
        while end - cursor > _MAX_PASSAGE_CHARS or len(text[cursor:end].split()) > _MAX_PASSAGE_WORDS:
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
                and len(combined.split()) <= _MAX_PASSAGE_WORDS):
            current_end = end
        else:
            passages.append((current_start, current_end))
            current_start, current_end = start, end
    passages.append((current_start, current_end))
    return passages


def _word_limit_end(text: str, start: int, end: int, max_words: int) -> int:
    words = list(re.finditer(r"\S+", text[start:end]))
    if len(words) <= max_words:
        return end
    return start + words[max_words - 1].end()


def _is_dialogue_attribution(text: str, index: int) -> bool:
    if index >= len(text):
        return False
    tail = text[index:]
    return bool(re.match(
        r"(?:(?:he|she|they|i|we)\s+)?(?:said|says|asked|asks|replied|replies|whispered|shouted|answered|continued)\b",
        tail,
        re.IGNORECASE,
    ))


def _is_decimal_point(text: str, index: int) -> bool:
    return index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit()


def _is_abbreviation_period(text: str, index: int) -> bool:
    match = re.search(r"([A-Za-z](?:[A-Za-z.]*[A-Za-z])?)\.$", text[:index + 1])
    return bool(match and match.group(1).casefold() in _ABBREVIATIONS)


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
    return "".join(output), applications


def _automatic_spoken_rules(
    text: str,
    *,
    language: str,
    expand_dates: bool,
    expand_citations: bool,
) -> list[tuple[int, int, str, str, str, str]]:
    """Return reversible English-only spoken substitutions with local source spans."""
    normalized_language = language.replace("-", "_").casefold()
    if normalized_language not in {"en_us", "en_gb", "en"}:
        return []
    found: list[tuple[int, int, str, str, str, str]] = []

    def collect(rule_id: str, pattern: str, replacement) -> None:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = replacement(match)
            if value and match.group()[:1].isupper():
                value = value[:1].upper() + value[1:]
            if value and value != match.group():
                found.append((match.start(), match.end(), f"auto:{normalized_language}:{rule_id}",
                              match.group(), value, match.group()))

    for token, spoken in (
        (r"e\.g\.", "for example"),
        (r"i\.e\.", "that is"),
        (r"etc\.", "and so on"),
        (r"vs\.", "versus"),
        (r"approx\.", "approximately"),
    ):
        collect(f"abbreviation.{token.replace('.', '')}", rf"(?<!\w){token}(?!\w)", lambda _, spoken=spoken: spoken)

    collect(
        "unit",
        r"(?<![\w.])(?P<number>\d[\d,]*(?:\.\d+)?)(?P<space>\s*)(?P<unit>km/h|m/s|km|cm|mm|kg|mg|g|mph|mi|ft|in|kHz|MHz|GHz|Hz|MiB|GiB|MB|GB|ms|min|s|h|°C|°F|%)(?!\w)",
        lambda match: _speak_measurement(match.group("number"), match.group("unit"), normalized_language),
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
    if 2000 <= year <= 2009:
        return "two thousand" + (f" {_integer_words(year % 1000)}" if year % 1000 else "")
    if 2010 <= year <= 2099:
        return f"twenty {_integer_words(year % 100)}"
    if 1900 <= year <= 1999:
        return f"nineteen {_integer_words(year % 100)}" if year % 100 else "nineteen hundred"
    return _integer_words(year)


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
