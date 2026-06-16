"""Adapter for Cross-Encoder reranking models."""

import logging
import os
from collections.abc import Sequence
from typing import Any

from atenex_nova.shared.config.settings import get_settings
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

    def __init__(self, model_name: str | None = None, required: bool = False) -> None:
        self._required = required
        settings = get_settings()

        if not settings.reranker_enabled:
            logger.info("Reranker is disabled by configuration settings/profile")
            self.__class__._model = None
            self.__class__._model_name = "heuristic"
            self.__class__._available = False
            if required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message="reranker is disabled by configuration settings/profile, but strict mode/required is enabled",
                )
            return

        if self._model is not None:
            return

        # Determine model path: local path in settings, env var, or fallback
        env_path = os.environ.get("ATENEX_RERANKER_PATH")
        model_to_load = settings.reranker_path or env_path or model_name or "BAAI/bge-reranker-v2-m3"

        logger.info("Initializing RerankerAdapter with model: %s", model_to_load)
        try:
            import torch
            from sentence_transformers import CrossEncoder

            # Device selection with CUDA auto-fallback
            device_config = settings.reranker_device
            if device_config == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA configured but not available. Falling back to CPU.")
                device = "cpu"
            elif device_config == "cuda":
                device = "cuda"
            else:
                device = "cpu"

            logger.info("Reranker loading on device: %s", device)

            # Using max_length=512 as an optimal tradeoff for snippet reranking
            model = CrossEncoder(model_to_load, max_length=512, device=device)

            # Calibration: Float16 conversion if CUDA and enabled
            if device == "cuda" and settings.reranker_fp16:
                try:
                    model.model.half()
                    logger.info("Reranker successfully calibrated to half-precision (float16)")
                except Exception as exc:
                    logger.warning("Could not convert Reranker to float16: %s", exc)

            self.__class__._model = model
            self.__class__._model_name = model_to_load
            self.__class__._available = True
        except ImportError as exc:
            if required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message=f"failed to import reranker dependencies for '{model_to_load}': {exc}",
                ) from exc
            logger.warning("Failed to initialize reranker %s: %s", model_to_load, exc)
            self.__class__._model = None
            self.__class__._model_name = "heuristic"
            self.__class__._available = False
        except Exception as exc:
            if required:
                raise ServiceUnavailableError(
                    service="reranker",
                    message=f"failed to load reranker '{model_to_load}': {exc}",
                ) from exc
            logger.error("Error loading reranker %s: %s", model_to_load, exc)
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

        settings = get_settings()
        batch_size = settings.reranker_batch_size

        try:
            scores = self._model.predict(pairs, batch_size=batch_size)
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
