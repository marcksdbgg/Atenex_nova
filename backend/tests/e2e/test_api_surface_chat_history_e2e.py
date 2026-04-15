"""E2E smoke coverage for public API surface: ingestion -> query/chat -> history."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from atenex_nova.main import app
from tests.e2e.test_document_ingestion_e2e import (
    _create_collection,
    _run_jobs_to_completion,
)
from tests.e2e.test_document_ingestion_e2e import (
    e2e_env as e2e_env,
)


@pytest.mark.asyncio
async def test_api_surface_ingestion_to_chat_history(e2e_env, tmp_path: Path) -> None:
    session_factory = e2e_env["session_factory"]

    source_file = tmp_path / "api-surface-source.txt"
    source_file.write_text(
        "Atenex Nova stores grounded evidence with citations.\n"
        "Query history must include answer metadata and route mode.",
        encoding="utf-8",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        collection_id = await _create_collection(client, "API Surface E2E")

        imported = await client.post(
            f"/collections/{collection_id}/documents/import",
            json={
                "source_path": str(source_file),
                "title": "API Surface Source",
                "mime_type": "text/plain",
                "collection_path": "chat/history/source.txt",
            },
        )
        assert imported.status_code == 201
        document = imported.json()
        document_id = document["id"]

        await _run_jobs_to_completion(session_factory)

        listed_collections = await client.get("/collections")
        assert listed_collections.status_code == 200
        assert any(item["id"] == collection_id for item in listed_collections.json())

        fetched_collection = await client.get(f"/collections/{collection_id}")
        assert fetched_collection.status_code == 200

        patched_collection = await client.patch(
            f"/collections/{collection_id}",
            json={"description": "API smoke description"},
        )
        assert patched_collection.status_code == 200
        assert patched_collection.json()["description"] == "API smoke description"

        listed_documents = await client.get(f"/collections/{collection_id}/documents", params={"limit": 200})
        assert listed_documents.status_code == 200
        assert any(item["id"] == document_id for item in listed_documents.json())

        fetched_document = await client.get(f"/documents/{document_id}")
        assert fetched_document.status_code == 200
        assert fetched_document.json()["id"] == document_id

        fetched_nodes = await client.get(f"/documents/{document_id}/nodes")
        assert fetched_nodes.status_code == 200
        assert fetched_nodes.json()

        searched = await client.post(
            "/queries/search",
            json={
                "collection_id": collection_id,
                "query": "How does Atenex Nova keep evidence grounded?",
                "mode": "auto",
            },
        )
        assert searched.status_code == 200
        search_payload = searched.json()
        assert search_payload["query_id"]
        assert search_payload["hits"]

        answered = await client.post(
            "/queries/answer",
            json={
                "collection_id": collection_id,
                "query": "Summarize grounding and citations behavior",
                "mode": "auto",
                "generation_profile": "standard",
            },
        )
        assert answered.status_code == 200
        answer_payload = answered.json()
        assert answer_payload["answer_id"]
        assert answer_payload["query_id"]
        assert isinstance(answer_payload["answer"], str)
        assert answer_payload["route_mode"]

        history = await client.get("/queries/history", params={"collection_id": collection_id, "limit": 50})
        assert history.status_code == 200
        history_items = history.json()
        assert any(item["query_id"] == answer_payload["query_id"] for item in history_items)

        answer_id = answer_payload["answer_id"]
        fetched_answer = await client.get(f"/answers/{answer_id}")
        assert fetched_answer.status_code == 200
        assert fetched_answer.json()["answer_id"] == answer_id

        markdown_export = await client.get(f"/answers/{answer_id}/export/markdown")
        assert markdown_export.status_code == 200
        assert markdown_export.headers["content-type"].startswith("text/markdown")

        pdf_export = await client.get(f"/answers/{answer_id}/export/pdf")
        assert pdf_export.status_code == 200
        assert pdf_export.headers["content-type"].startswith("application/pdf")

        jobs = await client.get("/jobs", params={"limit": 100})
        assert jobs.status_code == 200
        jobs_payload = jobs.json()
        assert jobs_payload
        job_id = jobs_payload[0]["id"]

        job_detail = await client.get(f"/jobs/{job_id}")
        assert job_detail.status_code == 200
        assert job_detail.json()["id"] == job_id

        audit_list = await client.get(
            "/observability/audit",
            params={"entity_type": "document", "entity_id": document_id, "limit": 200},
        )
        assert audit_list.status_code == 200
        assert audit_list.json()

        evidence = await client.get(f"/observability/documents/{document_id}/evidence")
        assert evidence.status_code == 200
        evidence_payload = evidence.json()
        assert evidence_payload["document"]["id"] == document_id

        datasets = await client.get("/evaluation/datasets")
        assert datasets.status_code == 200

        runs = await client.get("/evaluation/runs")
        assert runs.status_code == 200
