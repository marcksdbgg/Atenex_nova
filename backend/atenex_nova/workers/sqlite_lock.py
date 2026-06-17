"""SQLite worker lock helpers."""

from __future__ import annotations

import os
from pathlib import Path

from atenex_nova.shared.config.settings import STORAGE_ROOT, get_settings


def is_sqlite_backend() -> bool:
    return get_settings().database_url.startswith("sqlite")


def acquire_sqlite_worker_lock() -> int | None:
    """Acquire an exclusive worker lock when using SQLite. Returns fd or None."""
    if not is_sqlite_backend():
        return None

    lock_path = Path(STORAGE_ROOT) / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SystemExit(
            "SQLite backend detected and another worker lock already exists at "
            f"{lock_path}. Stop duplicate workers or use PostgreSQL for bulk ingestion."
        ) from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd
