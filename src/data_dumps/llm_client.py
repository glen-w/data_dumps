"""Local LLM client: Ollama default, optional LiteLLM extra."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import requests

from data_dumps.paths import data_root

LLMProvider = Literal["ollama", "litellm"]
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


class LLMClientError(Exception):
    """Configuration or transport error for LLM."""


class LLMClient(Protocol):
    provider: str

    def is_available(self) -> tuple[bool, str]:
        """Return (ok, message)."""

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        """Generate text from prompt."""


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    provider: LLMProvider = "ollama"
    model: str = "qwen2.5:7b"
    base_url: str = "http://127.0.0.1:11434"
    effort: Literal["light", "balanced"] = "balanced"
    allow_remote: bool = False
    api_base: str | None = None
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> LLMConfig:
        provider = os.environ.get("DATA_DUMPS_LLM_PROVIDER", "ollama")
        if provider not in ("ollama", "litellm"):
            provider = "ollama"
        effort = os.environ.get("DATA_DUMPS_LLM_EFFORT", "balanced")
        if effort not in ("light", "balanced"):
            effort = "balanced"
        return cls(
            enabled=os.environ.get("DATA_DUMPS_LLM_ENABLED", "0") == "1",
            provider=provider,  # type: ignore[arg-type]
            model=os.environ.get("DATA_DUMPS_LLM_MODEL", "qwen2.5:7b"),
            base_url=os.environ.get(
                "DATA_DUMPS_LLM_BASE_URL", "http://127.0.0.1:11434"
            ),
            effort=effort,  # type: ignore[arg-type]
            allow_remote=os.environ.get("DATA_DUMPS_LLM_ALLOW_REMOTE", "0") == "1",
            api_base=os.environ.get("DATA_DUMPS_LLM_API_BASE"),
            api_key=os.environ.get("DATA_DUMPS_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY"),
        )


def _validate_url(url: str, allow_remote: bool) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS and not allow_remote:
        raise LLMClientError(
            f"LLM URL host {host!r} is not local. "
            "Set DATA_DUMPS_LLM_ALLOW_REMOTE=1 to permit remote endpoints."
        )


def _reject_litellm_ollama_model(model: str) -> None:
    lowered = model.strip().lower()
    if lowered.startswith("ollama/") or lowered.startswith("ollama_chat/"):
        raise LLMClientError(
            f"Model {model!r} routes Ollama through LiteLLM; "
            "use provider 'ollama' instead."
        )


def _max_tokens(effort: str) -> int:
    return 400 if effort == "light" else 800


class OllamaClient:
    provider = "ollama"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        _validate_url(self.base_url, config.allow_remote)

    def is_available(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False, f"Ollama tags HTTP {resp.status_code}"
            return True, "Ollama reachable"
        except requests.RequestException as exc:
            return False, f"Ollama unreachable: {exc}"

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": _max_tokens(self.config.effort),
            },
        }
        if system:
            payload["system"] = system
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=120,
        )
        if resp.status_code != 200:
            raise LLMClientError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        text = data.get("response", "")
        if not text:
            raise LLMClientError("Ollama returned empty response")
        return text.strip()


class LiteLLMClient:
    provider = "litellm"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        _reject_litellm_ollama_model(config.model)
        if config.api_base:
            _validate_url(config.api_base, config.allow_remote)
        try:
            import litellm
        except ImportError:
            raise LLMClientError(
                "LiteLLM not installed. Run: uv sync --extra llm"
            ) from None
        self._litellm = litellm

    def is_available(self) -> tuple[bool, str]:
        return True, "LiteLLM configured (availability checked on first call)"

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": _max_tokens(self.config.effort),
        }
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        resp = self._litellm.completion(**kwargs)
        text = resp.choices[0].message.content or ""
        if not text:
            raise LLMClientError("LiteLLM returned empty response")
        return text.strip()


def make_client(config: LLMConfig | None = None) -> LLMClient | None:
    cfg = config or LLMConfig.from_env()
    if not cfg.enabled:
        return None
    if cfg.provider == "litellm":
        return LiteLLMClient(cfg)
    return OllamaClient(cfg)


def llm_cache_dir() -> Path:
    return data_root() / "warehouse" / "llm_cache"


def _cache_key(context: dict[str, Any], model: str) -> str:
    digest = context.get("filter_digest")
    if digest:
        blob = f"{digest}:{model}"
    else:
        blob = json.dumps(context, sort_keys=True, default=str) + model
    return hashlib.sha256(blob.encode()).hexdigest()


DEFAULT_SYSTEM = (
    "You write short, personal Spotify Wrapped-style narratives. "
    "Use only the statistics provided. Do not invent artists or numbers. "
    "Two short paragraphs max. Warm but not cheesy."
)

TELEGRAM_SYSTEM = (
    "You write short, personal year-in-review narratives about someone's "
    "Telegram messaging habits. Use only the aggregate statistics provided "
    "(counts, chat names, media mix). Never quote or guess message content. "
    "Do not invent names or numbers. Two short paragraphs max. Warm but not cheesy."
)

THUNDERBIRD_SYSTEM = (
    "You write short, personal year-in-review narratives about someone's "
    "email habits from Thunderbird metadata. Use only the aggregate statistics "
    "provided (counts, domains, senders, signals). Never quote or invent "
    "message bodies or subjects beyond the aggregates given. "
    "Two short paragraphs max. Warm but not cheesy."
)

BROWSER_SYSTEM = (
    "Summarize this browsing-history view from aggregates only. "
    "Use only the statistics provided (domains, categories, search engines, "
    "counts). Do not invent sites or numbers. Two short paragraphs max."
)


def narrate(
    context: dict[str, Any],
    *,
    config: LLMConfig | None = None,
    system: str | None = None,
) -> tuple[str, bool]:
    """
    Generate Wrapped-style narrative from aggregates.
    Returns (text, from_cache). ``system`` overrides the default Spotify prompt.
    """
    cfg = config or LLMConfig.from_env()
    client = make_client(cfg)
    if client is None:
        return (
            "LLM disabled. Set DATA_DUMPS_LLM_ENABLED=1 and ensure Ollama is running.",
            False,
        )
    ok, msg = client.is_available()
    if not ok:
        return (
            f"LLM unavailable: {msg}. "
            "Start Ollama or set DATA_DUMPS_LLM_BASE_URL "
            "(use host.docker.internal from Docker).",
            False,
        )

    cache_dir = llm_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(context, cfg.model)
    cache_file = cache_dir / f"{key}.txt"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8"), True

    system_prompt = system or DEFAULT_SYSTEM
    prompt = "Write a narrative for this filtered view:\n\n" + json.dumps(
        context, indent=2, default=str
    )
    text = client.complete(prompt, system=system_prompt)
    cache_file.write_text(text, encoding="utf-8")
    return text, False
