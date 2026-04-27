"""Adapter for Cross-Encoder reranking models."""

import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)

class RerankerAdapter:
    """Singleton adapter for Cross-Encoder reranker."""
    
    _instance = None
    _model = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        if self._model is not None:
            return
            
        logger.info("Initializing RerankerAdapter with model: %s", model_name)
        try:
            import torch
            from sentence_transformers import CrossEncoder
            device = "cuda" if torch.cuda.is_available() else "cpu"
            # Using max_length=512 as an optimal tradeoff for snippet reranking
            self.__class__._model = CrossEncoder(model_name, max_length=512, device=device)
        except ImportError as e:
            logger.warning("Failed to initialize reranker %s: %s", model_name, e)
            self.__class__._model = None
        except Exception as e:
            logger.error("Error loading reranker %s: %s", model_name, e)
            self.__class__._model = None

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Predict relevance scores for a list of (query, document) pairs.
        Returns a list of float scores (logits).
        Returns empty list if model is not available.
        """
        if not pairs:
            return []
            
        if self._model is None:
            return []
            
        try:
            scores = self._model.predict(pairs)
            # CrossEncoder predict can return scalar or array depending on input. Ensure list.
            if hasattr(scores, "tolist"):
                return scores.tolist()
            if isinstance(scores, (float, int)):
                return [float(scores)]
            return [float(s) for s in scores]
        except Exception as e:
            logger.warning("Reranker prediction failed: %s", e)
            return []
