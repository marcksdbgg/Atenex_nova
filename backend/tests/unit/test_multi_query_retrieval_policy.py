"""Unit coverage for deterministic bounded multi-query planning."""

from __future__ import annotations

from atenex_nova.application.policies.conversation_retrieval_policy import (
    CONVERSATION_CONTEXT_MARKER,
)
from atenex_nova.application.policies.multi_query_retrieval_policy import (
    MultiQueryRetrievalPolicy,
)


def test_multi_hop_extracts_facets_and_keeps_conversation_context_transient() -> None:
    policy = MultiQueryRetrievalPolicy()
    original = (
        "Analiza la libertad moral en Cervantes; "
        "explica la vulnerabilidad social ante la eutanasia"
    )
    retrieval = (
        f"{original.lower()}\n\n{CONVERSATION_CONTEXT_MARKER}\n"
        "Usuario: El corpus es de Jesús G."
    )

    plan = policy.build(
        original_text=original,
        retrieval_text=retrieval,
        route_mode="multi_hop",
    )

    assert plan.expanded
    assert plan.variants[0].kind == "original"
    assert plan.variants[0].text == retrieval
    assert [variant.audit_text for variant in plan.variants[1:3]] == [
        "analiza la libertad moral en cervantes",
        "explica la vulnerabilidad social ante la eutanasia",
    ]
    assert all(CONVERSATION_CONTEXT_MARKER in variant.text for variant in plan.variants[1:])
    assert all("Jesús G." not in variant.audit_text for variant in plan.variants)
    assert len(plan.variants) <= policy.max_facet_variants + 1


def test_argumentative_query_builds_opposing_polarity_facets() -> None:
    plan = MultiQueryRetrievalPolicy().build(
        original_text="Contrasta argumentos a favor y en contra de la eutanasia asistida",
        retrieval_text="Contrasta argumentos a favor y en contra de la eutanasia asistida",
        route_mode="argumentative",
    )

    facet_texts = [variant.audit_text.casefold() for variant in plan.variants[1:]]
    assert any("a favor de la eutanasia asistida" in text for text in facet_texts)
    assert any("en contra de la eutanasia asistida" in text for text in facet_texts)
    assert len(facet_texts) == 2
    assert "contrasta argumentos a favor" not in facet_texts
    assert len(facet_texts) == len(set(facet_texts))


def test_global_query_expands_at_most_three_substantial_comma_facets() -> None:
    plan = MultiQueryRetrievalPolicy().build(
        original_text=(
            "Resume la visión del corpus sobre la dignidad humana, "
            "analiza la vulnerabilidad social en los enfermos, "
            "contrasta la libertad personal ante la muerte, "
            "describe el papel colectivo de la esperanza"
        ),
        retrieval_text=(
            "resume la visión del corpus sobre la dignidad humana, "
            "analiza la vulnerabilidad social en los enfermos, "
            "contrasta la libertad personal ante la muerte, "
            "describe el papel colectivo de la esperanza"
        ),
        route_mode="global",
    )

    assert plan.expanded
    assert len(plan.variants) == 4
    assert all(variant.kind == "facet" for variant in plan.variants[1:])
    assert all(len(variant.audit_text.split()) >= 4 for variant in plan.variants[1:])


def test_short_and_duplicate_facets_are_discarded() -> None:
    plan = MultiQueryRetrievalPolicy().build(
        original_text=(
            "Analiza la libertad moral en Cervantes; sí; "
            "analiza la libertad moral en Cervantes; "
            "explica la vulnerabilidad social ante la eutanasia"
        ),
        retrieval_text=(
            "analiza la libertad moral en cervantes; sí; "
            "analiza la libertad moral en cervantes; "
            "explica la vulnerabilidad social ante la eutanasia"
        ),
        route_mode="multi_hop",
    )

    facets = [variant.audit_text for variant in plan.variants[1:]]
    assert facets == [
        "analiza la libertad moral en cervantes",
        "explica la vulnerabilidad social ante la eutanasia",
    ]


def test_benchmarked_eutanacia_typo_adds_a_conservative_retrieval_variant() -> None:
    text = (
        "Dicen que la eutanacia demuestra libertad; "
        "analiza la tesis y sus posibles contradicciones"
    )

    plan = MultiQueryRetrievalPolicy().build(
        original_text=text,
        retrieval_text=text,
        route_mode="argumentative",
    )

    assert plan.variants[0].text == text
    assert "eutanasia" in plan.variants[1].text
    assert "eutanacia" not in plan.variants[1].text
    assert len(plan.variants) <= 4


def test_factual_and_exact_routes_never_expand_or_inherit_previous_plan() -> None:
    policy = MultiQueryRetrievalPolicy()
    complex_text = "Describe la libertad en Cervantes; explica también la eutanasia"

    factual = policy.build(
        original_text=complex_text,
        retrieval_text=complex_text,
        route_mode="factual_local",
    )
    exact = policy.build(
        original_text="Busca el código ABC-12345678",
        retrieval_text="busca el código abc-12345678",
        route_mode="exact",
    )

    assert not factual.expanded
    assert factual.reason == "route_not_expandable"
    assert len(factual.variants) == 1
    assert not exact.expanded
    assert len(exact.variants) == 1
