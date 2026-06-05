"""E2E tests for the new Chat API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from atenex_nova.main import app
from tests.e2e.test_document_ingestion_e2e import (
    _create_collection,
)
from tests.e2e.test_document_ingestion_e2e import (
    e2e_env as e2e_env,
)


@pytest.mark.asyncio
async def test_chat_endpoints_lifecycle(e2e_env) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create a collection
        collection_id = await _create_collection(client, "Chats API E2E Collection")

        # 2. List chats (should be empty initially)
        list_res = await client.get(f"/collections/{collection_id}/chats")
        assert list_res.status_code == 200
        assert list_res.json() == []

        # 3. Create a chat
        create_res = await client.post(
            "/chats",
            json={
                "collection_id": collection_id,
                "title": "Discussion about grounding"
            }
        )
        assert create_res.status_code == 201
        chat_data = create_res.json()
        assert chat_data["id"]
        assert chat_data["collection_id"] == collection_id
        assert chat_data["title"] == "Discussion about grounding"
        chat_id = chat_data["id"]

        # 4. List chats again (should contain the newly created chat)
        list_res2 = await client.get(f"/collections/{collection_id}/chats")
        assert list_res2.status_code == 200
        chats = list_res2.json()
        assert len(chats) == 1
        assert chats[0]["id"] == chat_id

        # 5. Get chat messages (should be empty)
        msgs_res = await client.get(f"/chats/{chat_id}/messages")
        assert msgs_res.status_code == 200
        assert msgs_res.json() == []

        # 6. Ask a question within the chat (saving user and assistant turns)
        answer_res = await client.post(
            "/queries/answer",
            json={
                "collection_id": collection_id,
                "query": "Is Atenex Nova RAG grounded?",
                "mode": "auto",
                "chat_id": chat_id,
            }
        )
        assert answer_res.status_code == 200
        answer_data = answer_res.json()
        assert answer_data["chat_history_used"] is not None

        # 7. Get chat messages again (should contain user query and assistant response)
        msgs_res2 = await client.get(f"/chats/{chat_id}/messages")
        assert msgs_res2.status_code == 200
        msgs = msgs_res2.json()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Is Atenex Nova RAG grounded?"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == answer_data["answer"]

        # 8. Delete the chat
        delete_res = await client.delete(f"/chats/{chat_id}")
        assert delete_res.status_code == 204

        # 9. List chats again (should be empty)
        list_res3 = await client.get(f"/collections/{collection_id}/chats")
        assert list_res3.status_code == 200
        assert list_res3.json() == []

        # 10. Fetching messages of a deleted chat should return 404
        msgs_res3 = await client.get(f"/chats/{chat_id}/messages")
        assert msgs_res3.status_code == 404
