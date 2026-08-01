"""Tests for substantive chunk evidence shown to the generator."""

from atenex_nova.application.orchestrators.retrieval_orchestrator import RetrievalOrchestrator


def test_clean_chunk_content_removes_video_envelope_without_translating_body() -> None:
    source = """Kind: captions
Language: es
En esta sesión vamos a hablar del dinero y del amor.
La literatura exige interpretar lo que el texto dice.
"""

    assert RetrievalOrchestrator._clean_chunk_content(source) == (
        "En esta sesión vamos a hablar del dinero y del amor. "
        "La literatura exige interpretar lo que el texto dice."
    )


def test_clean_chunk_content_rejects_metadata_only_chunk() -> None:
    source = """Title: Un vídeo
Video ID: abc123
Channel: Jesús G. Maestro
Subtitle language: es
Generated at: 2026-07-31
-----
"""

    assert RetrievalOrchestrator._clean_chunk_content(source) == ""


def test_best_chunk_excerpt_centers_query_terms_in_long_transcript() -> None:
    source = (
        "introducción " * 80
        + "el dinero y el amor siempre viajan juntos "
        + "continuación " * 80
    )

    excerpt = RetrievalOrchestrator._best_chunk_excerpt(
        source,
        "el dinero es enemigo del amor?",
        max_chars=220,
    )

    assert "dinero y el amor siempre viajan juntos" in excerpt
    assert len(excerpt) <= 220


def test_multi_hop_keeps_enough_ranked_candidates_for_source_diversity() -> None:
    assert RetrievalOrchestrator._result_limit("multi_hop") == 20
