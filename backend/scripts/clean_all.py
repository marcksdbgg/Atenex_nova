"""Atenex Nova — full clean-slate utility.

Wipes EVERY collection and derived artifact so the new architecture can be
re-tested from scratch:

  1. Relational store (SQLite or PostgreSQL, whichever ``ATENEX_DATABASE_URL``
     points at): drops and recreates every ORM table.
  2. Qdrant: deletes every collection on the configured server (chunks,
     ``*_propositions``, ``*_summaries``, ``pages_visual`` and any leftovers).
  3. Local on-disk storage: ``storage/turbovec`` (``*.tvim``),
     ``storage/visual_pages`` and ``storage/uploads``.

It does NOT touch original source files referenced by document source paths
unless they happen to live under ``storage/uploads``.

Usage (Windows / PowerShell, from the ``backend`` folder):

    .venv312\\Scripts\\python.exe scripts\\clean_all.py --yes

Add ``--keep-uploads`` to preserve uploaded blobs, or ``--sql-only`` /
``--qdrant-only`` / ``--storage-only`` to scope the wipe.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

# Make ``atenex_nova`` importable when run as a plain script.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from atenex_nova.shared.config.settings import get_settings  # noqa: E402


async def wipe_sql() -> None:
    from sqlmodel import SQLModel

    from atenex_nova.infrastructure.db.models import tables  # noqa: F401  (register metadata)
    from atenex_nova.infrastructure.db.session import dispose_engine, get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    await dispose_engine()
    print(f"[sql] dropped + recreated all tables on {get_settings().database_url.split('://')[0]}")


async def wipe_qdrant() -> None:
    from urllib.parse import urlparse

    from qdrant_client import AsyncQdrantClient

    settings = get_settings()
    endpoint = urlparse(settings.qdrant_url)
    client = AsyncQdrantClient(host=endpoint.hostname or "localhost", port=endpoint.port or 6333)
    try:
        collections = (await client.get_collections()).collections
        for col in collections:
            await client.delete_collection(col.name)
            print(f"[qdrant] deleted collection {col.name}")
        if not collections:
            print("[qdrant] no collections found (already clean)")
    finally:
        await client.close()


def wipe_storage(keep_uploads: bool) -> None:
    settings = get_settings()
    targets = [settings.turbovec_path, settings.visual_pages_path]
    if not keep_uploads:
        targets.append(settings.blob_store_path)
    for target in targets:
        target = Path(target)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            print(f"[storage] removed {target}")
        target.mkdir(parents=True, exist_ok=True)
        print(f"[storage] recreated empty {target}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Wipe all Atenex Nova collections and artifacts.")
    parser.add_argument("--yes", action="store_true", help="Run without interactive confirmation.")
    parser.add_argument("--keep-uploads", action="store_true", help="Preserve storage/uploads blobs.")
    parser.add_argument("--sql-only", action="store_true")
    parser.add_argument("--qdrant-only", action="store_true")
    parser.add_argument("--storage-only", action="store_true")
    args = parser.parse_args()

    scoped = args.sql_only or args.qdrant_only or args.storage_only
    do_sql = args.sql_only or not scoped
    do_qdrant = args.qdrant_only or not scoped
    do_storage = args.storage_only or not scoped

    if not args.yes:
        settings = get_settings()
        print("This will PERMANENTLY delete all collections / derived data:")
        print(f"  DB:      {settings.database_url}")
        print(f"  Qdrant:  {settings.qdrant_url}")
        print(f"  Storage: {settings.turbovec_path}, {settings.visual_pages_path}, {settings.blob_store_path}")
        if input("Type 'wipe' to continue: ").strip().lower() != "wipe":
            print("Aborted.")
            return

    if do_sql:
        await wipe_sql()
    if do_qdrant:
        try:
            await wipe_qdrant()
        except Exception as exc:  # noqa: BLE001
            print(f"[qdrant] skipped/failed (is Qdrant running?): {exc}")
    if do_storage:
        wipe_storage(keep_uploads=args.keep_uploads)

    print("Done. Clean slate ready.")


if __name__ == "__main__":
    asyncio.run(main())
