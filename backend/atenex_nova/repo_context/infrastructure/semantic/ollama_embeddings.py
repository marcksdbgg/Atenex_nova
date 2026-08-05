"""Local Ollama embeddings for the required semantic projection."""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen


class OllamaEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "embeddinggemma",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    @property
    def identity(self) -> str:
        return f"ollama:{self._model}"

    def available(self) -> bool:
        request = Request(f"{self._base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=min(self._timeout, 2.0)) as response:
                if not 200 <= int(response.status) < 300:
                    return False
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError):
            return False
        expected = self._model.removesuffix(":latest")
        return any(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item["name"].removesuffix(":latest") == expected
            for item in body.get("models", [])
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self._model, "input": list(texts)}).encode()
        request = Request(
            f"{self._base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError) as exc:
            raise RuntimeError(f"Ollama embeddings unavailable: {exc}") from exc
        vectors = body.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError("Ollama returned an invalid embeddings response")
        return [[float(value) for value in vector] for vector in vectors]
