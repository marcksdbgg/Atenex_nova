"""Tests for accent-tolerant Spanish lexical retrieval."""

import builtins

import pytest

from atenex_nova.infrastructure.embeddings.bm25_encoder import (
    BM25SparseEncoder,
    StableSparseEncoder,
    hash_token,
    tokenize,
)


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


def test_stable_sparse_fallback_initialization_is_attempted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__
    torch_imports = 0

    def import_without_torch(name, *args, **kwargs):
        nonlocal torch_imports
        if name == "torch":
            torch_imports += 1
            raise ImportError("torch intentionally unavailable")
        return real_import(name, *args, **kwargs)

    StableSparseEncoder.reset_cache_for_tests()
    monkeypatch.setattr(builtins, "__import__", import_without_torch)
    try:
        first = StableSparseEncoder()
        second = StableSparseEncoder()
        assert first.encode_document("libertad y realidad") == second.encode_document(
            "libertad y realidad"
        )
        assert first.uses_fallback is True
        assert torch_imports == 1
    finally:
        StableSparseEncoder.reset_cache_for_tests()


def test_cached_token_hash_preserves_the_existing_stable_value() -> None:
    hash_token.cache_clear()
    expected = int("f0ab3f8e", 16)

    assert hash_token("libertad") == expected
    assert hash_token("libertad") == expected
    assert hash_token.cache_info().hits == 1
