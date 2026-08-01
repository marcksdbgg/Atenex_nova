"""Safe, Git-aware repository scanner for the deterministic context index."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from atenex_nova.repo_context.domain.models import (
    Diagnostic,
    FileRecord,
    RepositorySnapshot,
    ScanResult,
)
from atenex_nova.repo_context.domain.policies import (
    SECRET_NAMES,
    IndexPolicy,
    safe_relative_path,
)

_LANGUAGES = {
    ".css": "css",
    ".htm": "html",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsonc": "jsonc",
    ".jsx": "javascript",
    ".md": "markdown",
    ".mdx": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".pyi": "python",
    ".sh": "shell",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}
_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".db",
        ".dll",
        ".doc",
        ".docx",
        ".dylib",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lockb",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".sqlite",
        ".sqlite3",
        ".so",
        ".tar",
        ".tgz",
        ".ttf",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
_SECRET_SUFFIXES = frozenset({".jks", ".key", ".keystore", ".p12", ".pfx", ".pem"})
_SECRET_CONTENT_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
_GENERATED_NAMES = frozenset(
    {
        "test_out.json",
        "coverage.json",
        "lcov.info",
        "junit.xml",
    }
)


class SnapshotChangedError(RuntimeError):
    """Raised when a stable source snapshot cannot be captured."""


class GitRepositoryScanner:
    """Capture the current filesystem view of a repository without executing it."""

    def __init__(
        self,
        root: Path,
        *,
        policy: IndexPolicy | None = None,
        timeout: float = 10.0,
        max_capture_attempts: int = 3,
        schema_version: int = 1,
        parser_version: str = "repo-context-v1.0.0",
    ) -> None:
        canonical = root.expanduser().resolve()
        if not canonical.is_dir():
            raise ValueError(f"repository root is not a directory: {root}")
        self._root = canonical
        self._policy = policy or IndexPolicy()
        self._timeout = timeout
        self._max_capture_attempts = max(1, max_capture_attempts)
        self._schema_version = schema_version
        self._parser_version = parser_version

    @property
    def root(self) -> Path:
        return self._root

    def scan(self) -> ScanResult:
        last_error: Exception | None = None
        for _attempt in range(self._max_capture_attempts):
            try:
                return self._capture_once()
            except SnapshotChangedError as exc:
                last_error = exc
        raise SnapshotChangedError(
            "snapshot_changed_during_capture: repository did not stabilize "
            f"after {self._max_capture_attempts} attempts"
        ) from last_error

    def _capture_once(self) -> ScanResult:
        is_git = self._is_git_worktree()
        inventory_before = self._git_inventory() if is_git else self._filesystem_inventory()
        statuses, dirty = self._git_statuses() if is_git else ({}, False)
        tracked = self._git_tracked() if is_git else set()

        files: list[FileRecord] = []
        diagnostics: list[Diagnostic] = []
        skipped: Counter[str] = Counter()
        for seen, relative in enumerate(inventory_before, start=1):
            if seen > self._policy.max_files:
                raise RuntimeError(
                    f"repository exceeds max_files={self._policy.max_files}"
                )
            record, diagnostic = self._read_candidate(
                relative,
                statuses=statuses,
                tracked=tracked,
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)
                skipped[diagnostic.code] += 1
            if record is not None:
                files.append(record)

        inventory_after = self._git_inventory() if is_git else self._filesystem_inventory()
        if inventory_after != inventory_before:
            raise SnapshotChangedError("repository inventory changed during capture")
        self._revalidate_files(files)

        files.sort(key=lambda item: item.path)
        content_fingerprint = _fingerprint_files(files, include_status=False)
        head = self._git_text("rev-parse", "--verify", "HEAD") if is_git else None
        branch = (
            self._git_text("symbolic-ref", "--quiet", "--short", "HEAD")
            if is_git
            else None
        )
        worktree_hasher = hashlib.sha256()
        worktree_hasher.update((head or "").encode())
        worktree_hasher.update(b"\0")
        worktree_hasher.update(_fingerprint_files(files, include_status=True).encode())
        snapshot = RepositorySnapshot(
            repository_id=hashlib.sha256(os.fsencode(str(self._root))).hexdigest(),
            root=str(self._root),
            head=head,
            branch=branch,
            dirty=dirty,
            worktree_fingerprint=worktree_hasher.hexdigest(),
            content_fingerprint=content_fingerprint,
            schema_version=self._schema_version,
            parser_version=self._parser_version,
            created_at=datetime.now(UTC).isoformat(),
        )
        return ScanResult(
            snapshot=snapshot,
            files=tuple(files),
            diagnostics=tuple(diagnostics),
            skipped=dict(sorted(skipped.items())),
        )

    def _read_candidate(
        self,
        relative: str,
        *,
        statuses: dict[str, str],
        tracked: set[str],
    ) -> tuple[FileRecord | None, Diagnostic | None]:
        try:
            safe = safe_relative_path(relative)
        except ValueError:
            return None, _diagnostic("excluded_path_escape", relative)
        if any("\ud800" <= char <= "\udfff" for char in safe):
            return None, _diagnostic("excluded_path_encoding", safe)

        parts = Path(safe).parts
        if any(part in self._policy.excluded_parts for part in parts):
            return None, _diagnostic("excluded_path", safe)
        source_path = self._root.joinpath(*parts)

        try:
            stat_before = source_path.lstat()
        except FileNotFoundError:
            # A deleted tracked file belongs to Git's inventory but not to the snapshot.
            return None, None

        if source_path.is_symlink():
            try:
                source_path.resolve(strict=True).relative_to(self._root)
            except (FileNotFoundError, ValueError):
                return None, _diagnostic("excluded_symlink_escape", safe)
            return None, _diagnostic("excluded_symlink", safe)
        if not source_path.is_file():
            return None, _diagnostic("excluded_non_file", safe)
        if _is_secret_name(source_path.name):
            return None, _diagnostic("excluded_secret", safe)
        if source_path.name.lower() in _GENERATED_NAMES:
            return None, _diagnostic("excluded_generated", safe)
        if source_path.suffix.lower() in _BINARY_SUFFIXES:
            return None, _diagnostic("excluded_binary", safe)
        if stat_before.st_size > self._policy.max_file_bytes:
            return None, _diagnostic("excluded_large_file", safe)

        try:
            content = source_path.read_bytes()
            stat_after = source_path.stat()
        except OSError:
            return None, _diagnostic("unreadable_file", safe)
        identity_before = (
            stat_before.st_dev,
            stat_before.st_ino,
            stat_before.st_size,
            stat_before.st_mtime_ns,
        )
        identity_after = (
            stat_after.st_dev,
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
        )
        if identity_before != identity_after or len(content) != stat_after.st_size:
            raise SnapshotChangedError(f"{safe} changed while being read")
        if _looks_binary(content):
            return None, _diagnostic("excluded_binary", safe)
        if _contains_secret(content):
            return None, _diagnostic("excluded_secret", safe)

        text = _decode_text(content)
        digest = hashlib.sha256(content).hexdigest()
        if safe in statuses:
            git_status = statuses[safe]
        elif safe in tracked:
            git_status = "tracked"
        else:
            git_status = "untracked" if tracked else "filesystem"
        return (
            FileRecord(
                path=safe,
                language=_language_for(source_path),
                content_hash=digest,
                size=len(content),
                git_status=git_status,
                text=text,
                line_count=_line_count(text),
            ),
            None,
        )

    def _revalidate_files(self, files: list[FileRecord]) -> None:
        """Ensure no eligible file changed after its individual read completed."""
        for file in files:
            source_path = self._root.joinpath(*Path(file.path).parts)
            try:
                if source_path.is_symlink():
                    raise SnapshotChangedError(
                        f"{file.path} became a symlink during capture"
                    )
                content = source_path.read_bytes()
            except OSError as exc:
                raise SnapshotChangedError(
                    f"{file.path} changed after capture"
                ) from exc
            if (
                len(content) != file.size
                or hashlib.sha256(content).hexdigest() != file.content_hash
            ):
                raise SnapshotChangedError(f"{file.path} changed after capture")

    def _is_git_worktree(self) -> bool:
        result = self._run_git("rev-parse", "--is-inside-work-tree")
        return result.returncode == 0 and result.stdout.strip() == b"true"

    def _git_inventory(self) -> tuple[str, ...]:
        result = self._run_git(
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            check=True,
        )
        return tuple(sorted(_decode_paths(result.stdout)))

    def _git_tracked(self) -> set[str]:
        result = self._run_git("ls-files", "--cached", "-z", check=True)
        return set(_decode_paths(result.stdout))

    def _git_statuses(self) -> tuple[dict[str, str], bool]:
        result = self._run_git(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
            check=True,
        )
        records = result.stdout.split(b"\0")
        statuses: dict[str, str] = {}
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            decoded = record.decode("utf-8", errors="surrogateescape")
            if len(decoded) < 4:
                continue
            status = decoded[:2]
            path = decoded[3:]
            if "R" in status or "C" in status:
                # In porcelain -z, the following field is the original path.
                index += 1
            try:
                statuses[safe_relative_path(path)] = status
            except ValueError:
                continue
        return statuses, bool(result.stdout)

    def _filesystem_inventory(self) -> tuple[str, ...]:
        results: list[str] = []
        for directory, child_dirs, filenames in os.walk(
            self._root, topdown=True, followlinks=False
        ):
            current = Path(directory)
            child_dirs[:] = sorted(
                name
                for name in child_dirs
                if name not in self._policy.excluded_parts
                and not (current / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = current / filename
                try:
                    relative = path.relative_to(self._root).as_posix()
                    results.append(safe_relative_path(relative))
                except ValueError:
                    continue
                if len(results) > self._policy.max_files:
                    raise RuntimeError(
                        f"repository exceeds max_files={self._policy.max_files}"
                    )
        return tuple(sorted(results))

    def _git_text(self, *args: str) -> str | None:
        result = self._run_git(*args)
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", errors="replace").strip()
        return value or None

    def _run_git(
        self, *args: str, check: bool = False
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._root,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            if check:
                raise RuntimeError("Git is unavailable or timed out") from None
            return subprocess.CompletedProcess(["git", *args], 127, b"", b"")
        if check and result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Git command failed: {message or result.returncode}")
        return result


GitScanner = GitRepositoryScanner


def _decode_paths(payload: bytes) -> list[str]:
    paths: list[str] = []
    for raw in payload.split(b"\0"):
        if not raw:
            continue
        paths.append(raw.decode("utf-8", errors="surrogateescape"))
    return paths


def _fingerprint_files(
    files: list[FileRecord], *, include_status: bool
) -> str:
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.content_hash.encode())
        if include_status:
            digest.update(b"\0")
            digest.update(file.git_status.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _diagnostic(code: str, path: str) -> Diagnostic:
    severity: Literal["info", "warning", "error"] = (
        "warning"
        if code
        in {
            "excluded_path_escape",
            "excluded_path_encoding",
            "excluded_symlink_escape",
            "excluded_secret",
            "unreadable_file",
        }
        else "info"
    )
    return Diagnostic(
        code=code,
        message=code.replace("_", " "),
        path=path,
        severity=severity,
    )


def _is_secret_name(name: str) -> bool:
    lower = name.lower()
    return (
        lower in SECRET_NAMES
        or lower == ".env"
        or lower.startswith(".env.")
        or Path(lower).suffix in _SECRET_SUFFIXES
        or lower in {"credentials", "secrets"}
    )


def _contains_secret(content: bytes) -> bool:
    sample = content[:256_000]
    return any(pattern.search(sample) is not None for pattern in _SECRET_CONTENT_PATTERNS)


def _looks_binary(content: bytes) -> bool:
    if not content:
        return False
    sample = content[:8192]
    # A small number of literal NUL characters can legally occur inside source
    # string literals. Dense NULs remain a strong binary/UTF-16 signal.
    if sample.count(b"\0") / len(sample) > 0.01:
        return True
    control = sum(byte < 32 and byte not in b"\t\n\r\f\b" for byte in sample)
    return control / len(sample) > 0.15


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _language_for(path: Path) -> str:
    if path.name in {"Dockerfile", "Containerfile"}:
        return "dockerfile"
    if path.name.lower() in {
        "cargo.lock",
        "composer.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }:
        return "lockfile"
    return _LANGUAGES.get(path.suffix.lower(), "text")


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)
