"""LLM client tests with mocked transport."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from data_dumps.llm_client import (
    LiteLLMClient,
    LLMClientError,
    LLMConfig,
    OllamaClient,
    _reject_litellm_ollama_model,
    _validate_url,
    make_client,
    narrate,
)


def test_llm_config_from_env(monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_LLM_ENABLED", "1")
    monkeypatch.setenv("DATA_DUMPS_LLM_MODEL", "test-model")
    cfg = LLMConfig.from_env()
    assert cfg.enabled
    assert cfg.model == "test-model"


def test_validate_url_rejects_remote():
    with pytest.raises(LLMClientError, match="not local"):
        _validate_url("http://api.openai.com", allow_remote=False)


def test_validate_url_allows_remote_when_flagged():
    _validate_url("http://api.openai.com", allow_remote=True)


def test_reject_litellm_ollama_model():
    with pytest.raises(LLMClientError, match="routes Ollama"):
        _reject_litellm_ollama_model("ollama/llama3")


def test_make_client_disabled():
    assert make_client(LLMConfig(enabled=False)) is None


def test_ollama_complete_mock():
    client = OllamaClient(LLMConfig(enabled=True, base_url="http://127.0.0.1:11434"))
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "Wrapped prose."}
    with patch("requests.post", return_value=mock_resp):
        text = client.complete("prompt", system="sys")
    assert text == "Wrapped prose."


def test_litellm_missing_extra():
    cfg = LLMConfig(enabled=True, provider="litellm", model="gpt-4o-mini")
    with pytest.raises(LLMClientError, match="LiteLLM not installed"):
        LiteLLMClient(cfg)


def test_narrate_disabled():
    text, cached = narrate({"filter_digest": "abc"}, config=LLMConfig(enabled=False))
    assert "LLM disabled" in text
    assert not cached


def test_narrate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DUMPS_ROOT", str(tmp_path))
    cfg = LLMConfig(enabled=True, model="test-model")
    client = OllamaClient(cfg)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "Cached story."}
    with patch("requests.get", return_value=MagicMock(status_code=200)):
        with patch("requests.post", return_value=mock_resp):
            with patch("data_dumps.llm_client.make_client", return_value=client):
                ctx = {"filter_digest": "digest123"}
                text1, c1 = narrate(ctx, config=cfg)
                text2, c2 = narrate(ctx, config=cfg)
    assert text1 == "Cached story."
    assert not c1
    assert c2
