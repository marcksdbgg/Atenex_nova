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
        if _lock_owner_is_alive(lock_path):
            raise SystemExit(
                "SQLite backend detected and another worker lock already exists at "
                f"{lock_path}. Stop duplicate workers or use PostgreSQL for bulk ingestion."
            ) from exc
        lock_path.unlink(missing_ok=True)
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as retry_exc:
            raise SystemExit(
                "SQLite worker lock was reacquired by another process at "
                f"{lock_path}. Stop duplicate workers or use PostgreSQL for bulk ingestion."
            ) from retry_exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def release_sqlite_worker_lock(fd: int | None) -> None:
    """Release a lock owned by this process without deleting another worker's lock."""
    if fd is None:
        return
    lock_path = Path(STORAGE_ROOT) / "worker.lock"
    try:
        os.close(fd)
    finally:
        try:
            owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        if owner_pid == os.getpid():
            lock_path.unlink(missing_ok=True)


def _lock_owner_is_alive(lock_path: Path) -> bool:
    try:
        owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(owner_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
