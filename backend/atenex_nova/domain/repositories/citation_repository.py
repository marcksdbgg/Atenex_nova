"""Citation repository protocol."""

from typing import Protocol

from atenex_nova.domain.entities.citation import Citation


class CitationRepository(Protocol):
    async def create_many(self, citations: list[Citation]) -> list[Citation]: ...

    async def list_by_answer(self, answer_id: str) -> list[Citation]: ...