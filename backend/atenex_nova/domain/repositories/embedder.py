"""Embedder protocol."""

from typing import Protocol


class Embedder(Protocol):
    """Protocol for generating vector embeddings from text."""

    def __init__(self, model_name: str, dim: int) -> None: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
