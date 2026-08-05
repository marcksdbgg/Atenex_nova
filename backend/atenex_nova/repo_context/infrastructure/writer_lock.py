"""Process-owned single-writer lock for repository index publication."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path


@contextmanager
def repository_writer_lock(data_dir: Path) -> Iterator[None]:
    """Serialize lexical and semantic generation writes for one sidecar.

    The lock file may survive a crash, but ownership belongs to the live file
    descriptor in the kernel. A later process can therefore recover without
    deleting any state or guessing whether a recorded PID is stale.
    """

    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        os.chmod(data_dir, 0o700)
    lock_path = data_dir / "writer.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"pid={os.getpid()}\n")
            lock_file.flush()
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        raise
