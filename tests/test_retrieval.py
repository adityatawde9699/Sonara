import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_client import LlmConfig, ask_document, context_budget_chars, retrieve_relevant_context, summarize_document
from retrieval import (
    Bm25Index,
    RetrievalCase,
    VectorIndex,
    chunk_document,
    evaluate_retrieval,
    fuse_rankings,
    select_passages,
    tokenize,
)
from retrieval_eval import CASE_KINDS, EVALUATION_CASES, evaluation_passages, run_evaluation


def topic_document(paragraphs=40):
    topics = ["glaciers retreat", "volcanic soil", "coral reefs", "desert rainfall", "river deltas"]
    parts = []
    for index in range(paragraphs):
        topic = topics[index % len(topics)]
        parts.append(f"Section {index}. Notes about {topic}. " + "General filler sentence about field work. " * 25)
    parts.append("The secret launch code for the probe is AURORA-7, recorded by the mission archivist.")
    return "\n\n".join(parts)


class ChunkingAndRankingTests(unittest.TestCase):
    def test_chunks_respect_paragraphs_and_the_size_limit(self):
        text = "Short one.\n\nShort two.\n\n" + "word " * 700
        chunks = chunk_document(text, max_chars=1200)
        self.assertEqual(chunks[0].split("\n\n")[:2], ["Short one.", "Short two."])
        self.assertTrue(all(len(chunk) <= 1200 for chunk in chunks))
        self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(text.split()))

    def test_tokenizer_drops_stopwords_folds_case_accents_and_suffixes(self):
        self.assertEqual(tokenize("The Voices were synthesised in Zürich"), ["voice", "synthesis", "zurich"])

    def test_bm25_prefers_rare_matching_terms(self):
        index = Bm25Index(["the cat sat on the mat", "a dog barked", "the cat chased the dog through the cat flap"])
        self.assertEqual(index.rank("cat flap")[0], 2)
        self.assertEqual(index.rank("barking dogs"), [1, 2])
        self.assertEqual(index.rank("unrelated words"), [])

    def test_reciprocal_rank_fusion_rewards_agreement(self):
        self.assertEqual(fuse_rankings([[0, 1, 2], [1, 0, 2], [1, 2, 0]])[0], 1)

    def test_selection_fits_the_budget_and_keeps_document_order(self):
        passages = ["a" * 100, "b" * 500, "c" * 100, "d" * 100]
        self.assertEqual(select_passages(passages, [3, 1, 0, 2], budget_chars=260), [0, 3])

    def test_vector_index_is_cached_by_passages_and_model(self):
        calls = []

        def embed(text):
            calls.append(text)
            return [1.0, float(len(text))]

        with tempfile.TemporaryDirectory() as root:
            first = VectorIndex.build(["one", "three"], embed, cache_dir=Path(root), cache_key="m1")
            again = VectorIndex.build(["one", "three"], embed, cache_dir=Path(root), cache_key="m1")
            VectorIndex.build(["one", "three"], embed, cache_dir=Path(root), cache_key="m2")
            self.assertEqual(first.vectors, again.vectors)
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(list(Path(root).glob("*.json"))), 2)
            saved = json.loads(next(Path(root).glob("*.json")).read_text())
            self.assertEqual(saved["chunks"], ["one", "three"])


class AssistantRetrievalTests(unittest.TestCase):
    def test_long_documents_send_only_matching_passages_for_cloud_providers(self):
        config = LlmConfig(provider="openai", api_key="k")
        context = retrieve_relevant_context(config, "What is the probe launch code?", topic_document())
        self.assertLessEqual(len(context), context_budget_chars(config) + 200)
        self.assertIn("AURORA-7", context)
        self.assertNotIn("[Passage 1]\nSection 0", context.split("AURORA-7")[0][-2000:])

    def test_vague_questions_fall_back_to_the_opening_passages(self):
        context = retrieve_relevant_context(LlmConfig(provider="ollama"), "Tell me more?", topic_document())
        self.assertTrue(context.startswith("[Passage 1]\nSection 0."))

    def test_short_documents_are_sent_whole(self):
        context = retrieve_relevant_context(LlmConfig(), "anything", "First.\n\nSecond.")
        self.assertEqual(context, "[Passage 1]\nFirst.\n\nSecond.")

    def test_embedded_budget_follows_the_context_window(self):
        small = LlmConfig(provider="embedded_llama_cpp", context_size=2048, max_tokens=512)
        large = LlmConfig(provider="embedded_llama_cpp", context_size=32768)
        self.assertEqual(context_budget_chars(small), (2048 - 512 - 400) * 3)
        self.assertEqual(context_budget_chars(large), 6000)
        self.assertEqual(context_budget_chars(LlmConfig(provider="embedded_llama_cpp", context_size=512)), 1000)

    def test_llama_cpp_fuses_vectors_and_falls_back_to_keywords(self):
        document = topic_document()
        config = LlmConfig(provider="llama_cpp", endpoint="http://127.0.0.1:9931/v1")

        def embed(text):
            # A toy embedding that only "understands" the probe passage.
            return [1.0, 0.0] if "probe" in text.lower() or "launch" in text.lower() else [0.0, 1.0]

        with tempfile.TemporaryDirectory() as cache, patch.dict("os.environ", {"SONARA_CACHE_DIR": cache}):
            fused = retrieve_relevant_context(config, "launch code", document, embed=embed)
            self.assertIn("AURORA-7", fused)
            self.assertTrue(list((Path(cache) / "embeddings").glob("*.json")))

            def broken(_text):
                raise RuntimeError("Local embeddings unavailable")

            with patch("sys.stderr"):
                fallback = retrieve_relevant_context(config, "probe launch code", document, embed=broken)
        self.assertIn("AURORA-7", fallback)

    @patch("llm_client.chat_completion", return_value="answer")
    def test_every_provider_gets_cited_passages(self, mock_chat):
        for provider in ("ollama", "openai", "embedded_llama_cpp"):
            ask_document(LlmConfig(provider=provider), "What is the probe launch code?", topic_document())
            prompt = mock_chat.call_args.args[1][-1]["content"]
            self.assertIn("AURORA-7", prompt, provider)
            self.assertIn("[Passage ", prompt)


class LongSummaryTests(unittest.TestCase):
    def test_short_documents_use_one_request(self):
        with patch("llm_client.chat_completion", return_value="summary") as chat:
            self.assertEqual(summarize_document(LlmConfig(), "A short document."), "summary")
        self.assertEqual(chat.call_count, 1)

    def test_long_documents_are_summarised_by_sections_then_combined(self):
        document = topic_document(paragraphs=30)
        prompts = []

        def fake_chat(config, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            return "combined summary" if "section summaries" in prompts[-1] else f"partial {len(prompts)}"

        with patch("llm_client.chat_completion", side_effect=fake_chat):
            result = summarize_document(LlmConfig(), document)
        sections = [prompt for prompt in prompts if prompt.startswith("This is section")]
        self.assertGreater(len(sections), 1)
        self.assertTrue(result.startswith("combined summary"))
        self.assertIn("Section 1: partial 1", prompts[-1])
        self.assertIn("AURORA-7", sections[-1])  # the end of the document is covered
        self.assertNotIn("Summary based on", result)  # every section fitted
        self.assertTrue(all(len(prompt) < 6000 + 400 for prompt in prompts))

    def test_very_long_documents_report_their_coverage(self):
        document = topic_document(paragraphs=200)
        with patch("llm_client.chat_completion", return_value="text") as chat:
            result = summarize_document(LlmConfig(), document, "takeaways")
        self.assertEqual(chat.call_count, 8 + 1)
        self.assertRegex(result, r"Summary based on 8 of \d+ sections \(about \d+% of the text\)")

    def test_time_budget_stops_section_requests(self):
        ticks = iter(range(0, 10_000, 100))
        with patch("llm_client.chat_completion", return_value="text") as chat:
            result = summarize_document(LlmConfig(), topic_document(paragraphs=60), clock=lambda: next(ticks))
        self.assertLess(chat.call_count, 9)
        self.assertIn("Summary based on", result)


class RetrievalEvaluationTests(unittest.TestCase):
    def test_metrics(self):
        passages = ["alpha facts", "beta facts", "gamma facts"]
        report = evaluate_retrieval(
            passages,
            [RetrievalCase("q1", "alpha"), RetrievalCase("q2", "gamma")],
            lambda question: [0, 1, 2] if question == "q1" else [1, 0, 2],
            ks=(1, 3),
        )
        self.assertEqual(report["recall@1"], 0.5)
        self.assertEqual(report["recall@3"], 1.0)
        self.assertEqual(report["mrr"], round((1 + 1 / 3) / 2, 3))

    def test_bundled_set_meets_the_keyword_baseline(self):
        # A regression floor for BM25 on the bundled evaluation set; see
        # docs/BENCHMARKS.md §7 for the measured numbers. Paraphrases are BM25's
        # known weak spot and are reported, not asserted.
        passages = evaluation_passages()
        self.assertGreaterEqual(len(passages), 10)
        report = run_evaluation(passages, EVALUATION_CASES, CASE_KINDS)["bm25"]
        for kind in ("lexical", "numeric"):
            self.assertEqual(report["by_kind"][kind]["recall@3"], 1.0, (kind, report["misses"]))
        self.assertGreaterEqual(report["mrr"], 0.8)

    def test_every_case_has_exactly_one_answering_passage(self):
        passages = evaluation_passages()
        for case in EVALUATION_CASES:
            matches = [p for p in passages if case.answer_phrase.lower() in p.lower()]
            self.assertEqual(len(matches), 1, case)


if __name__ == "__main__":
    unittest.main()
