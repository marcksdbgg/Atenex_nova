"""Unit coverage for bounded conversational retrieval context."""

from __future__ import annotations

from atenex_nova.application.policies.conversation_retrieval_policy import (
    ConversationRetrievalPolicy,
)
from atenex_nova.domain.entities.chat import ChatMessage


def test_standalone_query_does_not_inherit_history() -> None:
    policy = ConversationRetrievalPolicy()
    history = [
        ChatMessage(id="m1", chat_id="chat", role="user", content="Hablemos de Cervantes"),
        ChatMessage(id="m2", chat_id="chat", role="assistant", content="De acuerdo"),
    ]

    result = policy.build("¿Qué es la entropía?", history)

    assert result.original_text == "¿Qué es la entropía?"
    assert result.retrieval_text == "¿Qué es la entropía?"
    assert result.history_messages_used == 0
    assert not result.contextualized


def test_referential_query_uses_recent_bounded_user_and_assistant_turns() -> None:
    policy = ConversationRetrievalPolicy()
    history: list[object] = [
        {"role": "system", "content": "must be ignored"},
        ChatMessage(id="m0", chat_id="chat", role="user", content="old " + ("x" * 500)),
        ChatMessage(
            id="m1",
            chat_id="chat",
            role="user",
            content="Estamos hablando de Cervantes y su concepción del amor.",
        ),
        ChatMessage(
            id="m2",
            chat_id="chat",
            role="assistant",
            content="La respuesta distinguió el amor vivido del amor fingido.",
        ),
        {"role": "user", "content": "Compara esas dos ideas."},
        {"role": "assistant", "content": "La primera se presentó como experiencia sincera."},
    ]

    result = policy.build("¿Y qué decía él?", history)

    assert result.original_text == "¿Y qué decía él?"
    assert result.retrieval_text.startswith("¿Y qué decía él?")
    assert "Cervantes" in result.retrieval_text
    assert "amor fingido" in result.retrieval_text
    assert "must be ignored" not in result.retrieval_text
    assert "old " not in result.retrieval_text
    assert result.history_messages_used == policy.max_messages
    assert result.contextualized


def test_policy_has_no_cross_query_state() -> None:
    policy = ConversationRetrievalPolicy()
    contextualized = policy.build(
        "Explica más eso",
        [{"role": "user", "content": "Tema privado de la conversación anterior"}],
    )
    independent = policy.build("Define aprendizaje continuo")

    assert contextualized.contextualized
    assert independent.retrieval_text == "Define aprendizaje continuo"
    assert independent.history_messages_used == 0
