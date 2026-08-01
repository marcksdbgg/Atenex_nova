"""Tests for accent-tolerant Spanish lexical retrieval."""

from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder, tokenize


def test_tokenize_folds_spanish_vowel_accents_but_preserves_enye() -> None:
    assert tokenize("imbécil, poesía, niño") == ["imbecil", "poesia", "niño"]


def test_bm25_matches_query_written_without_spanish_accents() -> None:
    scores = BM25SparseEncoder().score(
        "un imbecil enamorado",
        [
            "El amor es más sensato de lo que cree un imbécil enamorado.",
            "Este fragmento no trata de esa cuestión.",
        ],
    )

    assert scores[0] > scores[1]
