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


class StableSparseEncoder:
    """Stable sparse encoder for persisting sparse vectors.
    Uses term frequency with BM25-like saturation, assuming fixed document length."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.avg_dl = 200.0

    def encode_document(self, text: str) -> tuple[list[int], list[float]]:
        tokens = tokenize(text)
        counts = Counter(tokens)
        doc_length = max(1, len(tokens))
        indices = []
        values = []
        for token, frequency in counts.items():
            indices.append(hash_token(token))
            numerator = frequency * (self.k1 + 1)
            denominator = frequency + self.k1 * (1 - self.b + self.b * doc_length / self.avg_dl)
            # Assuming average IDF of 3.0 for all terms as a simplistic approximation
            values.append(3.0 * numerator / denominator)
        
        sorted_pairs = sorted(zip(indices, values))
        if not sorted_pairs:
            return [], []
        return [p[0] for p in sorted_pairs], [p[1] for p in sorted_pairs]

    def encode_query(self, text: str) -> tuple[list[int], list[float]]:
        tokens = tokenize(text)
        counts = Counter(tokens)
        indices = []
        values = []
        for token, frequency in counts.items():
            indices.append(hash_token(token))
            values.append(float(frequency))
            
        sorted_pairs = sorted(zip(indices, values))
        if not sorted_pairs:
            return [], []
        return [p[0] for p in sorted_pairs], [p[1] for p in sorted_pairs]


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
