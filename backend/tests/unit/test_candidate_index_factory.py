"""Unit tests for candidate index factory backend selection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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
