"""Atenex Nova — Database session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from atenex_nova.shared.config.settings import get_settings

_engine = None
_session_factory = None

# Backward-compatible alias used by older worker wiring.
async_session_factory = None


def get_engine():
    """Get or create the async database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory, async_session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async_session_factory = _session_factory
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all tables (for development/testing only)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        if conn.dialect.name == "sqlite":
            await _ensure_sqlite_columns(conn, "documents", {
                "collection_path": "ALTER TABLE documents ADD COLUMN collection_path VARCHAR(800) NOT NULL DEFAULT ''",
            })
            await _ensure_sqlite_columns(conn, "retrieval_chunks", {
                "metadata_json": "ALTER TABLE retrieval_chunks ADD COLUMN metadata_json TEXT NULL",
            })
            await _ensure_sqlite_columns(conn, "answers", {
                "prompt_version": "ALTER TABLE answers ADD COLUMN prompt_version VARCHAR(50) NOT NULL DEFAULT 'v1'",
                "draft_text": "ALTER TABLE answers ADD COLUMN draft_text TEXT NOT NULL DEFAULT ''",
                "verification_issues_json": "ALTER TABLE answers ADD COLUMN verification_issues_json TEXT NOT NULL DEFAULT '[]'",
                "evidence_trace_json": "ALTER TABLE answers ADD COLUMN evidence_trace_json TEXT NOT NULL DEFAULT '{}'",
            })
            await _ensure_sqlite_columns(conn, "citations", {
                "bbox_json": "ALTER TABLE citations ADD COLUMN bbox_json TEXT NULL",
                "heading_path_json": "ALTER TABLE citations ADD COLUMN heading_path_json TEXT NOT NULL DEFAULT '[]'",
                "page_asset_path": "ALTER TABLE citations ADD COLUMN page_asset_path VARCHAR(1000) NULL",
            })
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_documents_collection_path ON documents (collection_path)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_documents_collection_checksum ON documents (collection_id, checksum)"
            )
        else:
            await conn.exec_driver_sql(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS collection_path VARCHAR(800) NOT NULL DEFAULT ''"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE retrieval_chunks ADD COLUMN IF NOT EXISTS metadata_json TEXT NULL"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE answers ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(50) NOT NULL DEFAULT 'v1'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE answers ADD COLUMN IF NOT EXISTS draft_text TEXT NOT NULL DEFAULT ''"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE answers ADD COLUMN IF NOT EXISTS verification_issues_json TEXT NOT NULL DEFAULT '[]'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE answers ADD COLUMN IF NOT EXISTS evidence_trace_json TEXT NOT NULL DEFAULT '{}'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE citations ADD COLUMN IF NOT EXISTS bbox_json TEXT NULL"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE citations ADD COLUMN IF NOT EXISTS heading_path_json TEXT NOT NULL DEFAULT '[]'"
            )
            await conn.exec_driver_sql(
                "ALTER TABLE citations ADD COLUMN IF NOT EXISTS page_asset_path VARCHAR(1000) NULL"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_documents_collection_path ON documents (collection_path)"
            )
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_documents_collection_checksum ON documents (collection_id, checksum)"
            )


async def _ensure_sqlite_columns(conn, table_name: str, column_sql: dict[str, str]) -> None:
    pragma_rows = await conn.exec_driver_sql(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in pragma_rows.fetchall()}
    for column_name, statement in column_sql.items():
        if column_name not in columns:
            await conn.exec_driver_sql(statement)


async def dispose_engine() -> None:
    """Dispose the engine (cleanup on shutdown)."""
    global _engine, _session_factory, async_session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        async_session_factory = None
