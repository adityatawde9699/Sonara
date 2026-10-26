import unittest
from unittest.mock import MagicMock, patch
import json
import io

from llm_client import (
    LlmConfig,
    chat_completion,
    test_connection,
    ask_document,
    summarize_document,
    enhance_narration_script,
    rpc_handler,
)


class LlmClientTests(unittest.TestCase):
    def test_config_parsing_defaults(self):
        ollama_cfg = LlmConfig.from_dict({"provider": "ollama"})
        self.assertEqual(ollama_cfg.provider, "ollama")
        self.assertEqual(ollama_cfg.endpoint, "http://localhost:11434/v1")
        self.assertEqual(ollama_cfg.model, "llama3.2")
        self.assertEqual(ollama_cfg.api_key, "")

        openai_cfg = LlmConfig.from_dict({"provider": "openai", "apiKey": "sk-12345"})
        self.assertEqual(openai_cfg.provider, "openai")
        self.assertEqual(openai_cfg.endpoint, "https://api.openai.com/v1")
        self.assertEqual(openai_cfg.model, "gpt-4o-mini")
        self.assertEqual(openai_cfg.api_key, "sk-12345")

        gemini_cfg = LlmConfig.from_dict({"provider": "gemini", "apiKey": "gemini-key"})
        self.assertEqual(gemini_cfg.provider, "gemini")
        self.assertEqual(gemini_cfg.endpoint, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(gemini_cfg.model, "gemini-1.5-flash")

    def test_offline_connection_returns_actionable_error(self):
        # Point to an unused local port to simulate offline server
        cfg = LlmConfig(provider="ollama", endpoint="http://127.0.0.1:59999/v1", model="llama3.2")
        result = test_connection(cfg)
        self.assertFalse(result["ok"])
        self.assertIn("Could not connect", result["error"])

    @patch("urllib.request.urlopen")
    def test_chat_completion_parses_response(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "This is an answer from LLM."}}]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        cfg = LlmConfig(provider="ollama", endpoint="http://localhost:11434/v1", model="llama3.2")
        res = chat_completion(cfg, [{"role": "user", "content": "Hello"}])
        self.assertEqual(res, "This is an answer from LLM.")

    @patch("urllib.request.urlopen")
    def test_rpc_handler_routes_chat_and_summarize(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Summary text here."}}]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = rpc_handler({
            "action": "summarize",
            "config": {"provider": "ollama"},
            "text": "Some document text to summarize",
            "mode": "summary",
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["summary"], "Summary text here.")

    @patch("urllib.request.urlopen")
    def test_enhance_narration_script_extracts_json(self, mock_urlopen):
        mock_response = MagicMock()
        mock_json_content = """```json
{
  "spoken_text": "Summer holidays! Uh-jee smiled.",
  "notes": ["Replaced Ajji with phonetic spelling Uh-jee"],
  "suggested_overrides": [{"source": "Ajji", "spoken": "Uh-jee"}]
}
```"""
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": mock_json_content}}]
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        cfg = LlmConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test")
        enhanced = enhance_narration_script(cfg, "Summer holidays! Ajji smiled.")
        self.assertEqual(enhanced["spoken_text"], "Summer holidays! Uh-jee smiled.")
        self.assertEqual(len(enhanced["suggested_overrides"]), 1)
        self.assertEqual(enhanced["suggested_overrides"][0]["source"], "Ajji")

    def test_extract_text_from_target_and_rpc(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "document_text.txt").write_text("Extracted document text sample.", encoding="utf-8")
            res = rpc_handler({
                "action": "get_document_text",
                "path": str(tmp_path),
            })
            self.assertTrue(res["ok"])
            self.assertEqual(res["text"], "Extracted document text sample.")


if __name__ == "__main__":
    unittest.main()

