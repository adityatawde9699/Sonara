"""Sonara LLM client for embedded llama.cpp, local HTTP, and cloud providers.

HTTP providers use standard-library urllib/json. The optional llama-cpp-python native
runtime is imported lazily only when an embedded GGUF request needs it.
"""

from __future__ import annotations

import json
import ipaddress
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from retrieval import Bm25Index, VectorIndex, chunk_document, format_passages, fuse_rankings, select_passages


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
            from llama_runtime import import_llama

            Llama = import_llama()
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
    if config.provider not in HTTP_PROVIDERS:
        raise RuntimeError(f"Unsupported LLM provider: {config.provider!r}.")
    if config.provider in {"llama_cpp", "ollama"} and not _is_loopback_endpoint(config.endpoint):
        raise RuntimeError(f"{config.provider} provider only accepts a local loopback endpoint.")
    _require_safe_endpoint(config.endpoint)
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
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
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
        "- Ground your answer strictly in the provided document context.\n"
        "- Cite the excerpts you rely on by their labels, such as [Passage 2]. Do not invent citations.\n"
        "- If the excerpts do not contain the answer, say so instead of guessing."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content.strip() and role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    user_content = question
    if context_text.strip():
        # Retrieval picks the passages that fit the context budget, for every
        # provider; a short document fits whole.
        safe_context = retrieve_relevant_context(config, question, context_text)
        user_content = (
            f"--- DOCUMENT CONTEXT ---\n"
            f"{safe_context}\n"
            f"--- END DOCUMENT CONTEXT ---\n\n"
            f"User Question: {question}"
        )

    messages.append({"role": "user", "content": user_content})
    return chat_completion(config, messages, max_tokens=max(config.max_tokens, 1024))


HTTP_PROVIDERS = frozenset({"ollama", "llama_cpp", "openai", "gemini", "custom"})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so a credentialed request cannot be bounced to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise urllib.error.HTTPError(req.full_url, code, "Redirects are not followed", headers, fp)


# build_opener keeps only http(s) handlers we name; file:/ftp: handlers are omitted.
_NO_REDIRECT_OPENER = urllib.request.build_opener(
    _NoRedirect, urllib.request.HTTPHandler, urllib.request.HTTPSHandler
)


def _require_safe_endpoint(endpoint: str) -> None:
    """Allow https anywhere, but plain http only to loopback, so keys and text never cross the network in clear."""
    try:
        parsed = urllib.parse.urlparse(endpoint)
    except ValueError as exc:
        raise RuntimeError("LLM endpoint is not a valid URL.") from exc
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and _is_loopback_endpoint(endpoint):
        return
    raise RuntimeError("LLM endpoint must use https, or http only for localhost/loopback addresses.")


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
        with _NO_REDIRECT_OPENER.open(req, timeout=60) as response:
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


# Characters of document context per request. Larger prompts raise prefill
# latency sharply on CPU; small embedded contexts get less (see below).
CONTEXT_BUDGET_CHARS = 6000


def context_budget_chars(config: LlmConfig) -> int:
    """Context characters that fit the request, about 3 characters per token.

    An embedded model's window holds the prompt and the answer, so its budget
    shrinks with ``context_size``. Remote providers have large windows; the
    fixed budget there limits latency and how much text is sent.
    """
    if config.provider != "embedded_llama_cpp":
        return CONTEXT_BUDGET_CHARS
    answer_tokens = min(max(config.max_tokens, 256), config.context_size // 2)
    available = config.context_size - answer_tokens - 400  # instructions and history
    return max(1000, min(CONTEXT_BUDGET_CHARS, available * 3))


def _embedding_cache_dir() -> Path:
    return Path(os.environ.get("SONARA_CACHE_DIR", Path.home() / ".cache" / "sonara")) / "embeddings"


def _embedding_cache_budget() -> int:
    try:
        return max(1, int(os.environ.get("SONARA_EMBEDDING_CACHE_MAX_BYTES", 256 * 1024 * 1024)))
    except ValueError:
        return 256 * 1024 * 1024


def rank_passages(
    config: LlmConfig,
    question: str,
    passages: list[str],
    *,
    embed: Callable[[str], list[float]] | None = None,
) -> list[int]:
    """All passage indexes, best first.

    BM25 runs for every provider. With a local embedding server (the HTTP
    llama.cpp provider), the vector ranking is fused with it; if embeddings
    fail, BM25 alone is used and the reason goes to stderr. Passages that
    match nothing follow in document order, so a vague question ("what is
    this about?") still gets the opening passages.
    """
    rankings = [Bm25Index(passages).rank(question)]
    if config.provider == "llama_cpp":
        embed = embed or (lambda text: _embedding(config, text))
        model = config.embedding_model or config.model
        nomic = "nomic-embed-text" in model.lower()
        try:
            index = VectorIndex.build(
                passages, embed,
                cache_dir=_embedding_cache_dir(),
                cache_key="\0".join((config.embedding_endpoint or config.endpoint, model, "nomic-task-prefixes-v1" if nomic else "plain-text-v1")),
                document_prefix="search_document: " if nomic else "",
                max_cache_bytes=_embedding_cache_budget(),
            )
            rankings.append(index.rank(embed(f"search_query: {question}" if nomic else question)))
        except RuntimeError as exc:
            print(f"Sonara retrieval: using keyword ranking only. {exc}", file=sys.stderr)
    ranked = fuse_rankings(rankings) if len(rankings) > 1 else rankings[0]
    seen = set(ranked)
    return ranked + [index for index in range(len(passages)) if index not in seen]


def retrieve_relevant_context(
    config: LlmConfig,
    question: str,
    document_text: str,
    *,
    top_k: int = 6,
    budget_chars: int | None = None,
    embed: Callable[[str], list[float]] | None = None,
) -> str:
    """Labelled passages for the prompt: the whole document if it fits, else the best matches."""
    budget = budget_chars or context_budget_chars(config)
    passages = chunk_document(document_text)
    if not passages:
        return ""
    if sum(len(passage) + 20 for passage in passages) <= budget:
        return format_passages(passages, range(len(passages)))
    ranking = rank_passages(config, question, passages, embed=embed)
    return format_passages(passages, select_passages(passages, ranking, budget, top_k=top_k))


# Long documents are summarised map-reduce: each window of the document is
# summarised, then the partial summaries are combined. Both limits keep a
# summary inside the 300-second desktop RPC timeout on a local CPU model.
SUMMARY_MAX_SECTIONS = 8
SUMMARY_TIME_BUDGET_SECONDS = 240.0
SECTION_SUMMARY_TOKENS = 300

_SUMMARY_SYSTEM = (
    "You are Sonara's executive document summarizer. "
    "Be direct, accurate, and concise. Never output internal chain-of-thought or <think> tags."
)


def _final_summary_prompt(mode: str, text: str, *, from_sections: bool) -> str:
    source = "the following section summaries of one document, in order" if from_sections else "the following document"
    if mode == "takeaways":
        task = (
            f"Extract exactly 3 to 5 key takeaways from {source}. "
            "Format as concise Markdown bullets with bold titles. "
            "Do NOT output <think> tags or preface — start directly with the bullet points:"
        )
    elif mode == "explain_passage":
        task = (
            f"Explain the central concepts of {source} in 2 concise paragraphs. "
            "Do NOT output <think> tags or preface — provide only the clear explanation:"
        )
    else:
        task = (
            f"Provide a concise executive summary of {source} in under 150 words. "
            "Include: 1) Brief Overview (2 sentences), 2) Top 3 Takeaways (bullet points). "
            "Do NOT output <think> tags or preface — start directly with the summary:"
        )
    return f"{task}\n\n{text}"


def _section_windows(text: str, budget: int) -> list[str]:
    """Consecutive, paragraph-aligned windows of at most ``budget`` characters."""
    windows: list[str] = []
    current = ""
    for passage in chunk_document(text):
        if current and len(current) + len(passage) + 2 > budget:
            windows.append(current)
            current = ""
        current = f"{current}\n\n{passage}".strip()
    if current:
        windows.append(current)
    return windows


def _spread(items: list[str], count: int) -> list[int]:
    """``count`` indexes spread evenly over ``items``, first and last included."""
    if len(items) <= count:
        return list(range(len(items)))
    if count == 1:
        return [0]
    return sorted({round(i * (len(items) - 1) / (count - 1)) for i in range(count)})


def summarize_document(
    config: LlmConfig,
    doc_text: str,
    mode: str = "summary",
    *,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Executive summary, key takeaways, or an explanation of the document.

    A document that fits the context budget is summarised in one request.
    A longer one is split into windows; up to ``SUMMARY_MAX_SECTIONS``
    windows, spread across the document, are summarised and then combined.
    When windows had to be skipped, or the time budget ran out, the result
    says how much of the document it covers.
    """
    text = doc_text.strip()
    budget = context_budget_chars(config)
    token_budget = max(config.max_tokens, 1024)

    def complete(prompt: str, max_tokens: int, timeout: float) -> str:
        messages = [{"role": "system", "content": _SUMMARY_SYSTEM}, {"role": "user", "content": prompt}]
        return chat_completion(config, messages, max_tokens=max_tokens, timeout=timeout)

    if len(text) <= budget:
        return complete(_final_summary_prompt(mode, text, from_sections=False), token_budget, 60.0)

    windows = _section_windows(text, budget)
    chosen = _spread(windows, SUMMARY_MAX_SECTIONS)
    deadline = clock() + SUMMARY_TIME_BUDGET_SECONDS
    # Keep time for the combining request.
    reserve = SUMMARY_TIME_BUDGET_SECONDS / (len(chosen) + 1)
    partials: list[str] = []
    covered = 0
    for position, index in enumerate(chosen, start=1):
        remaining = deadline - clock() - reserve
        if partials and remaining < 5:
            break
        prompt = (
            f"This is section {position} of {len(chosen)} of a longer document. "
            "Summarise its main points in at most 120 words as plain sentences. "
            "Keep names, numbers and conclusions. No preface:\n\n"
            f"{windows[index]}"
        )
        partials.append(f"Section {position}: " + complete(prompt, SECTION_SUMMARY_TOKENS, max(5.0, min(60.0, remaining))))
        covered += len(windows[index])

    combined = "\n\n".join(partials)
    while len(combined) > budget and len(partials) > 1:
        # Rare: very verbose partials. Merge neighbours until they fit.
        partials = ["\n\n".join(partials[i:i + 2]) for i in range(0, len(partials), 2)]
        partials = [p[: budget // len(partials)] for p in partials]
        combined = "\n\n".join(partials)
    remaining = max(5.0, min(60.0, deadline - clock()))
    summary = complete(_final_summary_prompt(mode, combined[:budget], from_sections=True), token_budget, remaining)
    share = covered / max(1, sum(len(window) for window in windows))
    if share < 0.995:
        summary += (
            f"\n\n_Summary based on {len(partials)} of {len(windows)} sections "
            f"(about {share:.0%} of the text), spread across the document._"
        )
    return summary


# Rust caps RPC responses at 16 MiB; refuse larger text files before reading them.
MAX_DOCUMENT_TEXT_BYTES = 16 * 1024 * 1024


def _read_bounded_text(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_DOCUMENT_TEXT_BYTES:
        raise ValueError(f"{path.name} is {size} bytes, above the {MAX_DOCUMENT_TEXT_BYTES}-byte limit.")
    return path.read_text(encoding="utf-8", errors="replace")


def extract_text_from_target(target_path: str) -> dict[str, Any]:
    """Read plain text from reader-output directory or directly extract from a document file."""
    from pathlib import Path

    p = Path(target_path).expanduser().resolve()
    if p.is_dir():
        txt_path = p / "document_text.txt"
        if txt_path.is_file():
            try:
                return {"ok": True, "text": _read_bounded_text(txt_path), "source": str(txt_path)}
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": f"Failed reading {txt_path.name}: {exc}"}
        json_path = p / "extracted_document.json"
        if json_path.is_file():
            try:
                data = json.loads(_read_bounded_text(json_path))
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
            try:
                return {"ok": True, "text": _read_bounded_text(p), "source": str(p)}
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": f"Failed reading {p.name}: {exc}"}
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
        # Stdin EOF also ends the loop, but only once an in-flight request returns.
        from parent_watch import start_parent_watch

        start_parent_watch()
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
