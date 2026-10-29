from __future__ import annotations

import contextlib
import io
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ENTRY_PATH = Path(__file__).resolve().parents[1] / "packaging" / "runtime_entry.py"
ENTRY_SPEC = importlib.util.spec_from_file_location("sonara_runtime_entry", ENTRY_PATH)
assert ENTRY_SPEC is not None and ENTRY_SPEC.loader is not None
runtime_entry = importlib.util.module_from_spec(ENTRY_SPEC)
ENTRY_SPEC.loader.exec_module(runtime_entry)


class RuntimeEntryTests(unittest.TestCase):
    def test_unknown_entry_fails_without_running_backend(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status = runtime_entry.dispatch(["unknown.py"])
        self.assertEqual(status, 2)
        self.assertIn("Unknown Sonara runtime entry point", errors.getvalue())

    def test_empty_entry_fails_with_actionable_message(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            status = runtime_entry.dispatch([])
        self.assertEqual(status, 2)
        self.assertIn("requires a backend entry point", errors.getvalue())

    def test_llm_child_receives_original_worker_arguments(self):
        original_argv = sys.argv
        with patch("llm_client.main", return_value=0) as worker:
            self.assertEqual(runtime_entry.dispatch(["/bundle/llm_client.py", "worker"]), 0)
        worker.assert_called_once_with()
        self.assertEqual(sys.argv, original_argv)

    def test_piper_child_receives_model_paths_and_restores_argv(self):
        original_argv = sys.argv
        with patch("piper_worker.main", return_value=0) as worker:
            self.assertEqual(
                runtime_entry.dispatch(["/tmp/_MEI/piper_worker.py", "voice.onnx", "voice.json"]),
                0,
            )
        worker.assert_called_once_with()
        self.assertEqual(sys.argv, original_argv)

    def test_frozen_runtime_preserves_python_module_invocation(self):
        original_argv = sys.argv
        with patch.object(runtime_entry.runpy, "run_module") as run_module:
            self.assertEqual(runtime_entry.dispatch(["-m", "piper", "-m", "voice"]), 0)
        run_module.assert_called_once_with("piper", run_name="__main__", alter_sys=True)
        self.assertEqual(sys.argv, original_argv)

    def test_frozen_runtime_returns_piper_cli_exit_status(self):
        original_argv = sys.argv
        with patch.object(runtime_entry.runpy, "run_module", side_effect=SystemExit(7)):
            self.assertEqual(runtime_entry.dispatch(["-m", "piper"]), 7)
        self.assertEqual(sys.argv, original_argv)


if __name__ == "__main__":
    unittest.main()
