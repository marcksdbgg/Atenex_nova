"""Tests for the single-worker SQLite process lock."""

from pathlib import Path

import pytest

from atenex_nova.workers import sqlite_lock


def test_persistent_lock_file_does_not_block_a_new_worker_after_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_lock, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(sqlite_lock, "is_sqlite_backend", lambda: True)

    first = sqlite_lock.acquire_sqlite_worker_lock()
    assert first is not None
    lock_path = tmp_path / "worker.lock"
    assert lock_path.read_text(encoding="utf-8").strip()

    with pytest.raises(SystemExit, match="another worker owns the lock"):
        sqlite_lock.acquire_sqlite_worker_lock()

    sqlite_lock.release_sqlite_worker_lock(first)
    second = sqlite_lock.acquire_sqlite_worker_lock()
    assert second is not None
    sqlite_lock.release_sqlite_worker_lock(second)


def test_non_sqlite_backend_needs_no_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_lock, "is_sqlite_backend", lambda: False)

    assert sqlite_lock.acquire_sqlite_worker_lock() is None
    sqlite_lock.release_sqlite_worker_lock(None)
