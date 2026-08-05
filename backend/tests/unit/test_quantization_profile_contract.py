"""Quantized candidates must be namespaced by the active embedding contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atenex_nova.application.services.quantization_policy_service import (
    QuantizationPolicyService,
)
from atenex_nova.shared.config.settings import Settings


@pytest.mark.asyncio
async def test_new_quantization_profile_carries_embedding_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    monkeypatch.setattr(
        "atenex_nova.application.services.quantization_policy_service.get_settings",
        lambda: settings,
    )
    service = QuantizationPolicyService(MagicMock())
    service._store.get_profile_by_config = AsyncMock(return_value=None)
    service._store.save_profile = AsyncMock()

    profile = await service.get_or_create_profile("embeddinggemma", 384)

    assert profile.codebook_version.endswith(
        f"|{settings.embedding_contract_fingerprint}"
    )
    service._store.get_profile_by_config.assert_awaited_once_with(
        embedding_model="embeddinggemma",
        dimension=384,
        bit_width=4,
        codebook_version=profile.codebook_version,
    )
    service._store.save_profile.assert_awaited_once_with(profile)
