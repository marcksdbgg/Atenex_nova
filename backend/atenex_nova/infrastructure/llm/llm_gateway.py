"""LLM gateway protocol and HTTP adapters."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMGenerationResult:
    """Result from LLM generation backend, including text and token counts."""
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMGateway(Protocol):
    """Protocol for LLM generation backends."""

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> LLMGenerationResult: ...


class OllamaAdapter:
    """HTTP adapter for Ollama."""

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "gemma4:12b",
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
    ) -> LLMGenerationResult:
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

        max_retries = 3
        backoff_base = 2.0

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(f"{self._url}/api/generate", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    text = str(data.get("response", "")).strip()
                    prompt_tokens = data.get("prompt_eval_count")
                    completion_tokens = data.get("eval_count")

                    # If token counts are not present, estimate them
                    if prompt_tokens is None:
                        prompt_tokens = max(1, len(prompt) // 4)
                    if completion_tokens is None:
                        completion_tokens = max(1, len(text) // 4)

                    if text:
                        return LLMGenerationResult(
                            text=text,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                        )

                    # If empty text and it's not the last attempt, we wait and retry
                    if attempt < max_retries - 1:
                        sleep_time = backoff_base**attempt
                        logger.warning(
                            "Ollama returned empty response on attempt %d. Retrying in %.1fs...",
                            attempt + 1,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)
                        continue

                    if self._required:
                        raise ServiceUnavailableError(
                            service="llm",
                            message="ollama returned empty response in strict mode",
                        )
                    return LLMGenerationResult(
                        text="",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
            except Exception as exc:
                if attempt < max_retries - 1:
                    sleep_time = backoff_base**attempt
                    logger.warning(
                        "Ollama request failed on attempt %d (%s). Retrying in %.1fs...",
                        attempt + 1,
                        exc,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    if self._required:
                        raise ServiceUnavailableError(
                            service="llm",
                            message=f"ollama generation failed after {max_retries} attempts: {exc}",
                        ) from exc
                    logger.warning("Ollama generation unavailable: %s", exc)
                    # Fallback token counts for empty result
                    fallback_prompt_tokens = max(1, len(prompt) // 4)
                    return LLMGenerationResult(
                        text="",
                        prompt_tokens=fallback_prompt_tokens,
                        completion_tokens=0,
                    )

        return LLMGenerationResult(text="")


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
    ) -> LLMGenerationResult:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
        }
        if stop:
            payload["stop"] = stop

        max_retries = 3
        backoff_base = 2.0

        for attempt in range(max_retries):
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

                    # Check for tokens in llama.cpp response
                    prompt_tokens = None
                    completion_tokens = None
                    if isinstance(data, dict):
                        prompt_tokens = data.get("tokens_evaluated")
                        completion_tokens = data.get("tokens_predicted")
                        # Fallback to timings if not present directly
                        if prompt_tokens is None and "timings" in data:
                            prompt_tokens = data["timings"].get("prompt_n")
                        if completion_tokens is None and "timings" in data:
                            completion_tokens = data["timings"].get("predicted_n")

                    if prompt_tokens is None:
                        prompt_tokens = max(1, len(prompt) // 4)
                    if completion_tokens is None:
                        completion_tokens = max(1, len(text) // 4)

                    if text:
                        return LLMGenerationResult(
                            text=text,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                        )

                    # If empty text and it's not the last attempt, we wait and retry
                    if attempt < max_retries - 1:
                        sleep_time = backoff_base**attempt
                        logger.warning(
                            "llama.cpp returned empty response on attempt %d. Retrying in %.1fs...",
                            attempt + 1,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)
                        continue

                    if self._required:
                        raise ServiceUnavailableError(
                            service="llm",
                            message="llama.cpp returned empty response in strict mode",
                        )
                    return LLMGenerationResult(
                        text="",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
            except Exception as exc:
                if attempt < max_retries - 1:
                    sleep_time = backoff_base**attempt
                    logger.warning(
                        "llama.cpp request failed on attempt %d (%s). Retrying in %.1fs...",
                        attempt + 1,
                        exc,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    if self._required:
                        raise ServiceUnavailableError(
                            service="llm",
                            message=f"llama.cpp generation failed after {max_retries} attempts: {exc}",
                        ) from exc
                    logger.warning("llama.cpp generation unavailable: %s", exc)
                    fallback_prompt_tokens = max(1, len(prompt) // 4)
                    return LLMGenerationResult(
                        text="",
                        prompt_tokens=fallback_prompt_tokens,
                        completion_tokens=0,
                    )

        return LLMGenerationResult(text="")
