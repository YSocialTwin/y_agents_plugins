from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from y_agents_plugins.config import ClientConfig


@dataclass(frozen=True)
class LangChainLLMConfig:
    base_url: str
    api_key: str | None
    temperature: float | None
    max_tokens: int | None
    model: str | None


class LangChainTextGenerator:
    """LangChain-backed text generation compatible with YClient-style config."""

    def __init__(self, config: LangChainLLMConfig) -> None:
        self.config = config

    @classmethod
    def from_client_config(cls, client_config: ClientConfig) -> "LangChainTextGenerator":
        servers = client_config.llm_servers.values
        max_tokens = int(servers["llm_max_tokens"])
        return cls(
            LangChainLLMConfig(
                base_url=str(servers["llm"]),
                api_key=_normalize_api_key(servers.get("llm_api_key")),
                temperature=float(servers["llm_temperature"]),
                max_tokens=max_tokens if max_tokens > 0 else None,
                model=client_config.primary_llm_model,
            )
        )

    @property
    def is_available(self) -> bool:
        return bool(self.config.model)

    def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.is_available:
            raise RuntimeError("No LLM model configured for this client")
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as exc:
            raise RuntimeError(
                "LangChain Core is required for LLM access. Install `langchain-core`."
            ) from exc
        model = self._build_chat_model()
        response = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        return _coerce_content_to_text(getattr(response, "content", response)).strip()

    def _build_chat_model(self):
        if _looks_like_ollama(self.config):
            try:
                from langchain_ollama import ChatOllama
            except ImportError as exc:
                raise RuntimeError(
                    "LangChain Ollama support is required for Ollama endpoints. Install `langchain-ollama`."
                ) from exc

            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "base_url": self.config.base_url.rsplit("/v1", 1)[0],
            }
            if self.config.temperature is not None:
                kwargs["temperature"] = self.config.temperature
            if self.config.max_tokens is not None:
                kwargs["num_predict"] = self.config.max_tokens
            return ChatOllama(**kwargs)

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "LangChain OpenAI support is required for non-Ollama endpoints. Install `langchain-openai`."
            ) from exc

        kwargs = {
            "model": self.config.model,
            "base_url": self.config.base_url,
            "api_key": self.config.api_key or "EMPTY",
        }
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        if self.config.max_tokens is not None:
            kwargs["max_tokens"] = self.config.max_tokens
        return ChatOpenAI(**kwargs)


def _normalize_api_key(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.upper() in {"NULL", "EMPTY"}:
        return None
    return normalized


def _looks_like_ollama(config: LangChainLLMConfig) -> bool:
    parsed = urlparse(config.base_url)
    hostname = (parsed.hostname or "").lower()
    netloc = (parsed.netloc or "").lower()
    return (
        "ollama" in hostname
        or "ollama" in netloc
        or parsed.port == 11434
        or ":11434" in config.base_url
        or (config.api_key is None and bool(config.model) and ":" in str(config.model))
    )


def _coerce_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and "text" in item:
                chunks.append(str(item["text"]))
            else:
                chunks.append(str(item))
        return "\n".join(chunk for chunk in chunks if chunk)
    return str(content)
