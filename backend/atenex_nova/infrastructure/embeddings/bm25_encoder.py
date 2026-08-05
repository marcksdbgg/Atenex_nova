"""Lightweight BM25 sparse encoder used for query routing and reranking."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from atenex_nova.shared.exceptions.base import ServiceUnavailableError

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
SPANISH_ACCENT_TRANSLATION = str.maketrans(
    {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
    }
)


def tokenize(text: str) -> list[str]:
    return [
        token.casefold().translate(SPANISH_ACCENT_TRANSLATION)
        for token in TOKEN_RE.findall(text)
        if len(token) > 2
    ]


@lru_cache(maxsize=131_072)
def hash_token(token: str) -> int:
    """Return the existing stable 32-bit hash while caching repeated vocabulary."""
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:4], "big")


class StableSparseEncoder:
    """Stable sparse encoder for persisted sparse vectors.

    SPLADE is preferred when available. In local/dev setups where the model is
    absent, a deterministic lexical sparse vector is still persisted so sparse
    retrieval remains real and inspectable instead of becoming a silent no-op.
    """

    _instance: StableSparseEncoder | None = None
    _model: Any | None = None
    _tokenizer: Any | None = None
    _device: str = "cpu"
    _uses_fallback: bool = True
    _encoder_name: str = "lexical_hash"
    _load_attempted: bool = False
    _configuration_key: str | None = None
    _initialization_lock = threading.Lock()

    def __new__(cls, *args: object, **kwargs: object) -> StableSparseEncoder:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "prithivida/Splade_PP_en_v1", required: bool = False) -> None:
        cls = self.__class__
        with cls._initialization_lock:
            if cls._load_attempted and cls._configuration_key == model_name:
                if required and cls._model is None:
                    raise ServiceUnavailableError(
                        service="sparse-encoder",
                        message=f"sparse model '{model_name}' is unavailable",
                    )
                return

            cls._load_attempted = True
            cls._configuration_key = model_name
            cls._model = None
            cls._tokenizer = None
            cls._device = "cpu"
            cls._uses_fallback = True
            cls._encoder_name = "lexical_hash"
            logger.info("Initializing SpladeSparseEncoder with model: %s", model_name)
            try:
                import torch
                from transformers import (
                    AutoModelForMaskedLM,
                    AutoTokenizer,
                )

                cls._device = "cuda" if torch.cuda.is_available() else "cpu"
                cls._tokenizer = AutoTokenizer.from_pretrained(
                    model_name,
                    local_files_only=True,
                )
                cls._model = AutoModelForMaskedLM.from_pretrained(
                    model_name,
                    local_files_only=True,
                ).to(cls._device)
                cls._model.eval()
                cls._uses_fallback = False
                cls._encoder_name = model_name
            except Exception as exc:
                if required:
                    raise ServiceUnavailableError(
                        service="sparse-encoder",
                        message=f"failed to load sparse model '{model_name}': {exc}",
                    ) from exc
                logger.warning(
                    "Failed to initialize local SPLADE: %s. "
                    "Using deterministic lexical sparse fallback.",
                    exc,
                )

    def _encode(self, text: str) -> tuple[list[int], list[float]]:
        if self._model is None or self._tokenizer is None:
            return self._encode_lexical(text)
        import torch

        inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        vec = torch.max(
            torch.log(1 + torch.relu(outputs.logits)) * inputs.attention_mask.unsqueeze(-1),
            dim=1
        )[0].squeeze()
        indices = vec.nonzero().squeeze(-1)
        values = vec[indices]
        if indices.dim() == 0:
            return [int(indices.item())], [float(values.item())]
        return [int(index) for index in indices.tolist()], [float(value) for value in values.tolist()]

    @staticmethod
    def _encode_lexical(text: str) -> tuple[list[int], list[float]]:
        counts = Counter(tokenize(text))
        if not counts:
            return [], []
        max_count = max(counts.values()) or 1
        weighted = sorted(
            (
                hash_token(token),
                1.0 + (count / max_count),
            )
            for token, count in counts.items()
        )
        return [index for index, _value in weighted], [value for _index, value in weighted]

    def encode_document(self, text: str) -> tuple[list[int], list[float]]:
        return self._encode(text)

    def encode_query(self, text: str) -> tuple[list[int], list[float]]:
        return self._encode(text)

    @property
    def uses_fallback(self) -> bool:
        return self._uses_fallback

    @property
    def encoder_name(self) -> str:
        return self._encoder_name

    @classmethod
    def reset_cache_for_tests(cls) -> None:
        """Reset process-wide model state for isolated tests."""
        with cls._initialization_lock:
            cls._model = None
            cls._tokenizer = None
            cls._device = "cpu"
            cls._uses_fallback = True
            cls._encoder_name = "lexical_hash"
            cls._load_attempted = False
            cls._configuration_key = None
            cls._instance = None
        hash_token.cache_clear()


@dataclass
class BM25SparseEncoder:
    """Simple BM25 scorer that can rank a small local corpus."""

    k1: float = 1.5
    b: float = 0.75

    def fit(self, texts: list[str]) -> None:
        self._documents = [tokenize(text) for text in texts]
        self._doc_lengths = [len(doc) for doc in self._documents]
        self._avg_doc_length = sum(self._doc_lengths) / max(1, len(self._doc_lengths))
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(set(document))
        self._document_count = len(self._documents)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        self.fit(texts)
        query_terms = tokenize(query)
        scores: list[float] = []
        for document in self._documents:
            term_counts = Counter(document)
            score = 0.0
            doc_length = len(document) or 1
            for term in query_terms:
                frequency = term_counts.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency.get(term, 0)
                idf = math.log(1 + (self._document_count - document_frequency + 0.5) / (document_frequency + 0.5))
                numerator = frequency * (self.k1 + 1)
                denominator = frequency + self.k1 * (1 - self.b + self.b * doc_length / max(self._avg_doc_length, 1e-9))
                score += idf * numerator / denominator
            scores.append(score)
        return scores
