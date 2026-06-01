"""Policy for semantic chunking based on token budgets."""

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int:
        ...




class DefaultTokenEstimator(TokenEstimator):
    """Fallback token estimator using a simple character-based heuristic (approx. 4 chars per token)."""
    def estimate(self, text: str) -> int:
        return max(1, len(text) // 4)


class TransformersTokenEstimator(TokenEstimator):
    """Real token estimator using HuggingFace transformers AutoTokenizer."""

    def __init__(self, model_name: str = "google/embeddinggemma-300m") -> None:
        self.tokenizer: Any | None = None
        try:
            from transformers import AutoTokenizer

            # fast loading, avoids downloading weights if not needed
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception as exc:
            logger.warning("Failed to load AutoTokenizer for '%s': %s. Falling back to heuristic.", model_name, exc)
            self.tokenizer = None

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        if self.tokenizer:
            return len(self.tokenizer.tokenize(text))
        return max(1, len(text) // 4)


class TokenBudgetPolicy:
    """Evaluates boundaries for structural chunking to respect token budgets."""

    def __init__(self, estimator: TokenEstimator | None = None) -> None:
        if estimator is None:
            estimator = TransformersTokenEstimator()
        self.estimator = estimator

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return self.estimator.estimate(text)

    def should_split(
        self,
        current_tokens: int,
        next_node_tokens: int,
        node_type: str,
        min_tokens: int = 400,
        max_tokens: int = 800,
    ) -> bool:
        """
        Determine if the current chunk should be finalized before adding the next node.

        Args:
            current_tokens: Tokens currently accumulated in the chunk.
            next_node_tokens: Estimated tokens of the next node.
            node_type: The structural type of the next node.
            min_tokens: Minimum tokens to aim for before allowing a split.
            max_tokens: Maximum tokens allowed in a chunk.

        Returns:
            True if the chunk should be split now, False to continue accumulating.
        """
        # If the next node pushes us over max_tokens, and we have *something*, we must split.
        if current_tokens > 0 and (current_tokens + next_node_tokens) > max_tokens:
            return True

        # Structural boundaries that strongly imply a semantic break
        is_boundary_type = node_type in {
            "heading", "table", "caption", "image", "formula", "page_break"
        }

        # If it's a structural boundary AND we've satisfied the minimum budget, split.
        return bool(is_boundary_type and current_tokens >= min_tokens)
