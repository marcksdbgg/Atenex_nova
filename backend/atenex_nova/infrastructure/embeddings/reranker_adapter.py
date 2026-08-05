"""Adapter for Cross-Encoder reranking models."""

import logging
import os
import threading
from collections.abc import Sequence
from typing import Any

from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)


class RerankerAdapter:
    """Cross-encoder adapter with one process-wide, configuration-aware model cache."""

    _model: Any | None = None
    _model_name: str = "heuristic"
    _available: bool = False
    _load_attempted: bool = False
    _configuration_key: tuple[object, ...] | None = None
    _failure_detail: str | None = None
    _initialization_lock = threading.Lock()

    def __init__(self, model_name: str | None = None, required: bool = False) -> None:
        self._required = required
        settings = get_settings()
        env_path = os.environ.get("ATENEX_RERANKER_PATH")
        model_to_load = settings.reranker_path or env_path or model_name or "BAAI/bge-reranker-v2-m3"
        configuration_key = (
            settings.reranker_enabled,
            model_to_load,
            settings.reranker_device,
            settings.reranker_fp16,
        )

        with self.__class__._initialization_lock:
            if (
                self.__class__._load_attempted
                and self.__class__._configuration_key == configuration_key
            ):
                self._raise_if_required_and_unavailable()
                return

            self.__class__._configuration_key = configuration_key
            self.__class__._load_attempted = True
            self.__class__._model = None
            self.__class__._model_name = "heuristic"
            self.__class__._available = False
            self.__class__._failure_detail = None

            if not settings.reranker_enabled:
                detail = "reranker is disabled by configuration settings/profile"
                logger.info(detail)
                self.__class__._failure_detail = detail
                self._raise_if_required_and_unavailable()
                return

            logger.info("Initializing RerankerAdapter with model: %s", model_to_load)
            try:
                import torch
                from sentence_transformers import CrossEncoder

                device_config = settings.reranker_device
                if device_config == "cuda" and not torch.cuda.is_available():
                    logger.warning("CUDA configured but not available. Falling back to CPU.")
                    device = "cpu"
                elif device_config == "cuda":
                    device = "cuda"
                else:
                    device = "cpu"

                logger.info("Reranker loading on device: %s", device)
                model = CrossEncoder(model_to_load, max_length=512, device=device)

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
                detail = f"failed to import reranker dependencies for '{model_to_load}': {exc}"
                self.__class__._failure_detail = detail
                logger.warning("Failed to initialize reranker %s: %s", model_to_load, exc)
                if required:
                    raise ServiceUnavailableError(service="reranker", message=detail) from exc
            except Exception as exc:
                detail = f"failed to load reranker '{model_to_load}': {exc}"
                self.__class__._failure_detail = detail
                logger.error("Error loading reranker %s: %s", model_to_load, exc)
                if required:
                    raise ServiceUnavailableError(service="reranker", message=detail) from exc

    def _raise_if_required_and_unavailable(self) -> None:
        if self._required and not self.__class__._available:
            raise ServiceUnavailableError(
                service="reranker",
                message=self.__class__._failure_detail or "reranker model unavailable",
            )

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

    @property
    def failure_detail(self) -> str | None:
        return self._failure_detail

    @classmethod
    def reset_cache_for_tests(cls) -> None:
        """Reset shared state for isolated tests; production code must never call it."""
        with cls._initialization_lock:
            cls._model = None
            cls._model_name = "heuristic"
            cls._available = False
            cls._load_attempted = False
            cls._configuration_key = None
            cls._failure_detail = None
