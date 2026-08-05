"""Filesystem boundary checks for generated visual cleanup."""

from pathlib import Path

import pytest

from atenex_nova.workers.jobs.ingestion_job import (
    _remove_visual_asset_dir,
    _visual_cache_path,
)


def test_visual_cleanup_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collection_id"):
        _visual_cache_path(tmp_path, "../outside")
    with pytest.raises(ValueError, match="document_id"):
        _remove_visual_asset_dir(tmp_path, "../outside")


def test_visual_cleanup_never_follows_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    link = tmp_path / "doc-link"
    link.symlink_to(outside, target_is_directory=True)

    _remove_visual_asset_dir(tmp_path, "doc-link")

    assert link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep"
