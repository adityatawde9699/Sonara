"""Universal OpenAI-compatible LLM client for local (Ollama) and cloud (Gemini, OpenAI) models.

Zero extra dependencies — uses standard-library urllib and json.
Supports Ollama (default local), OpenAI, Google Gemini (via OpenAI-compatible endpoint),
OpenRouter, LocalAI, and LM Studio.
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


@dataclass(frozen=True)
class LlmConfig:
    provider: str = "ollama"  # "ollama" | "llama_cpp" | "openai" | "gemini" | "custom"
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT  # e.g. "http://localhost:11434/v1"
    model: str = "llama3.2"  # e.g. "llama3.2", "gpt-4o-mini", "gemini-1.5-flash"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    embedding_model: str = ""
    embedding_endpoint: str = ""

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

        endpoint = str(data.get("endpoint") or default_endpoint).rstrip("/")
        model = str(data.get("model") or default_model)
        api_key = str(data.get("apiKey") or data.get("api_key") or "")
        temperature = float(data.get("temperature", 0.7))
        max_tokens = int(data.get("maxTokens") or data.get("max_tokens") or 1024)
        embedding_model = str(data.get("embeddingModel") or data.get("embedding_model") or "")
        embedding_endpoint = str(data.get("embeddingEndpoint") or data.get("embedding_endpoint") or "")

        return cls(
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            embedding_model=embedding_model,
            embedding_endpoint=embedding_endpoint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "apiKey": self.api_key,
            "temperature": self.temperature,
            "maxTokens": self.max_tokens,
        }


def chat_completion(
    config: LlmConfig,
    messages: list[dict[str, str]],
    *,
    timeout: float = 60.0,
    max_tokens: int | None = None,
) -> str:
    """Send an OpenAI-compatible /chat/completions request via standard library urllib."""
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
            return content.strip()
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
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "model": config.model,
            "provider": config.provider,
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
        "and discuss documents while they listen to the audiobook. "
        "Give clear, concise, well-structured answers using clean Markdown. "
        "Ground your answers in the provided document context whenever applicable. "
        "If the document doesn't mention the answer, clearly state so."
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
        # Truncate context to ~12,000 characters to prevent context window overflow
        safe_context = context_text.strip()[:12000]
        user_content = (
            f"--- DOCUMENT CONTEXT ---\n"
            f"{safe_context}\n"
            f"--- END DOCUMENT CONTEXT ---\n\n"
            f"User Question: {question}"
        )

    messages.append({"role": "user", "content": user_content})
    return chat_completion(config, messages)


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
            f"Local embeddings unavailable at {endpoint}. Start llama.cpp with --embedding "
            f"and configure its embedding model. Details: {exc}"
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
    safe_text = doc_text.strip()[:16000]
    if mode == "takeaways":
        prompt = (
            "Extract the 4 to 6 most important key takeaways from the following document. "
            "Format as clean Markdown bullet points with bold titles and brief actionable explanations.\n\n"
            f"{safe_text}"
        )
    elif mode == "explain_passage":
        prompt = (
            "Explain the following passage in clear, accessible language. "
            "Highlight the main idea, clarify difficult terminology, and explain context.\n\n"
            f"{safe_text}"
        )
    else:
        prompt = (
            "Provide a comprehensive, easy-to-listen summary of the following document. "
            "Include: 1) Executive Overview (2-3 sentences), 2) Core Themes / Narrative Arc, "
            "3) Key Takeaways. Use clean Markdown formatting.\n\n"
            f"{safe_text}"
        )

    messages = [
        {
            "role": "system",
            "content": "You are Sonara's executive document summarizer. Be accurate, informative, and concise.",
        },
        {"role": "user", "content": prompt},
    ]
    return chat_completion(config, messages)


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
            from document import extract_document

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

    return {"ok": False, "error": f"Unknown LLM action: {action}"}


def main() -> int:
    """CLI entrypoint for testing and Tauri child-process RPC."""
    import sys

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
