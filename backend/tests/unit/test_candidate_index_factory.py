"""Unit tests for candidate index factory backend selection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from atenex_nova.infrastructure.indexes.candidate_index_factory import (
    build_candidate_index,
    is_turbovec_available,
)
from atenex_nova.infrastructure.indexes.purepy_candidate_index import (
    PurePyTurboQuantCandidateIndex,
)
from atenex_nova.infrastructure.indexes.turboquant_candidate_index import (
    TurboQuantCandidateIndex,
)
from atenex_nova.shared.config.settings import EmbeddingProfile, Settings


@pytest.fixture()
def session() -> MagicMock:
    return MagicMock()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Settings:
    settings = Settings(**overrides)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    return settings


def test_purepy_backend_always_returns_purepy(session: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, candidate_backend="purepy")
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: True,
    )

    index = build_candidate_index(session)

    assert isinstance(index, PurePyTurboQuantCandidateIndex)
    assert not isinstance(index, TurboQuantCandidateIndex)


def test_turbovec_backend_when_available(session: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, candidate_backend="turbovec")
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: True,
    )

    index = build_candidate_index(session)

    assert isinstance(index, TurboQuantCandidateIndex)


def test_turbovec_backend_raises_when_unavailable(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, candidate_backend="turbovec")
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: False,
    )

    with pytest.raises(ImportError, match="ATENEX_CANDIDATE_BACKEND=turbovec"):
        build_candidate_index(session)


@pytest.mark.parametrize("profile", [EmbeddingProfile.LITE, EmbeddingProfile.STANDARD, EmbeddingProfile.MAX])
def test_auto_uses_purepy_even_when_turbovec_available(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingProfile,
) -> None:
    _patch_settings(monkeypatch, candidate_backend="auto", embedding_profile=profile)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: True,
    )

    index = build_candidate_index(session)

    assert isinstance(index, PurePyTurboQuantCandidateIndex)
    assert not isinstance(index, TurboQuantCandidateIndex)


def test_auto_falls_back_to_purepy_when_turbovec_missing(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, candidate_backend="auto", embedding_profile=EmbeddingProfile.STANDARD)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: False,
    )

    index = build_candidate_index(session)

    assert isinstance(index, PurePyTurboQuantCandidateIndex)


def test_has_usable_turbovec_index_false_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from atenex_nova.infrastructure.indexes.candidate_index_factory import has_usable_turbovec_index

    settings = Settings(turbovec_path=tmp_path)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.get_settings",
        lambda: settings,
    )
    assert has_usable_turbovec_index("collection-id", "chunk") is False


def test_auto_uses_purepy_for_max_profile_even_when_turbovec_available(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, candidate_backend="auto", embedding_profile=EmbeddingProfile.MAX)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        lambda: True,
    )

    index = build_candidate_index(session)

    assert isinstance(index, PurePyTurboQuantCandidateIndex)


def test_is_turbovec_available_reflects_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.candidate_index_factory.is_turbovec_available",
        is_turbovec_available,
    )
    # Smoke check: real environment may or may not have turbovec; just ensure bool return.
    assert isinstance(is_turbovec_available(), bool)


@pytest.mark.asyncio
async def test_purepy_refuses_an_unbounded_layer_scan(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(purepy_max_vectors_per_layer=2)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.purepy_candidate_index.get_settings",
        lambda: settings,
    )
    index = PurePyTurboQuantCandidateIndex(session)
    index._store.count_vectors_by_layer = AsyncMock(return_value=3)
    index._store.get_vectors_by_layer = AsyncMock(return_value=[])

    result = await index.search("collection", ["proposition"], [0.1] * 384, top_n=10)

    assert result == []
    index._store.get_vectors_by_layer.assert_not_awaited()


@pytest.mark.asyncio
async def test_purepy_rejects_vectors_from_an_old_embedding_contract(
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(purepy_max_vectors_per_layer=10)
    monkeypatch.setattr(
        "atenex_nova.infrastructure.indexes.purepy_candidate_index.get_settings",
        lambda: settings,
    )
    index = PurePyTurboQuantCandidateIndex(session)
    index._store.count_vectors_by_layer = AsyncMock(return_value=1)
    index._store.get_vectors_by_layer = AsyncMock(
        return_value=[
            SimpleNamespace(
                profile_id="legacy-profile",
                node_id="legacy-node",
                idx_blob=b"idx",
                qjl_blob=b"qjl",
                residual_norm=0.0,
                vector_norm=1.0,
            )
        ]
    )
    index._store.get_profile = AsyncMock(
        return_value=SimpleNamespace(codebook_version="v1-b4")
    )
    index._quantizer.estimate_inner_products = MagicMock(return_value=[1.0])

    result = await index.search("collection", ["chunk"], [0.1] * 384, top_n=10)

    assert result == []
    index._quantizer.estimate_inner_products.assert_not_called()
