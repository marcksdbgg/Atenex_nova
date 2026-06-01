"""Chats router."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.chat import Chat
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.repositories.sql_chat_repo import SqlChatRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import (
    ChatMessageResponse,
    ChatResponse,
    CreateChatRequest,
)

router = APIRouter(tags=["chats"])


@router.post("/chats", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    body: CreateChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    chat_repo = SqlChatRepository(session)
    chat = Chat(
        id=new_id(),
        collection_id=body.collection_id,
        title=body.title,
    )
    await chat_repo.create_chat(chat)
    # The session will commit automatically because of get_session dependency cleanup
    return ChatResponse(
        id=chat.id,
        collection_id=chat.collection_id,
        title=chat.title,
        created_at=chat.created_at,
    )


@router.get("/collections/{collection_id}/chats", response_model=list[ChatResponse])
async def list_chats(
    collection_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[ChatResponse]:
    chat_repo = SqlChatRepository(session)
    chats = await chat_repo.list_by_collection(collection_id=collection_id, limit=limit) if hasattr(chat_repo, 'list_by_collection') else await chat_repo.list_chats_by_collection(collection_id=collection_id, limit=limit)
    return [
        ChatResponse(
            id=c.id,
            collection_id=c.collection_id,
            title=c.title,
            created_at=c.created_at,
        )
        for c in chats
    ]


@router.get("/chats/{chat_id}/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(
    chat_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[ChatMessageResponse]:
    chat_repo = SqlChatRepository(session)
    chat = await chat_repo.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await chat_repo.get_last_messages(chat_id=chat_id, limit=limit)
    return [
        ChatMessageResponse(
            id=m.id,
            chat_id=m.chat_id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    chat_repo = SqlChatRepository(session)
    chat = await chat_repo.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    await chat_repo.delete_chat(chat_id)
