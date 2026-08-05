"""Bootstrap migrations must also repair pre-existing development databases."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from atenex_nova.infrastructure.db import session as db_session


@pytest.mark.asyncio
async def test_bootstrap_adds_summary_provenance_to_existing_sqlite_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            """
            CREATE TABLE summary_nodes (
                id VARCHAR(36) PRIMARY KEY,
                scope_type VARCHAR(30) NOT NULL,
                scope_id VARCHAR(36) NOT NULL,
                text TEXT NOT NULL,
                embedding_ref VARCHAR(100) NULL
            )
            """
        )
        await connection.exec_driver_sql(
            "INSERT INTO summary_nodes (id, scope_type, scope_id, text) "
            "VALUES ('legacy', 'document', 'doc', 'legacy summary')"
        )

    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_session_factory", None)
    monkeypatch.setattr(db_session, "async_session_factory", None)

    await db_session.create_all_tables()
    await db_session.create_all_tables()

    async with engine.connect() as connection:
        columns = await connection.exec_driver_sql("PRAGMA table_info(summary_nodes)")
        names = {str(row[1]) for row in columns.fetchall()}
        assert "provenance_json" in names

        row = await connection.exec_driver_sql(
            "SELECT provenance_json FROM summary_nodes WHERE id = 'legacy'"
        )
        assert row.scalar_one() == "{}"

    await engine.dispose()
