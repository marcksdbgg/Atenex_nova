"""LLM gateway protocol and HTTP adapters."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

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
    """HTTP adapter for Ollama."""

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "gemma4:e4b",
        required: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._url = url.rstrip("/")
        self._model = model
        self._required = settings.llm_required if required is None else required
        logger.info("OllamaAdapter initialized → %s model=%s", self._url, model)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        options: dict[str, Any] = {
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if stop:
            options["stop"] = stop
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self._url}/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
                text = str(data.get("response", "")).strip()
                if text:
                    return text
                if self._required:
                    raise ServiceUnavailableError(
                        service="llm",
                        message="ollama returned empty response in strict mode",
                    )
                return ""
        except Exception as exc:
            if self._required:
                raise ServiceUnavailableError(service="llm", message=f"ollama generation failed: {exc}") from exc
            logger.warning("Ollama generation unavailable: %s", exc)
            return ""


class LlamaCppAdapter:
    """HTTP adapter for llama.cpp server."""

    def __init__(self, url: str = "http://localhost:8080", required: bool | None = None) -> None:
        settings = get_settings()
        self._url = url.rstrip("/")
        self._required = settings.llm_required if required is None else required
        logger.info("LlamaCppAdapter initialized → %s", self._url)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
        }
        if stop:
            payload["stop"] = stop
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self._url}/completion", json=payload)
                response.raise_for_status()
                data = response.json()
                text = ""
                if isinstance(data, dict):
                    if "content" in data:
                        text = str(data["content"]).strip()
                    if data.get("choices"):
                        text = str(data["choices"][0].get("text", "")).strip() or text
                if text:
                    return text
                if self._required:
                    raise ServiceUnavailableError(
                        service="llm",
                        message="llama.cpp returned empty response in strict mode",
                    )
                return ""
        except Exception as exc:
            if self._required:
                raise ServiceUnavailableError(service="llm", message=f"llama.cpp generation failed: {exc}") from exc
            logger.warning("llama.cpp generation unavailable: %s", exc)
            return ""
