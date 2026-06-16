"""Application Service: Quantization Policy Service."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models.tables import QuantizationProfileModel
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.vector_quantization.profile_registry import (
    TurboQuantProfileRegistry,
)
from atenex_nova.infrastructure.vector_quantization.turboquant_adapter import (
    TurboQuantAdapter,
)
from atenex_nova.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


class QuantizationPolicyService:
    """Service to coordinate quantization profiles and adapter invocation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._store = QuantizedCodeStore(session)
        self._adapter = TurboQuantAdapter()
        self._settings = get_settings()

    async def get_or_create_profile(
        self, embedding_model: str, dimension: int
    ) -> QuantizationProfileModel:
        """Get or create the quantization profile based on settings and dimension."""
        # Check settings for configured bit width (defaults to 4)
        bit_width = 4
        if hasattr(self._settings, "turbovec_bit_width") and self._settings.turbovec_bit_width:
            bit_width = int(self._settings.turbovec_bit_width)

        profile = await self._store.get_profile_by_config(
            embedding_model=embedding_model,
            dimension=dimension,
            bit_width=bit_width,
        )

        if profile is None:
            defaults = TurboQuantProfileRegistry.get_profile_defaults(bit_width)
            profile = QuantizationProfileModel(
                id=new_id(),
                algorithm="turboquant_prod",
                embedding_model=embedding_model,
                dimension=dimension,
                bit_width=bit_width,
                rotation_seed=defaults["rotation_seed"],
                qjl_seed=defaults["qjl_seed"],
                codebook_version=defaults["codebook_version"],
            )
            await self._store.save_profile(profile)
            logger.info(
                "Created new quantization profile: %s (algorithm=%s, bits=%d)",
                profile.id,
                profile.algorithm,
                profile.bit_width,
            )

        return profile

    def quantize(self, vector: list[float], profile: QuantizationProfileModel) -> dict[str, Any]:
        """Quantize a vector using the given profile."""
        return self._adapter.quantize(vector, profile)

    def dequantize(self, code: dict[str, Any], profile: QuantizationProfileModel) -> list[float]:
        """Dequantize a code block back to float representation."""
        return self._adapter.dequantize(code, profile)
