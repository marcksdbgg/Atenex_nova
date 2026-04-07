"""Unit tests for ingestion source path resolution."""

from __future__ import annotations

from pathlib import Path

from atenex_nova.workers.jobs.ingestion_job import _resolve_document_source_path


def test_resolve_document_source_path_prefers_project_root(tmp_path: Path) -> None:
    source_path = Path("storage") / "uploads" / "collection" / "doc" / "file.txt"
    file_path = tmp_path / source_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello", encoding="utf-8")

    resolved = _resolve_document_source_path(str(source_path), project_root=tmp_path)

    assert resolved == file_path.resolve()


def test_resolve_document_source_path_falls_back_to_backend_storage(tmp_path: Path) -> None:
    source_path = Path("storage") / "uploads" / "collection" / "doc" / "legacy.txt"
    legacy_file = tmp_path / "backend" / source_path
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("legacy", encoding="utf-8")

    resolved = _resolve_document_source_path(str(source_path), project_root=tmp_path)

    assert resolved == legacy_file.resolve()


def test_resolve_document_source_path_returns_project_root_candidate_when_missing(tmp_path: Path) -> None:
    source_path = Path("storage") / "uploads" / "collection" / "doc" / "missing.txt"

    resolved = _resolve_document_source_path(str(source_path), project_root=tmp_path)

    assert resolved == (tmp_path / source_path).resolve()
