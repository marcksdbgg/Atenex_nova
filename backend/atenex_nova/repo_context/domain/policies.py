"""Security and output policies shared by adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEFAULT_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".atenex",
        ".venv",
        ".venv312",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        ".next",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "storage",
        "qdrant_data",
        "qdrant_storage",
        "__pycache__",
    }
)

SECRET_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "secrets.json",
    }
)


@dataclass(frozen=True, slots=True)
class IndexPolicy:
    max_file_bytes: int = 2_000_000
    max_files: int = 100_000
    max_chunk_lines: int = 80
    max_chunk_chars: int = 12_000
    excluded_parts: frozenset[str] = DEFAULT_EXCLUDED_PARTS


def safe_relative_path(value: str) -> str:
    raw = value.replace("\\", "/")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError(f"unsafe repository-relative path: {value!r}")
    normalized = raw
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe repository-relative path: {value!r}")
    return path.as_posix()


def resolve_inside(root: Path, relative: str) -> Path:
    safe = safe_relative_path(relative)
    candidate = (root / safe).resolve()
    canonical_root = root.resolve()
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {relative!r}") from exc
    return candidate
