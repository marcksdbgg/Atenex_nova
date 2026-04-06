"""Answer repository protocol."""

from typing import Protocol

from atenex_nova.domain.entities.answer import Answer


class AnswerRepository(Protocol):
    async def create(self, answer: Answer) -> Answer: ...
    async def get_by_id(self, answer_id: str) -> Answer | None: ...