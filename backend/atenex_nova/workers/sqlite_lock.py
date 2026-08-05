"""SQLite worker lock helpers."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import IO, Any

from atenex_nova.shared.config.settings import STORAGE_ROOT, get_settings


def is_sqlite_backend() -> bool:
    return get_settings().database_url.startswith("sqlite")


def _lock_handle(handle: IO[str]) -> None:
    if os.name == "nt":
        msvcrt: Any = import_module("msvcrt")

        handle.seek(0)
        if not handle.read(1):
            handle.write("0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError from exc
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: IO[str]) -> None:
    if os.name == "nt":
        msvcrt: Any = import_module("msvcrt")

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_sqlite_worker_lock() -> IO[str] | None:
    """Acquire a process-owned advisory lock when using SQLite.

    The lock file may persist after a crash; the kernel lock, not file existence,
    determines ownership, so an unclean shutdown cannot brick the next worker.
    """
    if not is_sqlite_backend():
        return None

    lock_path = Path(STORAGE_ROOT) / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        _lock_handle(handle)
    except BlockingIOError as exc:
        handle.close()
        raise SystemExit(
            "SQLite backend detected and another worker owns the lock at "
            f"{lock_path}. Stop duplicate workers or use PostgreSQL for bulk ingestion."
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def release_sqlite_worker_lock(handle: IO[str] | None) -> None:
    """Release a lock acquired by :func:`acquire_sqlite_worker_lock`."""
    if handle is None or handle.closed:
        return
    try:
        _unlock_handle(handle)
    finally:
        handle.close()
