"""Application Orchestrator: Ingestion Orchestrator."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.quantization_policy_service import (
    QuantizationPolicyService,
)
from atenex_nova.infrastructure.indexes.quantized_code_store import QuantizedCodeStore
from atenex_nova.infrastructure.indexes.turboquant_candidate_index import (
    TurboQuantCandidateIndex,
    string_to_uint64,
)
from atenex_nova.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Orchestrator coordinating the vector quantization and indexing pipeline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._quant_service = QuantizationPolicyService(session)
        self._code_store = QuantizedCodeStore(session)
        self._candidate_index = TurboQuantCandidateIndex(session)
        self._settings = get_settings()

    async def index_nodes(
        self,
        collection_id: str,
        memory_layer: str,
        node_ids: list[str],
        vectors: list[list[float]],
        embedding_model: str,
        dimension: int,
        tenant_id: str = "",
    ) -> None:
        """Quantize and index a batch of vectors in the candidate index and relational store.

        Args:
            collection_id: The collection namespace.
            memory_layer: The memory layer ("chunk" | "proposition" | "summary" | "visual").
            node_ids: String UUIDs of the nodes.
            vectors: Float vectors corresponding to the nodes.
            embedding_model: The name of the embedding model used.
            dimension: The vector dimension.
            tenant_id: The optional tenant ID.
        """
        if not node_ids or not vectors:
            return

        # 1. Resolve or create quantization profile
        profile = await self._quant_service.get_or_create_profile(
            embedding_model=embedding_model, dimension=dimension
        )

        # 2. Quantize vectors and save to relational DB code store
        for node_id, vector in zip(node_ids, vectors, strict=False):
            code = self._quant_service.quantize(vector, profile)
            uint64_id = string_to_uint64(node_id)
            await self._code_store.save_vector(
                node_id=node_id,
                uint64_id=uint64_id,
                collection_id=collection_id,
                memory_layer=memory_layer,
                profile_id=profile.id,
                idx_blob=code["idx_blob"],
                qjl_blob=code["qjl_blob"],
                residual_norm=code["residual_norm"],
                vector_norm=code["vector_norm"],
            )

        # 3. Add to the local turbovec IdMapIndex file
        await self._candidate_index.add_vectors(
            collection_id=collection_id,
            memory_layer=memory_layer,
            node_ids=node_ids,
            vectors=vectors,
        )

        logger.info(
            "Quantized and indexed %d vectors for collection %s layer %s",
            len(node_ids),
            collection_id,
            memory_layer,
        )
