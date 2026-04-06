"""LLM gateway protocol and HTTP adapters."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

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

    def __init__(self, url: str = "http://localhost:11434", model: str = "gemma4:e4b") -> None:
        self._url = url.rstrip("/")
        self._model = model
        logger.info("OllamaAdapter initialized → %s model=%s", self._url, model)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if stop:
            payload["options"]["stop"] = stop
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self._url}/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data.get("response", "")).strip()
        except Exception as exc:
            logger.warning("Ollama generation unavailable: %s", exc)
            return ""


class LlamaCppAdapter:
    """HTTP adapter for llama.cpp server."""

    def __init__(self, url: str = "http://localhost:8080") -> None:
        self._url = url.rstrip("/")
        logger.info("LlamaCppAdapter initialized → %s", self._url)

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        payload = {
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
                if isinstance(data, dict):
                    if "content" in data:
                        return str(data["content"]).strip()
                    if "choices" in data and data["choices"]:
                        return str(data["choices"][0].get("text", "")).strip()
                return ""
        except Exception as exc:
            logger.warning("llama.cpp generation unavailable: %s", exc)
            return ""
