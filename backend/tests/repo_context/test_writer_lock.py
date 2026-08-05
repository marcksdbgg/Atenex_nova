from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from atenex_nova.repo_context.infrastructure.writer_lock import (
    repository_writer_lock,
)


class RepositoryWriterLockTests(unittest.TestCase):
    def test_serializes_concurrent_writers_for_one_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "context"
            state_lock = threading.Lock()
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()
            active_writers = 0
            maximum_active_writers = 0

            def worker(*, first: bool) -> None:
                nonlocal active_writers, maximum_active_writers
                with repository_writer_lock(data_dir):
                    with state_lock:
                        active_writers += 1
                        maximum_active_writers = max(
                            maximum_active_writers, active_writers
                        )
                    if first:
                        first_entered.set()
                        self.assertTrue(release_first.wait(timeout=2))
                    else:
                        second_entered.set()
                    with state_lock:
                        active_writers -= 1

            first = threading.Thread(target=worker, kwargs={"first": True})
            second = threading.Thread(target=worker, kwargs={"first": False})
            first.start()
            self.assertTrue(first_entered.wait(timeout=2))
            second.start()
            time.sleep(0.05)
            self.assertFalse(second_entered.is_set())
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertTrue(second_entered.is_set())
            self.assertEqual(maximum_active_writers, 1)
            self.assertTrue((data_dir / "writer.lock").is_file())
