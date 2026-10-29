"""Frozen multi-entry backend used by the Tauri child-process protocol."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Sequence


def dispatch(arguments: Sequence[str]) -> int:
    if not arguments:
        print("Sonara runtime requires a backend entry point.", file=sys.stderr)
        return 2

    if arguments[0] == "--self-check":
        return self_check()

    # Preserve Python's ``sys.executable -m piper`` behavior used by Sonara's
    # one-shot synthesis path when sys.executable is this frozen executable.
    if len(arguments) >= 2 and arguments[0] == "-m" and arguments[1] == "piper":
        original_argv = sys.argv
        sys.argv = ["piper", *arguments[2:]]
        try:
            try:
                runpy.run_module("piper", run_name="__main__", alter_sys=True)
            except SystemExit as error:
                return int(error.code or 0)
            return 0
        finally:
            sys.argv = original_argv

    entry = Path(arguments[0]).name.lower()
    forwarded = list(arguments[1:])
    if entry == "sonara.py":
        from sonara import main

        return main(forwarded)

    if entry == "llm_client.py":
        import llm_client

        return _run_with_argv(llm_client.main, entry, forwarded)

    if entry == "piper_worker.py":
        import piper_worker

        return _run_with_argv(piper_worker.main, entry, forwarded)

    print(f"Unknown Sonara runtime entry point: {entry}", file=sys.stderr)
    return 2


def self_check() -> int:
    """Load every included CPU inference package without loading model weights."""
    import importlib.metadata

    results: dict[str, object] = {}
    failures = False
    for distribution, module_name in (
        ("piper-tts", "piper"),
        ("onnxruntime", "onnxruntime"),
        ("kokoro-onnx", "kokoro_onnx"),
        ("llama-cpp-python", "llama_cpp"),
    ):
        try:
            module = __import__(module_name)
            version = importlib.metadata.version(distribution)
            details: dict[str, object] = {"available": True, "version": version}
            if module_name == "onnxruntime":
                details["executionProviders"] = module.get_available_providers()
            results[distribution] = details
        except Exception as error:
            failures = True
            results[distribution] = {"available": False, "error": str(error)[:500]}
    print(json.dumps({"ok": not failures, "runtimes": results}, sort_keys=True))
    return 1 if failures else 0


def _run_with_argv(main: object, name: str, arguments: list[str]) -> int:
    original_argv = sys.argv
    sys.argv = [name, *arguments]
    try:
        return int(main())  # type: ignore[operator]
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(dispatch(sys.argv[1:]))
