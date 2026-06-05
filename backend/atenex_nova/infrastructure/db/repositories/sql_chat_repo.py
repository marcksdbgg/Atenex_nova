"""SQL repository: Chat and ChatMessage."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.chat import Chat, ChatMessage
from atenex_nova.infrastructure.db.models.tables import ChatMessageModel, ChatModel


class SqlChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_chat(self, chat: Chat) -> Chat:
        model = ChatModel(
            id=chat.id,
            collection_id=chat.collection_id,
            title=chat.title,
            created_at=chat.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return chat

    async def get_chat(self, chat_id: str) -> Chat | None:
        result = await self._session.execute(select(ChatModel).where(ChatModel.id == chat_id))
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Chat(
            id=model.id,
            collection_id=model.collection_id,
            title=model.title,
            created_at=model.created_at,
        )

    async def delete_chat(self, chat_id: str) -> None:
        # Cascade delete is handled by database or manually to be sure
        await self._session.execute(delete(ChatMessageModel).where(ChatMessageModel.chat_id == chat_id))
        await self._session.execute(delete(ChatModel).where(ChatModel.id == chat_id))
        await self._session.flush()

    async def list_chats_by_collection(self, collection_id: str, limit: int = 50) -> list[Chat]:
        result = await self._session.execute(
            select(ChatModel)
            .where(ChatModel.collection_id == collection_id)
            .order_by(ChatModel.created_at.desc())
            .limit(limit)
        )
        return [
            Chat(
                id=model.id,
                collection_id=model.collection_id,
                title=model.title,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        model = ChatMessageModel(
            id=message.id,
            chat_id=message.chat_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return message

    async def get_last_messages(self, chat_id: str, limit: int = 5) -> list[ChatMessage]:
        result = await self._session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.chat_id == chat_id)
            .order_by(ChatMessageModel.created_at.desc())
            .limit(limit)
        )
        # Reverse them so they are in chronological order (oldest first)
        messages = [
            ChatMessage(
                id=model.id,
                chat_id=model.chat_id,
                role=model.role,
                content=model.content,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]
        messages.reverse()
        return messages
