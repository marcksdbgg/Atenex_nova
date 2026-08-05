"""Policies for vector indexing and Qdrant dense placement."""

from __future__ import annotations

from atenex_nova.shared.config.settings import Settings


def dense_goes_to_qdrant(settings: Settings) -> bool:
    """Return True when dense float32 vectors should be stored in Qdrant.

    Qdrant is the scalable dense index for every embedding profile when enabled.
    Quantized SQL codes remain a bounded offline fallback, not the primary live
    retrieval path for large collections.
    """
    return bool(getattr(settings, "qdrant_dense_enabled", True))
