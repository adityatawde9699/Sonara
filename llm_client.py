"""Sonara LLM client for embedded llama.cpp, local HTTP, and cloud providers.

HTTP providers use standard-library urllib/json. The optional llama-cpp-python native
runtime is imported lazily only when an embedded GGUF request needs it.
"""

from __future__ import annotations

import json
import hashlib
import ipaddress
import math
import os
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434/v1"
DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_LLAMA_CPP_ENDPOINT = "http://127.0.0.1:9931/v1"
DEFAULT_EMBEDDED_MODEL_DIRECTORY = Path.home() / ".cache" / "sonara" / "models"


@dataclass(frozen=True)
class LlmConfig:
    provider: str = "ollama"  # embedded_llama_cpp is direct inference; llama_cpp is legacy HTTP.
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT  # e.g. "http://localhost:11434/v1"
    model: str = "llama3.2"  # e.g. "llama3.2", "gpt-4o-mini", "gemini-1.5-flash"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    embedding_model: str = ""
    embedding_endpoint: str = ""
    model_path: str = ""
    model_directory: str = ""
    context_size: int = 4096
    threads: int = 0
    batch_size: int = 512
    idle_timeout_seconds: int = 300

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmConfig:
        provider = str(data.get("provider", "ollama")).lower()
        default_endpoint = DEFAULT_OLLAMA_ENDPOINT
        default_model = "llama3.2"

        if provider == "openai":
            default_endpoint = DEFAULT_OPENAI_ENDPOINT
            default_model = "gpt-4o-mini"
        elif provider == "gemini":
            default_endpoint = DEFAULT_GEMINI_ENDPOINT
            default_model = "gemini-1.5-flash"
        elif provider == "llama_cpp":
            default_endpoint = DEFAULT_LLAMA_CPP_ENDPOINT
            default_model = "local-model"
        elif provider == "embedded_llama_cpp":
            default_endpoint = ""
            default_model = "GGUF model"

        endpoint = str(data.get("endpoint") or default_endpoint).rstrip("/")
        model = str(data.get("model") or default_model)
        api_key = str(data.get("apiKey") or data.get("api_key") or "")
        temperature = float(data.get("temperature", 0.7))
        max_tokens = int(data.get("maxTokens") or data.get("max_tokens") or 1024)
        embedding_model = str(data.get("embeddingModel") or data.get("embedding_model") or "")
        embedding_endpoint = str(data.get("embeddingEndpoint") or data.get("embedding_endpoint") or "")
        model_path = str(data.get("modelPath") or data.get("model_path") or "").strip()
        model_directory = str(data.get("modelDirectory") or data.get("model_directory") or "").strip()
        context_size = _bounded_int(data.get("contextSize", data.get("context_size", 4096)), 4096, 512, 131072)
        threads = _bounded_int(data.get("threads", data.get("nThreads", 0)), 0, 0, 256)
        batch_size = _bounded_int(data.get("batchSize", data.get("batch_size", 512)), 512, 32, 8192)
        idle_timeout_seconds = _bounded_int(data.get("idleTimeoutSeconds", data.get("idle_timeout_seconds", 300)), 300, 0, 86400)

        return cls(
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            embedding_model=embedding_model,
            embedding_endpoint=embedding_endpoint,
            model_path=model_path,
            model_directory=model_directory,
            context_size=context_size,
            threads=threads,
            batch_size=batch_size,
            idle_timeout_seconds=idle_timeout_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "apiKey": self.api_key,
            "temperature": self.temperature,
            "maxTokens": self.max_tokens,
            "modelPath": self.model_path,
            "modelDirectory": self.model_directory,
            "contextSize": self.context_size,
            "threads": self.threads,
            "batchSize": self.batch_size,
            "idleTimeoutSeconds": self.idle_timeout_seconds,
        }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def strip_thinking_tags(text: str) -> str:
    """Strip <think>...</think> reasoning blocks, unclosed thinking tags, and stray artifacts."""
    if not text:
        return ""
    import re

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if "<think>" in cleaned:
        before = cleaned.split("<think>", 1)[0].strip()
        cleaned = before if before else re.sub(r"</?think>", "", cleaned).strip()
    return re.sub(r"</?think>", "", cleaned).strip()


class EmbeddedModelManager:
    """Own one lazily-loaded llama-cpp-python model and serialize its use."""

    def __init__(self, model_factory: Any = None):
        import threading
        self._lock = threading.RLock()
        self._model: Any = None
        self._signature: tuple[Any, ...] | None = None
        self._state = "UNLOADED"
        self._last_error = ""
        self._last_used = 0.0
        self._timer: Any = None
        self._model_factory = model_factory

    def _validated_path(self, config: LlmConfig) -> Path:
        if not config.model_path:
            raise RuntimeError("Choose a local GGUF model file in Settings to use embedded llama.cpp.")
        path = Path(config.model_path).expanduser()
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(f"GGUF model file was not found or is inaccessible: {config.model_path}") from exc
        if not path.is_file() or path.suffix.lower() != ".gguf":
            raise RuntimeError("The selected model must be a readable .gguf file.")
        if not os.access(path, os.R_OK):
            raise RuntimeError(f"GGUF model file is not readable: {path}")
        try:
            with path.open("rb") as model_file:
                if model_file.read(4) != b"GGUF":
                    raise RuntimeError("The selected file does not have a GGUF model header.")
        except OSError as exc:
            raise RuntimeError(f"GGUF model file could not be read: {path}") from exc
        return path

    def _factory(self) -> Any:
        if self._model_factory is not None:
            return self._model_factory
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "Embedded llama.cpp runtime is unavailable. Install Sonara's optional llama-cpp-python dependency."
            ) from exc
        return Llama

    def _signature_for(self, config: LlmConfig, path: Path) -> tuple[Any, ...]:
        return (str(path), config.context_size, config.threads, config.batch_size)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _unload_locked(self) -> None:
        model, self._model = self._model, None
        self._signature = None
        if model is None:
            self._state = "UNLOADED"
            return
        self._state = "UNLOADING"
        try:
            close = getattr(model, "close", None)
            if callable(close):
                close()
            del model
            import gc
            gc.collect()
            self._state = "UNLOADED"
            self._last_error = ""
        except Exception as exc:
            self._state = "UNLOADED"
            self._last_error = f"Model release failed ({type(exc).__name__})."
            self._log_event("release_failed", type(exc).__name__)

    def _schedule_unload_locked(self, timeout: int) -> None:
        self._cancel_timer()
        if timeout <= 0 or self._model is None:
            self._state = "IDLE" if self._model is not None else "UNLOADED"
            return
        self._state = "IDLE"
        import threading
        self._timer = threading.Timer(timeout, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            if self._model is not None and self._state == "IDLE":
                self._unload_locked()

    def _ensure_loaded_locked(self, config: LlmConfig) -> Any:
        path = self._validated_path(config)
        signature = self._signature_for(config, path)
        if self._model is not None and self._signature != signature:
            self._unload_locked()
        if self._model is None:
            self._state = "LOADING"
            self._last_error = ""
            try:
                factory = self._factory()
                kwargs: dict[str, Any] = {
                    "model_path": str(path), "n_ctx": config.context_size,
                    "n_batch": config.batch_size, "use_mmap": True,
                    "use_mlock": False, "verbose": False,
                    "n_gpu_layers": -1,
                }
                if config.threads > 0:
                    kwargs["n_threads"] = config.threads
                    kwargs["n_threads_batch"] = config.threads
                self._model = factory(**kwargs)
                self._signature = signature
                self._state = "READY"
            except Exception as exc:
                self._model = None
                self._signature = None
                self._state = "FAILED"
                message = str(exc).strip()
                self._last_error = message[:500] if message else type(exc).__name__
                self._log_event("load_failed", type(exc).__name__)
                if isinstance(exc, RuntimeError) and "llama-cpp-python" in str(exc):
                    raise
                raise RuntimeError(f"Could not load GGUF model {path.name}: {self._last_error}") from exc
        return self._model

    def complete(self, config: LlmConfig, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        with self._lock:
            self._cancel_timer()
            model = self._ensure_loaded_locked(config)
            self._state = "IN_USE"
            try:
                result = model.create_chat_completion(
                    messages=messages,
                    temperature=config.temperature,
                    max_tokens=max_tokens or config.max_tokens,
                )
                choices = result.get("choices") or []
                if not choices:
                    raise RuntimeError("Embedded llama.cpp returned no completion choices.")
                content = str(choices[0].get("message", {}).get("content", ""))
                return strip_thinking_tags(content)
            except Exception as exc:
                self._last_error = f"Inference failed ({type(exc).__name__})."
                self._log_event("inference_failed", type(exc).__name__)
                if isinstance(exc, RuntimeError):
                    raise
                raise RuntimeError(f"Embedded llama.cpp inference failed: {type(exc).__name__}.") from exc
            finally:
                self._last_used = time.monotonic()
                self._schedule_unload_locked(config.idle_timeout_seconds)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self._state, "model": Path(self._signature[0]).name if self._signature else "",
                    "lastError": self._last_error}

    @staticmethod
    def _log_event(event: str, error_type: str) -> None:
        """Write only event and exception type; never record prompts, keys, or model output."""
        try:
            root = Path(os.environ.get("SONARA_CACHE_DIR", Path.home() / ".cache" / "sonara"))
            root.mkdir(parents=True, exist_ok=True)
            with (root / "llm-worker.log").open("a", encoding="utf-8") as log_file:
                log_file.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {event} {error_type}\n")
        except OSError:
            pass

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer()
            self._unload_locked()


_embedded_model_manager = EmbeddedModelManager()


def discover_gguf_models(config: LlmConfig) -> list[str]:
    """List only direct .gguf children in explicitly configured and standard Sonara model directories."""
    roots: list[Path] = []
    if config.model_directory:
        roots.append(Path(config.model_directory).expanduser())
    roots.extend([DEFAULT_EMBEDDED_MODEL_DIRECTORY, Path.home() / ".local" / "share" / "sonara" / "models", Path.home() / "Sonara" / "models"])
    found: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
            if resolved.is_dir():
                found.update(str(item.resolve()) for item in resolved.glob("*.gguf") if item.is_file() and os.access(item, os.R_OK))
        except (OSError, RuntimeError):
            continue
    if config.model_path:
        try:
            selected = Path(config.model_path).expanduser().resolve(strict=True)
            if selected.is_file() and selected.suffix.lower() == ".gguf" and os.access(selected, os.R_OK):
                found.add(str(selected))
        except (OSError, RuntimeError):
            pass
    return sorted(found)


def chat_completion(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float = 60.0,
    max_tokens: int | None = None,
) -> str:
    """Complete through the selected provider without changing the public client API."""
    if config.provider == "embedded_llama_cpp":
        return _embedded_model_manager.complete(config, messages, max_tokens=max_tokens)
    if config.provider in {"llama_cpp", "ollama"} and not _is_loopback_endpoint(config.endpoint):
        raise RuntimeError(f"{config.provider} provider only accepts a local loopback endpoint.")
    url = f"{config.endpoint}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Sonara-Desktop/0.1.0",
    }
    if config.api_key.strip():
        headers["Authorization"] = f"Bearer {config.api_key.strip()}"

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": max_tokens or config.max_tokens,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8")
            result = json.loads(raw_body)
            choices = result.get("choices")
            if not choices or not isinstance(choices, list):
                raise ValueError("LLM response did not contain choices")
            content = choices[0].get("message", {}).get("content", "")
            return strip_thinking_tags(content)
    except urllib.error.HTTPError as exc:
        err_msg = ""
        try:
            err_json = json.loads(exc.read().decode("utf-8"))
            err_msg = (
                err_json.get("error", {}).get("message")
                or err_json.get("message")
                or str(err_json)
            )
        except Exception:
            pass
        if exc.code == 401:
            raise RuntimeError(
                f"Authentication failed (HTTP 401). Verify your API key for {config.provider}."
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                f"Model or endpoint not found (HTTP 404). Check model name '{config.model}' and endpoint '{config.endpoint}'."
            ) from exc
        detail = f": {err_msg}" if err_msg else ""
        raise RuntimeError(f"LLM request failed with HTTP {exc.code}{detail}") from exc
    except urllib.error.URLError as exc:
        reason_str = str(exc.reason)
        if "Connection refused" in reason_str or "refused" in reason_str.lower():
            if "11434" in config.endpoint or "localhost" in config.endpoint:
                raise RuntimeError(
                    f"Could not connect to local LLM at {config.endpoint}. "
                    "Make sure Ollama is running ('ollama serve') or check Settings."
                ) from exc
        raise RuntimeError(f"Could not connect to {config.endpoint}: {reason_str}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"LLM request timed out after {timeout:g} seconds.") from exc


def test_connection(config: LlmConfig) -> dict[str, Any]:
    """Test connectivity and measure response latency."""
    started = time.monotonic()
    try:
        response = chat_completion(
            config,
            messages=[{"role": "user", "content": "Ping. Answer with single word: Pong."}],
            timeout=10.0,
            max_tokens=10,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "model": config.model,
            "provider": config.provider,
            "latencyMs": latency_ms,
            "response": response,
            "modelState": _embedded_model_manager.status()["state"] if config.provider == "embedded_llama_cpp" else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "model": config.model,
            "provider": config.provider,
            "modelState": _embedded_model_manager.status()["state"] if config.provider == "embedded_llama_cpp" else None,
        }


def ask_document(
    config: LlmConfig,
    question: str,
    context_text: str = "",
    history: Iterable[dict[str, str]] = (),
) -> str:
    """Answer a user question grounded in the open document text."""
    system_prompt = (
        "You are Sonara's AI Reading Assistant. You help users understand, explore, "
        "and discuss documents while they listen to the audiobook.\n"
        "Instructions:\n"
        "- Answer directly and concisely in 2 to 4 bullet points or short paragraphs.\n"
        "- Do NOT output internal thinking monologue, chain-of-thought, or <think> tags.\n"
        "- Ground your answer strictly in the provided document context."
    )
    if config.provider == "llama_cpp":
        system_prompt += " Cite supporting retrieved excerpts with their labels, such as [Passage 2]. Do not invent citations."

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content.strip() and role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    user_content = question
    if context_text.strip():
        if config.provider == "llama_cpp":
            context_text = retrieve_relevant_context(config, question, context_text)
        # Truncate context to ~6,000 characters to prevent high prefill latency
        safe_context = context_text.strip()[:6000]
        user_content = (
            f"--- DOCUMENT CONTEXT ---\n"
            f"{safe_context}\n"
            f"--- END DOCUMENT CONTEXT ---\n\n"
            f"User Question: {question}"
        )

    messages.append({"role": "user", "content": user_content})
    return chat_completion(config, messages, max_tokens=max(config.max_tokens, 1024))


def _is_loopback_endpoint(endpoint: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname or ""
        return parsed.scheme in {"http", "https"} and (
            host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        )
    except (ValueError, TypeError):
        return False


def _embedding(config: LlmConfig, text: str) -> list[float]:
    endpoint = config.embedding_endpoint or config.endpoint
    if not _is_loopback_endpoint(endpoint):
        raise RuntimeError("llama.cpp embedding endpoint must use localhost or a loopback IP address.")
    data = json.dumps({"model": config.embedding_model or config.model, "input": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint}/embeddings", data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Sonara-Desktop/0.1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        vector = payload["data"][0]["embedding"]
        if not isinstance(vector, list) or not vector:
            raise ValueError("empty embedding vector")
        return [float(value) for value in vector]
    except Exception as exc:
        raise RuntimeError(
            f"Local embeddings unavailable at {endpoint}. This is the legacy HTTP llama.cpp provider; "
            f"it requires a running server started with --embedding and a configured embedding model. "
            f"For direct inference without a server, select 'llama.cpp embedded' in Sonara Settings "
            f"(embedded chat currently uses bounded document context without vector embeddings). Details: {exc}"
        ) from exc


def retrieve_relevant_context(config: LlmConfig, question: str, document_text: str, *, top_k: int = 6) -> str:
    """Retrieve paragraph-aligned passages using a local llama.cpp embedding endpoint."""
    if not _is_loopback_endpoint(config.endpoint):
        raise RuntimeError("llama.cpp provider is restricted to a local endpoint.")
    chunks: list[str] = []
    current = ""
    for paragraph in (part.strip() for part in document_text.split("\n\n")):
        if not paragraph:
            continue
        words = paragraph.split()
        pieces: list[str] = []
        piece = ""
        for word in words:
            if piece and len(piece) + len(word) + 1 > 1200:
                pieces.append(piece)
                piece = ""
            piece = f"{piece} {word}".strip()
        if piece:
            pieces.append(piece)
        for part in pieces:
            if current and len(current) + len(part) + 2 > 1200:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{part}".strip()
    if current:
        chunks.append(current)
    if not chunks:
        return document_text[:12000]
    embedding_model = config.embedding_model or config.model
    embedding_endpoint = config.embedding_endpoint or config.endpoint
    use_nomic_prefixes = "nomic-embed-text" in embedding_model.lower()
    input_schema = "nomic-task-prefixes-v1" if use_nomic_prefixes else "plain-text-v1"
    digest = hashlib.sha256((embedding_endpoint + "\0" + embedding_model + "\0" + input_schema + "\0" + document_text).encode("utf-8")).hexdigest()
    root = Path(os.environ.get("SONARA_CACHE_DIR", Path.home() / ".cache" / "sonara")) / "embeddings"
    cache = root / f"{digest}.json"
    vectors: list[list[float]] = []
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("chunks") == chunks:
            vectors = saved.get("vectors", [])
    except (OSError, ValueError, AttributeError):
        pass
    if len(vectors) != len(chunks):
        vectors = [
            _embedding(config, f"search_document: {chunk}" if use_nomic_prefixes else chunk)
            for chunk in chunks
        ]
        root.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix(".tmp")
        temp.write_text(json.dumps({"chunks": chunks, "vectors": vectors}), encoding="utf-8")
        os.replace(temp, cache)
    query_text = f"search_query: {question}" if "nomic-embed-text" in embedding_model.lower() else question
    query = _embedding(config, query_text)
    def similarity(vector: list[float]) -> float:
        dot = sum(a * b for a, b in zip(query, vector))
        norm = math.sqrt(sum(a * a for a in query) * sum(b * b for b in vector))
        return dot / norm if norm else 0.0
    ranked = sorted(enumerate(vectors), key=lambda item: similarity(item[1]), reverse=True)[:top_k]
    return "\n\n".join(f"[Passage {index + 1}]\n{chunks[index]}" for index, _ in ranked)


def summarize_document(
    config: LlmConfig,
    doc_text: str,
    mode: str = "summary",
) -> str:
    """Generate an executive summary, key takeaways, or passage explanation."""
    safe_text = doc_text.strip()[:6000]
    token_budget = max(config.max_tokens, 1024)
    if mode == "takeaways":
        prompt = (
            "Extract exactly 3 to 5 key takeaways from the following document. "
            "Format as concise Markdown bullets with bold titles. "
            "Do NOT output <think> tags or preface — start directly with the bullet points:\n\n"
            f"{safe_text}"
        )
    elif mode == "explain_passage":
        prompt = (
            "Explain the central concepts of this document in 2 concise paragraphs. "
            "Do NOT output <think> tags or preface — provide only the clear explanation:\n\n"
            f"{safe_text}"
        )
    else:
        prompt = (
            "Provide a concise executive summary of this document in under 150 words. "
            "Include: 1) Brief Overview (2 sentences), 2) Top 3 Takeaways (bullet points). "
            "Do NOT output <think> tags or preface — start directly with the summary:\n\n"
            f"{safe_text}"
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are Sonara's executive document summarizer. "
                "Be direct, accurate, and concise. Never output internal chain-of-thought or <think> tags."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    return chat_completion(config, messages, max_tokens=token_budget)


def enhance_narration_script(
    config: LlmConfig,
    raw_text: str,
) -> dict[str, Any]:
    """Polish raw PDF/OCR text into natural, spoken prose and suggest pronunciation overrides."""
    prompt = (
        "You are an expert audio narration editor. Polish the following raw document passage "
        "into natural spoken English suitable for TTS narration. "
        "Rules:\n"
        "1. Remove raw PDF artifacts (running headers, broken line wraps, footnote indices).\n"
        "2. Spell out or expand abbreviations and equations for natural listening.\n"
        "3. Keep the original wording and meaning accurate — do not summarize.\n"
        "4. If there are proper names or loanwords that an English reader might mispronounce, "
        "provide phonetic substitutions in suggested_overrides.\n\n"
        "Respond ONLY with a JSON object in this exact format:\n"
        "{\n"
        '  "spoken_text": "polished text ready for speech",\n'
        '  "notes": ["short note of changes made"],\n'
        '  "suggested_overrides": [{"source": "Word", "spoken": "PhoneticSpelling"}]\n'
        "}\n\n"
        f"Text to polish:\n{raw_text[:4000]}"
    )

    messages = [
        {"role": "system", "content": "You are a professional audio narration script editor. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    raw_response = chat_completion(config, messages, max_tokens=1500)
    # Extract JSON block if surrounded by markdown code fences
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "spoken_text": raw_text,
            "notes": ["LLM returned non-JSON output; using original text"],
            "suggested_overrides": [],
        }


def extract_text_from_target(target_path: str) -> dict[str, Any]:
    """Read plain text from reader-output directory or directly extract from a document file."""
    from pathlib import Path

    p = Path(target_path).expanduser().resolve()
    if p.is_dir():
        txt_path = p / "document_text.txt"
        if txt_path.is_file():
            return {
                "ok": True,
                "text": txt_path.read_text(encoding="utf-8", errors="replace"),
                "source": str(txt_path),
            }
        json_path = p / "extracted_document.json"
        if json_path.is_file():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                blocks = data.get("blocks", [])
                text = "\n\n".join(b.get("text", "") for b in blocks if b.get("text"))
                return {"ok": True, "text": text, "source": str(json_path)}
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"Failed reading extracted_document.json: {exc}",
                }
        return {"ok": False, "error": f"No document text found in directory {p}"}
    if p.is_file():
        if p.name == "document_text.txt" or p.suffix.lower() in (".txt", ".text", ".md"):
            return {
                "ok": True,
                "text": p.read_text(encoding="utf-8", errors="replace"),
                "source": str(p),
            }
        try:
            from sonara import extract_document

            doc = extract_document(p)
            return {"ok": True, "text": doc.text, "source": str(p)}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Failed extracting document text from {p}: {exc}",
            }
    return {"ok": False, "error": f"Path not found: {target_path}"}


def rpc_handler(request: dict[str, Any]) -> dict[str, Any]:
    """Process a single JSON-RPC style request dictionary and return a result dictionary."""
    action = request.get("action", "")
    config_data = request.get("config", {})
    config = LlmConfig.from_dict(config_data)

    if action == "test_connection":
        return test_connection(config)

    if action == "chat":
        question = str(request.get("question", ""))
        context = str(request.get("context", ""))
        history = request.get("history", [])
        answer = ask_document(config, question, context, history)
        return {"ok": True, "answer": answer}

    if action == "summarize":
        text = str(request.get("text", ""))
        mode = str(request.get("mode", "summary"))
        summary = summarize_document(config, text, mode)
        return {"ok": True, "summary": summary}

    if action == "enhance_narration":
        text = str(request.get("text", ""))
        enhancement = enhance_narration_script(config, text)
        return {"ok": True, "enhancement": enhancement}

    if action == "get_document_text":
        path = str(request.get("path", ""))
        return extract_text_from_target(path)

    if action == "model_status":
        if config.provider != "embedded_llama_cpp":
            return {"ok": True, "state": "NOT_APPLICABLE", "model": "", "lastError": ""}
        return {"ok": True, **_embedded_model_manager.status()}

    if action == "discover_models":
        return {"ok": True, "models": discover_gguf_models(config)}

    if action == "shutdown":
        _embedded_model_manager.shutdown()
        return {"ok": True, "state": "UNLOADED"}

    return {"ok": False, "error": f"Unknown LLM action: {action}"}


def main() -> int:
    """CLI entrypoint for testing and Tauri child-process RPC."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        # One owned child per Tauri application. Requests and responses are bounded JSON lines.
        try:
            for line in sys.stdin:
                payload: Any = None
                if len(line) > 4 * 1024 * 1024:
                    result = {"ok": False, "error": "LLM worker request exceeded the 4 MiB limit."}
                else:
                    try:
                        payload = json.loads(line)
                        result = rpc_handler(payload)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)[:1000]}
                sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                if isinstance(payload, dict) and payload.get("action") == "shutdown":
                    break
        finally:
            _embedded_model_manager.shutdown()
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "rpc":
        # Read JSON from stdin, write JSON to stdout
        try:
            payload = json.loads(sys.stdin.read())
            result = rpc_handler(payload)
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            return 0
        except Exception as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
            return 1

    print("Sonara LLM Client module. Use 'python -m llm_client rpc' or import as library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
