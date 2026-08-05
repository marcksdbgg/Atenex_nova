"""Tests for the single-worker SQLite process lock."""

from __future__ import annotations

import os

import pytest

from atenex_nova.workers import sqlite_lock


def test_stale_worker_lock_is_recovered(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_lock, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(sqlite_lock, "is_sqlite_backend", lambda: True)
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text("999999999", encoding="utf-8")

    fd = sqlite_lock.acquire_sqlite_worker_lock()

    assert fd is not None
    assert lock_path.read_text(encoding="utf-8") == str(os.getpid())
    sqlite_lock.release_sqlite_worker_lock(fd)
    assert not lock_path.exists()


def test_live_worker_lock_is_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_lock, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(sqlite_lock, "is_sqlite_backend", lambda: True)
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")

    with pytest.raises(SystemExit, match="another worker lock"):
        sqlite_lock.acquire_sqlite_worker_lock()
