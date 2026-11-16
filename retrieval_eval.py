#!/usr/bin/env python3
"""Measure assistant retrieval quality: recall@k and MRR on labelled questions.

The bundled set is a fictional municipal report (written for this test, so
it never drifts with the repository) with questions of three kinds:

- ``lexical``: shares key words with the answering passage.
- ``paraphrase``: asks the same thing in other words. Keyword ranking is
  expected to struggle here; this is where embeddings should help.
- ``numeric``: asks for a figure, date or name.

Usage:
  python retrieval_eval.py                       # BM25 on the bundled set
  python retrieval_eval.py --json report.json
  python retrieval_eval.py --embedding-endpoint http://127.0.0.1:9931/v1 \
      --embedding-model nomic-embed-text         # adds vector and hybrid rankings
  python retrieval_eval.py --document notes.txt --cases cases.json
      # cases.json: [{"question": "...", "answer_phrase": "...", "kind": "..."}]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Sequence

from retrieval import Bm25Index, RetrievalCase, VectorIndex, chunk_document, evaluate_retrieval, fuse_rankings

# One passage per paragraph, so recall@k separates good and poor rankings.
EVALUATION_PASSAGE_CHARS = 480

EVALUATION_DOCUMENT = """\
Harrowgate Water Board: Annual Report

The Harrowgate Water Board supplies drinking water to about 48,000 residents across the town and the three outlying
villages of Brennock, Saltmere and Upper Linfield. This report covers the year from April to March and was approved
by the board on 14 May.

Supply sources. Roughly two thirds of the town's water comes from the Calder reservoir, filled by upland streams.
The remaining third is pumped from four boreholes in the chalk aquifer east of the river. Borehole 3 was taken out of
service in September after nitrate readings rose above the board's internal action level.

Treatment. Water from the reservoir passes through slow sand filters and is then disinfected with ultraviolet light
before a small chlorine residual is added for the pipe network. The slow sand filters were rebuilt in the summer, the
first full rebuild since 1987, at a cost of 2.3 million pounds.

Leakage. The network lost an estimated 17 percent of treated water to leaks, down from 21 percent the year before.
Acoustic loggers were fitted to 600 kilometres of main, and crews repaired 1,140 bursts. The worst single failure was a
cast-iron trunk main under Mill Street, which flooded six cellars in January.

Water quality. Of 9,800 samples taken at customer taps, 99.96 percent met every regulatory standard. Four samples
failed for discoloration after the Mill Street burst stirred up sediment, and none failed for bacteria. Lead pipes
remain in roughly 2,000 older homes; the board offers free replacement of the shared supply pipe on request.

Drought planning. The spring was the driest in thirty years, and reservoir storage fell to 41 percent in early August.
A temporary hosepipe ban ran from 2 August to 19 September. Demand fell by 11 percent during the ban, which the board
credits mainly to garden watering restrictions rather than to industrial users.

Customer service. The board received 3,200 written complaints, a fall of a quarter, most of them about low pressure in
Upper Linfield. A new booster pumping station for Upper Linfield is planned for completion next autumn. The average
time to answer the phone was 46 seconds.

Finances. Operating income was 31 million pounds against costs of 27 million. Average household bills rose by 4.5
percent, below inflation. The board borrowed 12 million pounds over 25 years to pay for the filter rebuild and the
leakage programme, and its credit rating was unchanged.

Staff. The board employs 212 people. Eleven apprentices joined the network maintenance team, and two engineers
completed chartered status. There were no reportable safety incidents, the third year in a row.

Outlook. Next year the board will begin a five-year programme to replace the remaining cast-iron trunk mains, starting
with the town centre. It will also trial smart meters in Saltmere, where about 900 homes have volunteered, to test
whether usage data helps households cut consumption.
"""

EVALUATION_CASES: tuple[RetrievalCase, ...] = (
    RetrievalCase("How many residents does the water board supply?", "48,000 residents"),
    RetrievalCase("Which villages are served besides the town?", "Brennock, Saltmere"),
    RetrievalCase("Why was borehole 3 taken out of service?", "nitrate readings"),
    RetrievalCase("Where does most of the town's water come from?", "Calder reservoir"),
    RetrievalCase("How is reservoir water disinfected?", "ultraviolet light"),
    RetrievalCase("How much did the slow sand filter rebuild cost?", "2.3 million"),
    RetrievalCase("What percentage of treated water was lost to leaks?", "17 percent"),
    RetrievalCase("How many bursts did crews repair?", "1,140 bursts"),
    RetrievalCase("What happened under Mill Street in January?", "flooded six cellars"),
    RetrievalCase("How many tap samples met every standard?", "99.96 percent"),
    RetrievalCase("Does the board replace lead pipes?", "free replacement"),
    RetrievalCase("When did the hosepipe ban run?", "2 August to 19 September"),
    RetrievalCase("How low did reservoir storage fall?", "41 percent"),
    RetrievalCase("What did most complaints concern?", "low pressure"),
    RetrievalCase("How long did customers wait for the phone to be answered?", "46 seconds"),
    RetrievalCase("How much did average household bills rise?", "4.5"),
    RetrievalCase("How much money did the board borrow?", "12 million pounds"),
    RetrievalCase("How many apprentices joined?", "Eleven apprentices"),
    RetrievalCase("Where will smart meters be trialled?", "smart meters in Saltmere"),
    # Paraphrases: few or no shared content words with the answer.
    RetrievalCase("Were there any injuries at work?", "no reportable safety incidents"),
    RetrievalCase("Did people use less water when outdoor watering was restricted?", "Demand fell by 11 percent"),
    RetrievalCase("Was anyone made ill by germs in the supply?", "none failed for bacteria"),
    RetrievalCase("What will be done about the old iron pipes in the centre?", "five-year programme"),
    RetrievalCase("Did the organisation make a surplus?", "Operating income"),
)
CASE_KINDS = {case.question: "paraphrase" for case in EVALUATION_CASES[19:]}
CASE_KINDS.update({EVALUATION_CASES[i].question: "numeric" for i in (0, 5, 6, 7, 9, 11, 12, 14, 15, 16)})


def evaluation_passages() -> list[str]:
    return chunk_document(EVALUATION_DOCUMENT, max_chars=EVALUATION_PASSAGE_CHARS)


def run_evaluation(
    passages: Sequence[str],
    cases: Sequence[RetrievalCase],
    kinds: dict[str, str],
    *,
    embed: Callable[[str], list[float]] | None = None,
) -> dict[str, object]:
    bm25 = Bm25Index(passages)
    rankers: dict[str, Callable[[str], Sequence[int]]] = {"bm25": bm25.rank}
    if embed is not None:
        index = VectorIndex.build(passages, embed)
        rankers["vector"] = lambda question: index.rank(embed(question))
        rankers["hybrid"] = lambda question: fuse_rankings([bm25.rank(question), index.rank(embed(question))])
    report: dict[str, object] = {}
    for name, rank in rankers.items():
        overall = evaluate_retrieval(passages, cases, rank)
        by_kind = {}
        for kind in sorted(set(kinds.get(case.question, "lexical") for case in cases)):
            subset = [case for case in cases if kinds.get(case.question, "lexical") == kind]
            by_kind[kind] = {key: value for key, value in evaluate_retrieval(passages, subset, rank).items() if key != "misses"}
        report[name] = {**overall, "by_kind": by_kind}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document", type=Path, help="Evaluate on this plain-text document instead of the bundled one")
    parser.add_argument("--cases", type=Path, help="JSON list of {question, answer_phrase, kind} for --document")
    parser.add_argument("--embedding-endpoint", help="Local OpenAI-compatible endpoint with /embeddings")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if bool(args.document) != bool(args.cases):
        parser.error("--document and --cases go together")
    if args.document:
        passages = chunk_document(args.document.read_text(encoding="utf-8"))
        raw = json.loads(args.cases.read_text(encoding="utf-8"))
        cases = [RetrievalCase(item["question"], item["answer_phrase"]) for item in raw]
        kinds = {item["question"]: item.get("kind", "lexical") for item in raw}
    else:
        passages, cases, kinds = evaluation_passages(), list(EVALUATION_CASES), CASE_KINDS

    embed = None
    if args.embedding_endpoint:
        from llm_client import LlmConfig, _embedding

        config = LlmConfig(provider="llama_cpp", endpoint=args.embedding_endpoint, embedding_model=args.embedding_model)
        nomic = "nomic-embed-text" in args.embedding_model.lower()

        def embed(text: str) -> list[float]:
            return _embedding(config, text)

        if nomic:
            # Task prefixes the nomic models were trained with.
            base = embed

            def embed(text: str) -> list[float]:  # noqa: F811
                prefix = "search_query: " if text.endswith("?") else "search_document: "
                return base(prefix + text)

    try:
        report = run_evaluation(passages, cases, kinds, embed=embed)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"retrieval_eval: {exc}", file=sys.stderr)
        return 2
    print(f"{len(cases)} questions over {len(passages)} passages")
    for name, result in report.items():
        print(f"{name:>7}: recall@1 {result['recall@1']:.2f}  recall@3 {result['recall@3']:.2f}  "
              f"recall@5 {result['recall@5']:.2f}  MRR {result['mrr']:.2f}")
        for kind, values in result["by_kind"].items():
            print(f"         {kind:<10} n={values['cases']:<3} recall@3 {values['recall@3']:.2f}  MRR {values['mrr']:.2f}")
        for miss in result["misses"]:
            print(f"         missed in top 5: {miss}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
