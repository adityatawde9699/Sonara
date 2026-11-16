"""Local passage retrieval for the reading assistant.

Every provider gets retrieval, not only the one with an embedding server:

- ``chunk_document`` splits text into paragraph-aligned passages.
- ``Bm25Index`` ranks passages lexically. It is pure Python, needs no model
  and runs on the device, so it works with Ollama, embedded llama.cpp and
  cloud providers alike, and no document text leaves the device to build it.
- ``VectorIndex`` holds embedding vectors (from a local llama.cpp server) and
  persists them in a content-addressed cache.
- ``fuse_rankings`` combines lexical and vector rankings with reciprocal rank
  fusion, which needs no score calibration between the two.

``evaluate_retrieval`` measures recall@k and MRR on labelled questions; see
``retrieval_eval.py`` for the bundled evaluation set.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

PASSAGE_CHARS = 1200
# Common English function words. Removing them keeps BM25 from matching on
# "the" and "of"; content words, numbers and names all stay.
STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have he her his how i if in into is it
    its me my no not of on or our she so than that the their them then there these they this those to us was we were
    what when where which who whom why will with would you your""".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def tokenize(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return [_stem(token) for token in _TOKEN.findall(folded) if token not in STOPWORDS]


def _stem(token: str) -> str:
    """Light suffix folding so "synthesis"/"synthesised" and "voices"/"voice" match."""
    if token.endswith("'s"):
        token = token[:-2]
    for suffix in ("ingly", "edly", "ings", "ing", "ies", "ied", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            stem = token[: -len(suffix)]
            if suffix in ("ies", "ied"):
                return stem + "y"
            if suffix == "es":
                # "boxes" -> "box", but "voices" -> "voice" (via the "s" rule).
                if stem.endswith(("ss", "x", "z", "ch", "sh")):
                    return stem
                continue
            if suffix == "s" and token.endswith(("ss", "us", "is")):
                return token
            return stem
    return token


def chunk_document(text: str, max_chars: int = PASSAGE_CHARS) -> list[str]:
    """Paragraph-aligned passages of at most ``max_chars`` characters.

    Short paragraphs are merged; a paragraph longer than the limit is split at
    word boundaries.
    """
    chunks: list[str] = []
    current = ""
    for paragraph in (part.strip() for part in re.split(r"\n\s*\n", text)):
        if not paragraph:
            continue
        pieces: list[str] = []
        piece = ""
        for word in paragraph.split():
            if piece and len(piece) + len(word) + 1 > max_chars:
                pieces.append(piece)
                piece = ""
            piece = f"{piece} {word}".strip()
        if piece:
            pieces.append(piece)
        for part in pieces:
            if current and len(current) + len(part) + 2 > max_chars:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{part}".strip()
    if current:
        chunks.append(current)
    return chunks


class Bm25Index:
    """Okapi BM25 over passages (k1 = 1.5, b = 0.75)."""

    def __init__(self, passages: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = list(passages)
        self.k1, self.b = k1, b
        self._terms = [Counter(tokenize(passage)) for passage in self.passages]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        frequency: Counter[str] = Counter()
        for terms in self._terms:
            frequency.update(terms.keys())
        count = len(self.passages)
        self._idf = {term: math.log(1 + (count - df + 0.5) / (df + 0.5)) for term, df in frequency.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        results = []
        for passage_terms, length in zip(self._terms, self._lengths):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / self._average) if self._average else self.k1
            for term in terms:
                tf = passage_terms.get(term, 0)
                if tf:
                    score += self._idf[term] * tf * (self.k1 + 1) / (tf + norm)
            results.append(score)
        return results

    def rank(self, query: str) -> list[int]:
        """Passage indexes, best first; passages with no matching term are left out."""
        scores = self.scores(query)
        return [index for index in sorted(range(len(scores)), key=lambda i: (-scores[i], i)) if scores[index] > 0]


@dataclass
class VectorIndex:
    passages: list[str]
    vectors: list[list[float]]

    @classmethod
    def build(
        cls,
        passages: Sequence[str],
        embed: Callable[[str], list[float]],
        *,
        cache_dir: Path | None = None,
        cache_key: str = "",
        document_prefix: str = "",
        max_cache_bytes: int = 256 * 1024 * 1024,
    ) -> VectorIndex:
        """Embed passages, reusing a cached index for the same passages and model."""
        passages = list(passages)
        cache = None
        if cache_dir is not None:
            digest = hashlib.sha256((cache_key + "\0" + "\0".join(passages)).encode("utf-8")).hexdigest()
            cache = cache_dir / f"{digest}.json"
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                if saved.get("chunks") == passages and len(saved.get("vectors", [])) == len(passages):
                    return cls(passages, saved["vectors"])
            except (OSError, ValueError, AttributeError):
                pass
        vectors = [embed(document_prefix + passage) for passage in passages]
        if cache is not None:
            _write_cache(cache, {"chunks": passages, "vectors": vectors})
            prune_cache(cache.parent, max(1, max_cache_bytes), protected=cache)
        return cls(passages, vectors)

    def rank(self, query_vector: Sequence[float]) -> list[int]:
        def cosine(vector: Sequence[float]) -> float:
            dot = sum(a * b for a, b in zip(query_vector, vector))
            norm = math.sqrt(sum(a * a for a in query_vector) * sum(b * b for b in vector))
            return dot / norm if norm else 0.0

        similarities = [cosine(vector) for vector in self.vectors]
        return sorted(range(len(similarities)), key=lambda i: (-similarities[i], i))


def _write_cache(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prune_cache(root: Path, max_bytes: int, *, protected: Path | None = None) -> int:
    """Delete the oldest content-addressed index files until under ``max_bytes``."""
    if not root.is_dir():
        return 0
    entries: list[tuple[float, Path, int]] = []
    for path in root.glob("*.json"):
        if len(path.stem) != 64 or any(char not in "0123456789abcdef" for char in path.stem):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, path, stat.st_size))
    total = sum(size for _, _, size in entries)
    removed = 0
    for _, path, size in sorted(entries):
        if total <= max_bytes:
            break
        if protected is not None and path == protected:
            continue
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


def fuse_rankings(rankings: Iterable[Sequence[int]], *, k: int = 60) -> list[int]:
    """Reciprocal rank fusion: score = sum of 1 / (k + rank) over rankings."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda index: (-scores[index], index))


def select_passages(passages: Sequence[str], ranking: Sequence[int], budget_chars: int, *, top_k: int = 6) -> list[int]:
    """The best-ranked passages that fit the character budget, in document order.

    Document order keeps the excerpts readable; the label of each passage is
    its position in the document, so citations stay stable across questions.
    """
    chosen: list[int] = []
    used = 0
    for index in ranking:
        size = len(passages[index]) + 20  # label and separator
        if len(chosen) >= top_k:
            break
        if used + size > budget_chars:
            continue
        chosen.append(index)
        used += size
    return sorted(chosen)


def format_passages(passages: Sequence[str], indexes: Sequence[int]) -> str:
    return "\n\n".join(f"[Passage {index + 1}]\n{passages[index]}" for index in indexes)


@dataclass(frozen=True)
class RetrievalCase:
    question: str
    # A phrase that only appears in the passages that answer the question.
    answer_phrase: str


def evaluate_retrieval(
    passages: Sequence[str],
    cases: Sequence[RetrievalCase],
    rank: Callable[[str], Sequence[int]],
    *,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, object]:
    """Recall@k (an answering passage is in the top k) and mean reciprocal rank."""
    if not cases:
        raise ValueError("No retrieval cases.")
    hits = {k: 0 for k in ks}
    reciprocal = 0.0
    misses = []
    for case in cases:
        relevant = {index for index, passage in enumerate(passages) if case.answer_phrase.lower() in passage.lower()}
        if not relevant:
            raise ValueError(f"No passage contains the answer phrase {case.answer_phrase!r}.")
        ranking = list(rank(case.question))
        first = next((position for position, index in enumerate(ranking, start=1) if index in relevant), None)
        if first is not None:
            reciprocal += 1 / first
        for k in ks:
            hits[k] += first is not None and first <= k
        if first is None or first > max(ks):
            misses.append(case.question)
    count = len(cases)
    return {
        "cases": count,
        "passages": len(passages),
        **{f"recall@{k}": round(hits[k] / count, 3) for k in ks},
        "mrr": round(reciprocal / count, 3),
        "misses": misses,
    }
