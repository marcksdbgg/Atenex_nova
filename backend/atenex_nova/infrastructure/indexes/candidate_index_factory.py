"""Factory for CandidateIndexPort implementations (purepy vs turbovec)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.ports.candidate_index import CandidateIndexPort
from atenex_nova.shared.config.settings import get_settings

_TURBOVEC_UNAVAILABLE_MSG = (
    "turbovec is required when ATENEX_CANDIDATE_BACKEND=turbovec. "
    "Install with: pip install 'atenex-nova[accel]'"
)


def is_turbovec_available() -> bool:
    """Return True when the optional turbovec package can be imported."""
    try:
        import turbovec  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False
    return True


def turbovec_index_path(collection_id: str, memory_layer: str) -> Path:
    """Path to the on-disk turbovec index for a collection layer."""
    settings = get_settings()
    return Path(settings.turbovec_path) / f"{collection_id}_{memory_layer}.tvim"


def has_usable_turbovec_index(collection_id: str, memory_layer: str = "chunk") -> bool:
    """True when a non-empty ``.tvim`` file exists for the collection layer."""
    path = turbovec_index_path(collection_id, memory_layer)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def build_candidate_index(session: AsyncSession) -> CandidateIndexPort:
    """Build the configured candidate index backend for *session*."""
    settings = get_settings()
    backend = settings.candidate_backend

    if backend == "purepy":
        from atenex_nova.infrastructure.indexes.purepy_candidate_index import (
            PurePyTurboQuantCandidateIndex,
        )

        return PurePyTurboQuantCandidateIndex(session)

    if backend == "turbovec":
        if not is_turbovec_available():
            raise ImportError(_TURBOVEC_UNAVAILABLE_MSG)
        from atenex_nova.infrastructure.indexes.turboquant_candidate_index import (
            TurboQuantCandidateIndex,
        )

        return TurboQuantCandidateIndex(session)

    # auto: canonical path is purepy. Never pick turbovec only because import works.
    from atenex_nova.infrastructure.indexes.purepy_candidate_index import (
        PurePyTurboQuantCandidateIndex,
    )

    return PurePyTurboQuantCandidateIndex(session)
