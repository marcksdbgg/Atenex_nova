"""EmbeddingGemma query/document prompt contract tests."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.shared.config.settings import Settings
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


class _EmbeddingResponse:
    def __init__(self, count: int) -> None:
        self._count = count

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"embeddings": [[1.0, 0.0] for _ in range(self._count)]}


class _RecordingClient:
    payloads: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> _EmbeddingResponse:
        _ = url
        type(self).payloads.append(json)
        inputs = json["input"]
        assert isinstance(inputs, list)
        return _EmbeddingResponse(len(inputs))


class _OrderedBatchResponse:
    def __init__(self, inputs: list[str]) -> None:
        self._inputs = inputs

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "embeddings": [[float(value), 1.0] for value in self._inputs],
        }


class _OrderedBatchClient:
    batches: ClassVar[list[list[str]]] = []
    fail_on_call: ClassVar[int | None] = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _OrderedBatchClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any]) -> _OrderedBatchResponse:
        _ = url
        inputs = json["input"]
        assert isinstance(inputs, list)
        batch = [str(value) for value in inputs]
        type(self).batches.append(batch)
        if type(self).fail_on_call == len(type(self).batches):
            raise ConnectionError("simulated Ollama failure")
        return _OrderedBatchResponse(batch)


@pytest.mark.asyncio
async def test_embedding_inputs_use_official_query_and_document_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.httpx.AsyncClient",
        _RecordingClient,
    )
    _RecordingClient.payloads = []
    adapter = EmbeddingGemmaAdapter(dim=2)

    await adapter.embed_query("What did Cervantes say?")
    await adapter.embed_documents(
        ["First passage", "Second passage"],
        titles=["Cervantes", None],
    )

    assert _RecordingClient.payloads[0]["input"] == [
        "task: search result | query: What did Cervantes say?"
    ]
    assert _RecordingClient.payloads[1]["input"] == [
        "title: Cervantes | text: First passage",
        "title: none | text: Second passage",
    ]


@pytest.mark.asyncio
async def test_embedding_prompts_are_configurable_and_title_is_single_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        embedding_query_prefix="query::",
        embedding_document_prefix="document[{title}]::",
        embedding_default_document_title="untitled",
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.httpx.AsyncClient",
        _RecordingClient,
    )
    _RecordingClient.payloads = []
    adapter = EmbeddingGemmaAdapter(dim=2)

    await adapter.embed_query("question")
    await adapter.embed_documents(["passage"], titles=["Line one\nLine two"])

    assert _RecordingClient.payloads[0]["input"] == ["query::question"]
    assert _RecordingClient.payloads[1]["input"] == [
        "document[Line one Line two]::passage"
    ]


@pytest.mark.asyncio
async def test_document_embedding_rejects_misaligned_titles() -> None:
    adapter = EmbeddingGemmaAdapter.__new__(EmbeddingGemmaAdapter)

    with pytest.raises(ValueError, match="same length"):
        await adapter.embed_documents(["one", "two"], titles=["only one"])


def test_embedding_contract_fingerprint_changes_with_vector_compatibility_inputs() -> None:
    baseline = Settings()

    assert baseline.embedding_contract_fingerprint == Settings().embedding_contract_fingerprint
    assert baseline.embedding_contract_fingerprint.startswith("emb-v2-")
    assert baseline.embedding_contract_fingerprint != Settings(
        embedding_query_prefix="query::",
    ).embedding_contract_fingerprint
    assert baseline.embedding_contract_fingerprint != Settings(
        chunk_max_tokens=900,
    ).embedding_contract_fingerprint


@pytest.mark.asyncio
async def test_ollama_embeddings_preserve_order_across_full_and_final_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(embedding_batch_size=2)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.httpx.AsyncClient",
        _OrderedBatchClient,
    )
    _OrderedBatchClient.batches = []
    _OrderedBatchClient.fail_on_call = None
    adapter = EmbeddingGemmaAdapter(dim=2, required=True)

    vectors = await adapter.embed(["1", "2", "3", "4", "5"])

    assert _OrderedBatchClient.batches == [["1", "2"], ["3", "4"], ["5"]]
    assert len(vectors) == 5
    assert [round(vector[0], 6) for vector in vectors] == sorted(
        round(vector[0], 6) for vector in vectors
    )


@pytest.mark.asyncio
async def test_ollama_batch_failure_aborts_strict_embedding_without_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(embedding_batch_size=2)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "atenex_nova.infrastructure.embeddings.embedding_adapter.httpx.AsyncClient",
        _OrderedBatchClient,
    )
    _OrderedBatchClient.batches = []
    _OrderedBatchClient.fail_on_call = 2
    adapter = EmbeddingGemmaAdapter(dim=2, required=True)

    with pytest.raises(
        ServiceUnavailableError,
        match=r"embedding generation failed: ollama embedding batch 2 failed",
    ):
        await adapter.embed(["1", "2", "3"])

    assert _OrderedBatchClient.batches == [["1", "2"], ["3"]]
