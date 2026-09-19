"""Evaluation-only adapter for Ollama's local HTTP generation endpoint."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaProviderError(RuntimeError):
    """Raised when a local Ollama request cannot provide one response string."""


_GENERATED_SQL_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sql": {"type": "string"},
        "referenced_tables": {"type": "array", "items": {"type": "string"}},
        "referenced_columns": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"]},
    },
    "required": ["sql"],
}


class OllamaProvider:
    """Adapt local Ollama generation to QueryGuard's existing provider protocol."""

    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.0,
        timeout_seconds: float = 120.0,
        endpoint: str = "http://127.0.0.1:11434/api/generate",
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint
        self.last_duration_ms: float | None = None

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        """Generate one strict JSON candidate through a local Ollama server."""

        started_at = time.perf_counter()
        try:
            return await asyncio.to_thread(self._request, _render_messages(messages))
        finally:
            self.last_duration_ms = (time.perf_counter() - started_at) * 1000

    def _request(self, prompt: str) -> str:
        payload = json.dumps(_request_payload(self.model, prompt, self.temperature)).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except (HTTPError, URLError, OSError) as exc:
            raise OllamaProviderError("Ollama request failed") from exc
        try:
            document: Any = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise OllamaProviderError("Ollama returned invalid HTTP JSON") from exc
        return _extract_candidate(document)


def _render_messages(messages: tuple[dict[str, str], ...]) -> str:
    """Preserve the existing prompt roles without depending on an Ollama SDK."""

    return "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)


def _request_payload(model: str, prompt: str, temperature: float) -> dict[str, object]:
    """Constrain Ollama output to QueryGuard's existing strict response contract."""

    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": _GENERATED_SQL_JSON_SCHEMA,
        "options": {"temperature": temperature},
    }


def _extract_candidate(document: object) -> str:
    """Use Ollama's normal response, or Qwen's thinking field when it holds JSON."""

    if not isinstance(document, dict):
        raise OllamaProviderError("Ollama returned a non-object HTTP JSON response")
    for key in ("response", "thinking"):
        candidate = document.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise OllamaProviderError("Ollama response did not contain generated text")
