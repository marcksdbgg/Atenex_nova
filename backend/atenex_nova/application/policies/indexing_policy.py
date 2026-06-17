"""Policies for vector indexing and Qdrant dense placement."""

from __future__ import annotations

from typing import cast

from atenex_nova.shared.config.settings import EmbeddingProfile, Settings


def dense_goes_to_qdrant(settings: Settings) -> bool:
    """Return True when dense float32 vectors should be stored in Qdrant.

    Only the MAX embedding profile (768d) keeps a Qdrant dense copy.
    LITE and STANDARD use quantized SQL codes as the canonical dense store.
    """
    profile = cast(EmbeddingProfile | None, getattr(settings, "embedding_profile", None))
    if profile is not None:
        return profile == EmbeddingProfile.MAX
    dimensions = getattr(settings, "embedding_dimensions", None)
    if dimensions is not None:
        return int(dimensions) >= 768
    return False
