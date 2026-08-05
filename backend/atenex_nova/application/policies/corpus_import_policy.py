"""Deterministic admission policy for local documentary corpora."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024

SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".csv",
        ".docx",
        ".htm",
        ".html",
        ".markdown",
        ".md",
        ".pdf",
        ".pptx",
        ".rst",
        ".text",
        ".txt",
        ".xlsx",
    }
)

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".atenex",
        ".cache",
        ".git",
        ".hg",
        ".meta",
        ".metadata",
        ".next",
        ".nox",
        ".nuxt",
        ".qdrant",
        ".repo-context",
        ".repo_context",
        ".sidecars",
        ".svn",
        ".svelte-kit",
        ".tox",
        ".venv",
        "__pycache__",
        "_exports",
        "_manifests",
        "_meta",
        "_metadata",
        "build",
        "coverage",
        "dist",
        "env",
        "exports",
        "htmlcov",
        "manifests",
        "metadata",
        "node_modules",
        "out",
        "qdrant_storage",
        "sidecars",
        "site-packages",
        "target",
        "vendor",
        "venv",
    }
)

EXCLUDED_ADMINISTRATIVE_FILE_NAMES = frozenset(
    {
        ".ds_store",
        "manifest.csv",
        "manifest.json",
        "metadata.csv",
        "metadata.json",
        "thumbs.db",
        "video_index.csv",
    }
)

EXCLUDED_ARCHIVE_EXTENSIONS = frozenset(
    {
        ".7z",
        ".bz2",
        ".gz",
        ".rar",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    }
)

EXCLUDED_SIDECAR_EXTENSIONS = frozenset(
    {
        ".db",
        ".idx",
        ".index",
        ".lock",
        ".log",
        ".shm",
        ".sqlite",
        ".sqlite3",
        ".tvim",
        ".wal",
    }
)


@dataclass(frozen=True, slots=True)
class CorpusImportDecision:
    """Admission result suitable for persistence in an import-session item."""

    accepted: bool
    reason_code: str | None = None
    detail: str = ""

    @classmethod
    def accept(cls) -> CorpusImportDecision:
        return cls(accepted=True)

    @classmethod
    def skip(cls, reason_code: str, detail: str = "") -> CorpusImportDecision:
        return cls(accepted=False, reason_code=reason_code, detail=detail)

    @property
    def report(self) -> str | None:
        if self.accepted or self.reason_code is None:
            return None
        if self.detail:
            return f"{self.reason_code}: {self.detail}"
        return self.reason_code


@dataclass(frozen=True, slots=True)
class CorpusImportPolicy:
    """Classify local paths before hashing, registration, or parsing.

    ``max_file_size_bytes`` and the allow/exclusion sets are constructor inputs so
    deployments and tests can tighten the boundary without changing the service.
    """

    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    allowed_extensions: frozenset[str] = field(
        default_factory=lambda: SUPPORTED_DOCUMENT_EXTENSIONS
    )
    excluded_directory_names: frozenset[str] = field(
        default_factory=lambda: EXCLUDED_DIRECTORY_NAMES
    )
    excluded_file_names: frozenset[str] = field(
        default_factory=lambda: EXCLUDED_ADMINISTRATIVE_FILE_NAMES
    )

    def __post_init__(self) -> None:
        if self.max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes must be positive")

        normalized_extensions = frozenset(
            self._normalize_extension(item) for item in self.allowed_extensions
        )
        normalized_directories = frozenset(
            item.casefold() for item in self.excluded_directory_names
        )
        normalized_files = frozenset(item.casefold() for item in self.excluded_file_names)
        object.__setattr__(self, "allowed_extensions", normalized_extensions)
        object.__setattr__(self, "excluded_directory_names", normalized_directories)
        object.__setattr__(self, "excluded_file_names", normalized_files)

    def evaluate_directory(self, path: Path, source_root: Path) -> CorpusImportDecision:
        """Decide whether a directory may be traversed.

        Directory symlinks are never traversed. This avoids cycles and guarantees
        that a link cannot expand discovery beyond the selected corpus root.
        """

        relative_path = self._lexical_relative_path(path, source_root)
        if relative_path is None:
            return CorpusImportDecision.skip("outside_source_root", path.as_posix())

        if path.is_symlink():
            target, error = self._resolve_target(path)
            if target is None:
                return CorpusImportDecision.skip("broken_symlink", error)
            if not target.is_relative_to(source_root):
                return CorpusImportDecision.skip(
                    "symlink_outside_root",
                    f"{relative_path.as_posix()} -> {target.as_posix()}",
                )
            return CorpusImportDecision.skip(
                "symlink_directory_not_followed",
                relative_path.as_posix(),
            )

        excluded_part = self._first_excluded_directory(relative_path)
        if excluded_part is not None:
            return CorpusImportDecision.skip("excluded_directory", excluded_part)
        return CorpusImportDecision.accept()

    def evaluate_file(self, path: Path, source_root: Path) -> CorpusImportDecision:
        """Decide whether a file is supported, safe, and within the size limit."""

        relative_path = self._lexical_relative_path(path, source_root)
        if relative_path is None:
            return CorpusImportDecision.skip("outside_source_root", path.as_posix())

        excluded_part = self._first_excluded_directory(relative_path.parent)
        if excluded_part is not None:
            return CorpusImportDecision.skip("excluded_directory", excluded_part)

        target, error = self._resolve_target(path)
        if target is None:
            reason = "broken_symlink" if path.is_symlink() else "unreadable_file"
            return CorpusImportDecision.skip(reason, error)
        if not target.is_relative_to(source_root):
            reason = "symlink_outside_root" if path.is_symlink() else "outside_source_root"
            return CorpusImportDecision.skip(
                reason,
                f"{relative_path.as_posix()} -> {target.as_posix()}",
            )
        if not target.is_file():
            return CorpusImportDecision.skip("not_regular_file", relative_path.as_posix())

        target_relative_path = target.relative_to(source_root)
        excluded_target_part = self._first_excluded_directory(target_relative_path.parent)
        if excluded_target_part is not None:
            return CorpusImportDecision.skip("excluded_directory", excluded_target_part)

        normalized_name = path.name.casefold()
        extension = path.suffix.casefold()
        if normalized_name in self.excluded_file_names:
            return CorpusImportDecision.skip("excluded_administrative_file", path.name)
        if normalized_name.startswith(("~$", ".~lock.")):
            return CorpusImportDecision.skip("excluded_sidecar_file", path.name)
        if extension in EXCLUDED_ARCHIVE_EXTENSIONS:
            return CorpusImportDecision.skip("excluded_archive", extension)
        if extension in EXCLUDED_SIDECAR_EXTENSIONS:
            return CorpusImportDecision.skip("excluded_sidecar_file", extension)
        if extension not in self.allowed_extensions:
            return CorpusImportDecision.skip("unsupported_extension", extension or "<none>")

        try:
            size = target.stat().st_size
        except OSError as exc:
            return CorpusImportDecision.skip("unreadable_file", str(exc))
        if size > self.max_file_size_bytes:
            return CorpusImportDecision.skip(
                "file_too_large",
                f"{size} bytes exceeds limit of {self.max_file_size_bytes} bytes",
            )
        return CorpusImportDecision.accept()

    def unreadable_directory(self, path: Path, error: OSError) -> CorpusImportDecision:
        return CorpusImportDecision.skip(
            "unreadable_directory",
            f"{path.as_posix()}: {error}",
        )

    def _first_excluded_directory(self, relative_path: Path) -> str | None:
        for part in relative_path.parts:
            if part.casefold() in self.excluded_directory_names:
                return part
        return None

    @staticmethod
    def _lexical_relative_path(path: Path, source_root: Path) -> Path | None:
        try:
            return path.absolute().relative_to(source_root)
        except ValueError:
            return None

    @staticmethod
    def _resolve_target(path: Path) -> tuple[Path | None, str]:
        try:
            return path.resolve(strict=True), ""
        except (OSError, RuntimeError) as exc:
            return None, str(exc)

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        normalized = extension.strip().casefold()
        if not normalized:
            raise ValueError("allowed_extensions cannot contain an empty extension")
        return normalized if normalized.startswith(".") else f".{normalized}"
