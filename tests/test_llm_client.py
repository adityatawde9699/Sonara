import unittest
from unittest.mock import MagicMock, patch
import json
import io
import os
import threading
import time

from llm_client import (
    LlmConfig,
    chat_completion,
    test_connection,
    ask_document,
    summarize_document,
    enhance_narration_script,
    rpc_handler,
    EmbeddedModelManager,
    _embedding,
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

    def test_embedded_provider_is_distinct_from_legacy_server_provider(self):
        embedded = LlmConfig.from_dict({"provider": "embedded_llama_cpp", "modelPath": "/models/test.gguf"})
        server = LlmConfig.from_dict({"provider": "llama_cpp", "endpoint": "http://127.0.0.1:9931/v1"})
        self.assertEqual(embedded.model_path, "/models/test.gguf")
        self.assertEqual(embedded.context_size, 4096)
        self.assertEqual(embedded.idle_timeout_seconds, 300)
        self.assertEqual(server.endpoint, "http://127.0.0.1:9931/v1")

    @patch("llm_client._embedded_model_manager.complete", return_value="direct answer")
    @patch("urllib.request.urlopen")
    def test_embedded_provider_uses_direct_runtime_not_http(self, mock_urlopen, mock_complete):
        cfg = LlmConfig(provider="embedded_llama_cpp", model_path="/tmp/example.gguf")
        result = chat_completion(cfg, [{"role": "user", "content": "hello"}])
        self.assertEqual(result, "direct answer")
        mock_complete.assert_called_once()
        mock_urlopen.assert_not_called()

    @patch("llm_client.chat_completion", return_value="document answer")
    @patch("llm_client.retrieve_relevant_context")
    def test_embedded_chat_uses_bounded_direct_context_without_http_embeddings(self, mock_retrieve, mock_chat):
        cfg = LlmConfig(provider="embedded_llama_cpp", model_path="/tmp/example.gguf")
        answer = ask_document(cfg, "What matters?", "A representative document passage.")
        self.assertEqual(answer, "document answer")
        mock_retrieve.assert_not_called()
        self.assertIn("A representative document passage.", mock_chat.call_args.args[1][-1]["content"])

    @patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_legacy_embedding_error_explains_server_and_embedded_options(self, _mock_urlopen):
        config = LlmConfig(provider="llama_cpp", endpoint="http://127.0.0.1:9931/v1")
        with self.assertRaises(RuntimeError) as raised:
            _embedding(config, "query")
        self.assertIn("legacy HTTP llama.cpp provider", str(raised.exception))
        self.assertIn("select 'llama.cpp embedded'", str(raised.exception))

    def test_embedded_manager_loads_lazily_and_reuses_single_instance(self):
        import tempfile
        from pathlib import Path
        model = MagicMock()
        model.create_chat_completion.return_value = {"choices": [{"message": {"content": "local answer"}}]}
        factory = MagicMock(return_value=model)
        manager = EmbeddedModelManager(factory)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "small.gguf"
            path.write_bytes(b"GGUFtest model placeholder")
            config = LlmConfig(provider="embedded_llama_cpp", model_path=str(path), idle_timeout_seconds=3600)
            self.assertEqual(manager.status()["state"], "UNLOADED")
            self.assertEqual(manager.complete(config, [{"role": "user", "content": "one"}]), "local answer")
            self.assertEqual(manager.complete(config, [{"role": "user", "content": "two"}]), "local answer")
            self.assertEqual(factory.call_count, 1)
            self.assertTrue(factory.call_args.kwargs["use_mmap"])
            self.assertFalse(factory.call_args.kwargs["use_mlock"])
            self.assertEqual(model.create_chat_completion.call_count, 2)
            manager.shutdown()
        model.close.assert_called_once()

    def test_embedded_manager_serializes_concurrent_first_use(self):
        import tempfile
        from pathlib import Path
        model = MagicMock()
        model.create_chat_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}
        def construct(**_kwargs):
            time.sleep(0.02)
            return model
        factory = MagicMock(side_effect=construct)
        manager = EmbeddedModelManager(factory)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "shared.gguf"
            path.write_bytes(b"GGUFplaceholder")
            config = LlmConfig(provider="embedded_llama_cpp", model_path=str(path), idle_timeout_seconds=3600)
            failures = []
            def infer():
                try:
                    manager.complete(config, [{"role": "user", "content": "hello"}])
                except Exception as exc:  # surfaced after joining worker threads
                    failures.append(exc)
            threads = [threading.Thread(target=infer) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(failures, [])
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(model.create_chat_completion.call_count, 2)
            manager.shutdown()

    @unittest.skipUnless(os.environ.get("SONARA_LLM_TEST_MODEL"), "set SONARA_LLM_TEST_MODEL to opt in to real GGUF inference")
    def test_real_embedded_gguf_inference_reuses_and_reloads_without_server(self):
        path = os.environ["SONARA_LLM_TEST_MODEL"]
        manager = EmbeddedModelManager()
        config = LlmConfig(provider="embedded_llama_cpp", model_path=path, context_size=1024,
                           max_tokens=32, temperature=0.1, idle_timeout_seconds=3600)
        try:
            first = manager.complete(config, [{"role": "user", "content": "Reply with the word ready."}], max_tokens=16)
            retained_model = manager._model
            second = manager.complete(config, [{"role": "user", "content": "Reply with the word ready."}], max_tokens=16)
            self.assertTrue(first)
            self.assertTrue(second)
            self.assertIs(manager._model, retained_model)
            manager._expire()
            self.assertEqual(manager.status()["state"], "UNLOADED")
            third = manager.complete(config, [{"role": "user", "content": "Reply with the word ready."}], max_tokens=16)
            self.assertTrue(third)
        finally:
            manager.shutdown()

    def test_embedded_manager_validates_model_path_before_loading(self):
        manager = EmbeddedModelManager(MagicMock())
        config = LlmConfig(provider="embedded_llama_cpp")
        with self.assertRaisesRegex(RuntimeError, "Choose a local GGUF"):
            manager.complete(config, [{"role": "user", "content": "hello"}])
        self.assertEqual(manager.status()["state"], "UNLOADED")

    def test_embedded_manager_reports_missing_runtime_actionably(self):
        import tempfile
        import sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "model.gguf"
            path.write_bytes(b"GGUFplaceholder")
            manager = EmbeddedModelManager()
            config = LlmConfig(provider="embedded_llama_cpp", model_path=str(path))
            with patch.dict(sys.modules, {"llama_cpp": None}):
                with self.assertRaisesRegex(RuntimeError, "Install Sonara's optional llama-cpp-python"):
                    manager.complete(config, [{"role": "user", "content": "hello"}])
            self.assertEqual(manager.status()["state"], "FAILED")

    def test_embedded_inference_failure_keeps_manager_recoverable(self):
        import tempfile
        from pathlib import Path
        model = MagicMock()
        model.create_chat_completion.side_effect = [ValueError("native failure"), {"choices": [{"message": {"content": "recovered"}}]}]
        manager = EmbeddedModelManager(MagicMock(return_value=model))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "model.gguf"
            path.write_bytes(b"GGUFplaceholder")
            config = LlmConfig(provider="embedded_llama_cpp", model_path=str(path), idle_timeout_seconds=3600)
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                manager.complete(config, [{"role": "user", "content": "private prompt"}])
            self.assertEqual(manager.complete(config, [{"role": "user", "content": "again"}]), "recovered")
            self.assertNotIn("private prompt", manager.status()["lastError"])
            manager.shutdown()

    def test_embedded_manager_idle_expiration_unloads_after_request(self):
        import tempfile
        from pathlib import Path
        model = MagicMock()
        model.create_chat_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}
        manager = EmbeddedModelManager(MagicMock(return_value=model))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "tiny.gguf"
            path.write_bytes(b"GGUFplaceholder")
            config = LlmConfig(provider="embedded_llama_cpp", model_path=str(path), idle_timeout_seconds=3600)
            manager.complete(config, [{"role": "user", "content": "hello"}])
            self.assertEqual(manager.status()["state"], "IDLE")
            manager._expire()
            self.assertEqual(manager.status()["state"], "UNLOADED")
            manager.complete(config, [{"role": "user", "content": "again"}])
            self.assertEqual(manager._model is not None, True)
            manager.shutdown()

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

            direct_file = tmp_path / "sample.txt"
            direct_file.write_text("Direct file content.", encoding="utf-8")
            res_file = rpc_handler({
                "action": "get_document_text",
                "path": str(direct_file),
            })
            self.assertTrue(res_file["ok"])
            self.assertEqual(res_file["text"], "Direct file content.")


if __name__ == "__main__":
    unittest.main()

