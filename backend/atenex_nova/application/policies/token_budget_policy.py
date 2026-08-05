"""Policy for semantic chunking based on token budgets."""

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int:
        ...


@dataclass(frozen=True, slots=True)
class TextSegment:
    """A bounded slice of a source text with stable character offsets."""

    text: str
    char_start: int
    char_end: int
    token_count: int


_SEMANTIC_BOUNDARY_RE = re.compile(r"(?<=[.!?;:])(?:\s+|$)|\n+")



class DefaultTokenEstimator(TokenEstimator):
    """Fallback token estimator using a simple character-based heuristic (approx. 4 chars per token)."""
    def estimate(self, text: str) -> int:
        return max(1, len(text) // 4)


class TransformersTokenEstimator(TokenEstimator):
    """Optional token estimator using a tokenizer already present on local disk."""

    def __init__(self, model_name: str) -> None:
        self.tokenizer: Any | None = None
        try:
            from transformers import AutoTokenizer

            # Offline-first: never fetch a tokenizer from the network.
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
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
            estimator = DefaultTokenEstimator()
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
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")

        # An oversized first node must be subdivided before it can be added.
        if next_node_tokens > max_tokens:
            return True

        # If the next node pushes us over max_tokens, finalize the current chunk first.
        if current_tokens > 0 and (current_tokens + next_node_tokens) > max_tokens:
            return True

        # Structural boundaries that strongly imply a semantic break
        is_boundary_type = node_type in {
            "heading", "table", "caption", "image", "formula", "page_break"
        }

        # If it's a structural boundary AND we've satisfied the minimum budget, split.
        return bool(is_boundary_type and current_tokens >= min_tokens)

    def split_text(
        self,
        text: str,
        *,
        max_tokens: int = 800,
        overlap_tokens: int = 80,
    ) -> list[TextSegment]:
        """Split *text* into bounded, ordered slices with source spans.

        The estimator is intentionally injected so this policy stays independent of
        any embedding runtime. Boundaries prefer sentence/newline breaks, then
        whitespace, while a hard postcondition guarantees every returned slice is
        within ``max_tokens`` according to that estimator.
        """
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative")
        if overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")
        if not text:
            return []

        if self.estimate_tokens(text) <= max_tokens:
            return [
                TextSegment(
                    text=text,
                    char_start=0,
                    char_end=len(text),
                    token_count=self.estimate_tokens(text),
                )
            ]

        segments: list[TextSegment] = []
        start = 0
        text_length = len(text)
        while start < text_length:
            hard_end = self._largest_bounded_end(text, start, max_tokens)
            if hard_end <= start:
                raise ValueError("token estimator cannot fit a single character in max_tokens")

            end = self._preferred_boundary(text, start, hard_end)
            if end <= start:
                end = hard_end

            token_count = self.estimate_tokens(text[start:end])
            if token_count > max_tokens:
                # Defensive fallback for a non-monotonic custom estimator.
                end = hard_end
                token_count = self.estimate_tokens(text[start:end])
            while end > start and token_count > max_tokens:
                end -= 1
                token_count = self.estimate_tokens(text[start:end])
            if end <= start or token_count > max_tokens:
                raise ValueError("unable to produce a segment within max_tokens")

            segments.append(
                TextSegment(
                    text=text[start:end],
                    char_start=start,
                    char_end=end,
                    token_count=token_count,
                )
            )
            if end >= text_length:
                break

            next_start = self._overlap_start(text, start, end, overlap_tokens)
            # Overlap must never prevent forward progress.
            start = min(end, max(start + 1, next_start))

        return segments

    def _largest_bounded_end(self, text: str, start: int, max_tokens: int) -> int:
        """Return the largest suffix end that fits the configured budget."""
        best = start
        distance = 1
        probe = min(len(text), start + distance)
        while self.estimate_tokens(text[start:probe]) <= max_tokens:
            best = probe
            if probe >= len(text):
                return probe
            distance *= 2
            probe = min(len(text), start + distance)

        low = best + 1
        high = probe - 1
        while low <= high:
            middle = (low + high) // 2
            if self.estimate_tokens(text[start:middle]) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    @staticmethod
    def _preferred_boundary(text: str, start: int, hard_end: int) -> int:
        """Choose a nearby semantic boundary without creating tiny fragments."""
        if hard_end >= len(text):
            return hard_end
        minimum_end = start + max(1, int((hard_end - start) * 0.6))
        window = text[start:hard_end]
        semantic_ends = [start + match.end() for match in _SEMANTIC_BOUNDARY_RE.finditer(window)]
        semantic_ends = [end for end in semantic_ends if end >= minimum_end]
        if semantic_ends:
            return semantic_ends[-1]

        whitespace = max(text.rfind(" ", minimum_end, hard_end), text.rfind("\t", minimum_end, hard_end))
        return whitespace + 1 if whitespace >= minimum_end else hard_end

    def _overlap_start(self, text: str, chunk_start: int, chunk_end: int, overlap_tokens: int) -> int:
        if overlap_tokens == 0:
            return chunk_end

        low = chunk_start + 1
        high = chunk_end
        best = chunk_end
        while low <= high:
            middle = (low + high) // 2
            if self.estimate_tokens(text[middle:chunk_end]) <= overlap_tokens:
                best = middle
                high = middle - 1
            else:
                low = middle + 1

        # Prefer starting the overlap at a word boundary. Moving right can only
        # reduce its token count, so the hard cap remains intact.
        if best < chunk_end and best > 0 and not text[best - 1].isspace() and not text[best].isspace():
            next_space = text.find(" ", best, chunk_end)
            if next_space != -1:
                best = next_space + 1
        return best
