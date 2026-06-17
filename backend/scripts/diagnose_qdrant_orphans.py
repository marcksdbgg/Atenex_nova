"""Read-only Qdrant orphan collection diagnosis."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atenex_nova.infrastructure.db.models import tables as _tables  # noqa: F401
from atenex_nova.infrastructure.db.models.tables import CollectionModel
from atenex_nova.infrastructure.db.session import get_engine
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter


def _collection_ids_from_qdrant_name(name: str) -> str | None:
    if name.startswith("collection_") and name.endswith("_propositions"):
        return name.removeprefix("collection_").removesuffix("_propositions")
    if name.startswith("collection_") and name.endswith("_summaries"):
        return name.removeprefix("collection_").removesuffix("_summaries")
    if name.startswith("collection_"):
        return name.removeprefix("collection_")
    return None


async def diagnose() -> dict[str, object]:
    adapter = QdrantAdapter(host="localhost", port=6333)
    qdrant_collections = await adapter.list_collections()
    qdrant_names = {item["name"] for item in qdrant_collections}

    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(CollectionModel.id))
        live_ids = {str(row[0]) for row in result.all()}

    referenced_ids = {
        collection_id
        for name in qdrant_names
        for collection_id in [_collection_ids_from_qdrant_name(name)]
        if collection_id
    }
    orphan_ids = sorted(referenced_ids - live_ids)
    missing_ids = sorted(live_ids - referenced_ids)

    return {
        "qdrant_collections": sorted(qdrant_names),
        "live_sql_collections": sorted(live_ids),
        "orphan_collection_ids": orphan_ids,
        "collections_without_qdrant_chunks": missing_ids,
    }


def main() -> int:
    report = asyncio.run(diagnose())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
