"""Block-aware passages and the citations built from an answer."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import llm_client
from llm_client import LlmConfig, citations_for, cited_passage_numbers, rpc_handler
from retrieval import chunk_blocks


def block(block_id, text, page=1):
    return {"id": block_id, "text": text, "source": {"page": page}}


def rebuilt(passage, blocks):
    by_id = {b["id"]: b["text"] for b in blocks}
    return "\n\n".join(by_id[piece.block_id][piece.start:piece.end] for piece in passage.pieces)


class ChunkBlocksTests(unittest.TestCase):
    def test_every_passage_is_exact_slices_of_its_blocks(self):
        long = " ".join(f"Sentence {n} says something about the archive." for n in range(80))
        blocks = [block("b0", "Heading"), block("b1", "  A short paragraph.  "), block("b2", long, 2), block("b3", "Tail.", 3)]
        passages = chunk_blocks(blocks, max_chars=400)
        self.assertGreater(len(passages), 3)
        for passage in passages:
            self.assertEqual(passage.text, rebuilt(passage, blocks))
            self.assertLessEqual(len(passage.text), 400)
        # Short blocks merge; trimming drops the outer whitespace.
        self.assertEqual(passages[0].text, "Heading\n\nA short paragraph.")
        self.assertEqual(passages[0].pieces[1].start, 2)
        self.assertEqual(passages[0].page, 1)
        # A split block stays on its own page, and breaks at sentence ends.
        self.assertEqual(passages[1].page, 2)
        self.assertTrue(passages[1].text.endswith("archive."))

    def test_a_sentence_longer_than_the_limit_is_split_at_words(self):
        words = " ".join(["word"] * 300)
        passages = chunk_blocks([block("b0", words)], max_chars=100)
        self.assertTrue(all(len(p.text) <= 100 for p in passages))
        self.assertEqual(" ".join(p.text for p in passages), words)

    def test_malformed_blocks_are_skipped(self):
        passages = chunk_blocks([{"id": 3, "text": "x"}, {"id": "b1"}, block("b2", "Kept", page=0)])
        self.assertEqual([p.text for p in passages], ["Kept"])
        self.assertIsNone(passages[0].page)


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [block(f"b{n}", f"Paragraph {n} text.", page=n + 1) for n in range(3)]
        self.passages = chunk_blocks(self.blocks, max_chars=20)

    def test_labels_in_their_common_forms(self):
        answer = "Yes [Passage 2]. Also [Passages 1, 3] and [passage 2 and 1]."
        self.assertEqual(cited_passage_numbers(answer), [2, 1, 3])

    def test_only_passages_that_were_sent_are_cited(self):
        citations = citations_for("See [Passage 1] and [Passage 3] and [Passage 9].", self.passages, sent=[0, 1])
        self.assertEqual([c["passageIndex"] for c in citations], [0])
        self.assertEqual(citations[0]["page"], 1)
        self.assertEqual(citations[0]["spans"], [{"blockId": "b0", "start": 0, "end": 17}])
        self.assertEqual(citations[0]["excerpt"], "Paragraph 0 text.")

    def test_chat_with_a_session_directory_returns_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "extracted_document.json").write_text(json.dumps({"extractor": "Native DOCX reader", "blocks": self.blocks}))
            with mock.patch.object(llm_client, "chat_completion", return_value="It is in [Passage 2].") as chat:
                result = rpc_handler({"action": "chat", "config": {"provider": "ollama"}, "question": "Where?", "document": tmp})
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "It is in [Passage 2].")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["pageLabel"], "section")
        prompt = chat.call_args.args[1][-1]["content"]
        self.assertIn("[Passage 2]\nParagraph 1 text.", prompt)

    def test_a_missing_session_document_is_an_error_not_an_empty_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = rpc_handler({"action": "chat", "config": {"provider": "ollama"}, "question": "Q", "document": tmp})
        self.assertFalse(result["ok"])
        self.assertIn("no extracted document", result["error"])


if __name__ == "__main__":
    unittest.main()
