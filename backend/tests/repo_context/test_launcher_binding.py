from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = BACKEND_ROOT / "scripts/serve_repo_context_mcp.sh"
INSTALL_ROOT = BACKEND_ROOT.parent


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/bash", os.fspath(LAUNCHER), *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _init_repository(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q", os.fspath(path)], check=True)
    (path / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", os.fspath(path), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            os.fspath(path),
            "-c",
            "user.name=Repo Context Test",
            "-c",
            "user.email=repo-context@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        check=True,
    )


class LauncherRepositoryBindingTests(unittest.TestCase):
    def _environment(self, root: Path) -> tuple[dict[str, str], Path]:
        log_path = root / "python-arguments.log"
        fake_python = root / "fake-python"
        fake_python.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" >> \"$ATENEX_FAKE_PYTHON_LOG\"\n"
        )
        fake_python.chmod(0o755)
        environment = os.environ.copy()
        environment.update(
            {
                "ATENEX_CONTEXT_INSTALL_ROOT": os.fspath(INSTALL_ROOT),
                "ATENEX_CONTEXT_PYTHON": os.fspath(fake_python),
                "ATENEX_CONTEXT_DATA_DIR": os.fspath(root / "sidecar"),
                "ATENEX_CONTEXT_SOURCE_ROOT": os.fspath(INSTALL_ROOT),
                "ATENEX_FAKE_PYTHON_LOG": os.fspath(log_path),
            }
        )
        return environment, log_path

    def test_relative_root_requires_expected_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            _init_repository(repository)
            environment, log_path = self._environment(root)

            result = _run(".", cwd=repository, env=environment)

            self.assertEqual(result.returncode, 2)
            self.assertIn("require an expected checkout root", result.stderr)
            self.assertFalse(log_path.exists())

    def test_relative_root_rejects_another_repository_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            another_repository = root / "another"
            _init_repository(repository)
            _init_repository(another_repository)
            environment, log_path = self._environment(root)

            result = _run(
                ".",
                os.fspath(another_repository),
                cwd=repository,
                env=environment,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("repository binding mismatch", result.stderr)
            self.assertFalse(log_path.exists())

    def test_linked_worktree_matches_its_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            worktree = root / "worktree"
            _init_repository(repository)
            subprocess.run(
                [
                    "git",
                    "-C",
                    os.fspath(repository),
                    "worktree",
                    "add",
                    "-q",
                    "-b",
                    "fixture-worktree",
                    os.fspath(worktree),
                ],
                check=True,
            )
            environment, log_path = self._environment(root)

            result = _run(
                ".",
                os.fspath(repository),
                cwd=worktree,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = log_path.read_text().splitlines()
            self.assertEqual(arguments.count("--repo"), 2)
            self.assertEqual(arguments.count(os.fspath(worktree)), 2)
            self.assertIn("index", arguments)
            self.assertIn("serve", arguments)


if __name__ == "__main__":
    unittest.main()
