"""Deterministic policy for conversational retrieval context."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

CONVERSATION_CONTEXT_MARKER = (
    "Contexto conversacional previo para resolver referencias:"
)

_FOLLOW_UP_PATTERNS = (
    re.compile(r"^\s*[\u00bf?]*(?:y|pero|entonces|ademas|además)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:él|ella|ellos|ellas|eso|esa|ese|esto|aquello|"
        r"lo anterior|la anterior|el anterior|dicho|dicha|dichos|dichas)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mencionaste|dijiste|explicaste|comentaste|"
        r"you said|you mentioned|as above|the former|the latter)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:profundiza|amplia|amplía|continua|continúa|sigue|"
        r"explica mas|explica más|tell me more|go on|continue)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:what|how)\s+about\s+(?:that|this|him|her|them)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, slots=True)
class ContextualizedRetrievalQuery:
    """Original query plus an optional, bounded retrieval-only representation."""

    original_text: str
    retrieval_text: str
    history_messages_used: int

    @property
    def contextualized(self) -> bool:
        return self.history_messages_used > 0


class ConversationRetrievalPolicy:
    """Adds explicit chat context only when the new turn contains a follow-up cue.

    The policy has no mutable state and never calls an LLM. A standalone query, even
    when executed after a conversational query, therefore cannot inherit old terms.
    """

    max_messages = 4
    max_chars_per_message = 400
    max_history_chars = 1_200

    def build(
        self,
        query_text: str,
        messages: Sequence[object] | None = None,
    ) -> ContextualizedRetrievalQuery:
        original_text = query_text
        retrieval_text = query_text.strip()
        if not messages or not self._needs_context(retrieval_text):
            return ContextualizedRetrievalQuery(
                original_text=original_text,
                retrieval_text=retrieval_text,
                history_messages_used=0,
            )

        extracted: list[tuple[str, str]] = []
        for message in messages:
            parsed = self._extract_message(message)
            if parsed is None:
                continue
            role, content = parsed
            if content.casefold() == retrieval_text.casefold():
                continue
            extracted.append((role, content))

        selected: list[tuple[str, str]] = []
        remaining_chars = self.max_history_chars
        for role, content in reversed(extracted[-self.max_messages :]):
            if remaining_chars <= 0:
                break
            bounded = content[: min(self.max_chars_per_message, remaining_chars)].rstrip()
            if not bounded:
                continue
            selected.append((role, bounded))
            remaining_chars -= len(bounded)
        selected.reverse()

        if not selected:
            return ContextualizedRetrievalQuery(
                original_text=original_text,
                retrieval_text=retrieval_text,
                history_messages_used=0,
            )

        history = "\n".join(
            f"{'Usuario' if role == 'user' else 'Asistente'}: {content}"
            for role, content in selected
        )
        contextualized_text = (
            f"{retrieval_text}\n\n"
            f"{CONVERSATION_CONTEXT_MARKER}\n"
            f"{history}"
        )
        return ContextualizedRetrievalQuery(
            original_text=original_text,
            retrieval_text=contextualized_text,
            history_messages_used=len(selected),
        )

    @staticmethod
    def _needs_context(query_text: str) -> bool:
        return bool(query_text) and any(pattern.search(query_text) for pattern in _FOLLOW_UP_PATTERNS)

    @staticmethod
    def _extract_message(message: object) -> tuple[str, str] | None:
        if isinstance(message, Mapping):
            raw_role = message.get("role")
            raw_content = message.get("content")
        else:
            raw_role = getattr(message, "role", None)
            raw_content = getattr(message, "content", None)

        if not isinstance(raw_role, str) or not isinstance(raw_content, str):
            return None
        role = raw_role.strip().lower()
        if role not in {"user", "assistant"}:
            return None
        content = " ".join(raw_content.split())
        if not content:
            return None
        return role, content
