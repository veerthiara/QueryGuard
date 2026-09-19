"""Deterministic tests for Ollama request adaptation without a running server."""

import pytest

from evals.queryguard_evals.ollama_provider import (
    OllamaProvider,
    OllamaProviderError,
    _extract_candidate,
    _render_messages,
    _request_payload,
)

pytestmark = pytest.mark.evals


def test_message_rendering_preserves_existing_prompt_roles():
    prompt = _render_messages(
        (
            {"role": "system", "content": "schema"},
            {"role": "user", "content": "question"},
        )
    )

    assert prompt == "SYSTEM:\nschema\n\nUSER:\nquestion"


def test_provider_rejects_invalid_local_configuration():
    with pytest.raises(ValueError, match="model"):
        OllamaProvider("   ")
    with pytest.raises(ValueError, match="timeout"):
        OllamaProvider("local-model", timeout_seconds=0)


def test_qwen_thinking_json_is_used_when_ollama_response_is_empty():
    assert (
        _extract_candidate({"response": "", "thinking": '{"sql": "SELECT 1"}'})
        == '{"sql": "SELECT 1"}'
    )

    with pytest.raises(OllamaProviderError, match="generated text"):
        _extract_candidate({"response": "", "thinking": ""})


def test_request_payload_uses_the_existing_generated_sql_shape():
    payload = _request_payload("local-model", "prompt", 0.0)

    assert payload["format"] != "json"
    assert payload["options"] == {"temperature": 0.0}
