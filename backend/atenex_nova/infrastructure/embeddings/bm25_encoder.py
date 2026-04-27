"""Lightweight BM25 sparse encoder used for query routing and reranking."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 2]


def hash_token(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)


import logging
logger = logging.getLogger(__name__)

class StableSparseEncoder:
    """Stable sparse encoder for persisting sparse vectors.
    Uses SPLADE via transformers to generate semantic sparse vectors."""
    
    _instance = None
    _model = None
    _tokenizer = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "prithivida/Splade_PP_en_v1"):
        if self._model is not None:
            return
        logger.info("Initializing SpladeSparseEncoder with model: %s", model_name)
        try:
            import torch
            from transformers import AutoModelForMaskedLM, AutoTokenizer
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self.__class__._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.__class__._model = AutoModelForMaskedLM.from_pretrained(model_name).to(self._device)
            self.__class__._model.eval()
        except ImportError as e:
            logger.warning("Failed to initialize SPLADE: %s. Using mock fallback.", e)
            self.__class__._model = None
            self.__class__._tokenizer = None

    def _encode(self, text: str) -> tuple[list[int], list[float]]:
        if self._model is None or self._tokenizer is None:
            return [], []
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
            return [indices.item()], [values.item()]
        return indices.tolist(), values.tolist()

    def encode_document(self, text: str) -> tuple[list[int], list[float]]:
        return self._encode(text)

    def encode_query(self, text: str) -> tuple[list[int], list[float]]:
        return self._encode(text)


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
