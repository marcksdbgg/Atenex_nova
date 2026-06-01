"""Adapter for Cross-Encoder reranking models."""

import logging
from collections.abc import Sequence
from typing import Any

from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


class RerankerAdapter:
    """Singleton adapter for Cross-Encoder reranker."""

    _instance: "RerankerAdapter | None" = None
    _model: Any | None = None
    _model_name: str = "heuristic"
    _available: bool = False

    def __new__(cls, *args: object, **kwargs: object) -> "RerankerAdapter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", required: bool = False) -> None:
        self._required = required
        if self._model is not None:
            return

        logger.info("Initializing RerankerAdapter with model: %s", model_name)
        try:
            import torch
            from sentence_transformers import CrossEncoder

            device = "cuda" if torch.cuda.is_available() else "cpu"
            # Using max_length=512 as an optimal tradeoff for snippet reranking
            self.__class__._model = CrossEncoder(model_name, max_length=512, device=device)
            self.__class__._model_name = model_name
            self.__class__._available = True
        except ImportError as exc:
            if required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message=f"failed to import reranker dependencies for '{model_name}': {exc}",
                ) from exc
            logger.warning("Failed to initialize reranker %s: %s", model_name, exc)
            self.__class__._model = None
            self.__class__._model_name = "heuristic"
            self.__class__._available = False
        except Exception as exc:
            if required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message=f"failed to load reranker '{model_name}': {exc}",
                ) from exc
            logger.error("Error loading reranker %s: %s", model_name, exc)
            self.__class__._model = None
            self.__class__._model_name = "heuristic"
            self.__class__._available = False

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Predict relevance scores for a list of (query, document) pairs.
        Returns a list of float scores (logits).
        Returns empty list if model is not available.
        """
        if not pairs:
            return []

        if self._model is None:
            if self._required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message="reranker model unavailable and strict mode requires neural reranking",
                )
            return []

        try:
            scores = self._model.predict(pairs)
            # CrossEncoder predict can return scalar or array depending on input. Ensure list.
            if hasattr(scores, "tolist"):
                return [float(score) for score in scores.tolist()]
            if isinstance(scores, (float, int)):
                return [float(scores)]
            return [float(s) for s in scores]
        except Exception as exc:
            if self._required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message=f"reranker prediction failed: {exc}",
                ) from exc
            logger.warning("Reranker prediction failed: %s", exc)
            return []

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def model_name(self) -> str:
        return self._model_name
