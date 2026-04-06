"""LLM gateway protocol and stub adapters."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class LLMGateway(Protocol):
    """Protocol for LLM generation backends."""

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str: ...


class OllamaAdapter:
    """Stub adapter for Ollama API. Implemented in Fase 6."""

    def __init__(self, url: str = "http://localhost:11434", model: str = "gemma4:e4b") -> None:
        self._url = url
        self._model = model
        logger.info("OllamaAdapter initialized (stub) → %s model=%s", url, model)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        logger.info("Stub: Ollama generate (len=%d)", len(prompt))
        return "[Stub response — Ollama not connected]"


class LlamaCppAdapter:
    """Stub adapter for llama.cpp server. Implemented in Fase 6."""

    def __init__(self, url: str = "http://localhost:8080") -> None:
        self._url = url
        logger.info("LlamaCppAdapter initialized (stub) → %s", url)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        logger.info("Stub: llama.cpp generate (len=%d)", len(prompt))
        return "[Stub response — llama.cpp not connected]"
