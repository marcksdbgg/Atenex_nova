"""Focused tests for local corpus admission."""

from pathlib import Path

import pytest

from atenex_nova.application.policies.corpus_import_policy import CorpusImportPolicy


def test_policy_accepts_supported_content_and_reports_rejection_reason(tmp_path: Path) -> None:
    source_root = tmp_path / "corpus"
    source_root.mkdir()
    content_csv = source_root / "table.csv"
    content_csv.write_text("a,b", encoding="utf-8")
    unsupported = source_root / "payload.json"
    unsupported.write_text("{}", encoding="utf-8")
    oversized = source_root / "chapter.md"
    oversized.write_text("12345", encoding="utf-8")

    policy = CorpusImportPolicy(max_file_size_bytes=4)

    assert policy.evaluate_file(content_csv, source_root).accepted is True
    assert policy.evaluate_file(unsupported, source_root).report == "unsupported_extension: .json"
    assert policy.evaluate_file(oversized, source_root).report == (
        "file_too_large: 5 bytes exceeds limit of 4 bytes"
    )


def test_policy_rejects_excluded_path_and_symlink_outside_root(tmp_path: Path) -> None:
    source_root = tmp_path / "corpus"
    source_root.mkdir()
    metadata_directory = source_root / "_meta"
    metadata_directory.mkdir()
    metadata_file = metadata_directory / "video_index.csv"
    metadata_file.write_text("title,url", encoding="utf-8")

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("not in corpus", encoding="utf-8")
    external_link = source_root / "outside-link.txt"
    external_link.symlink_to(outside_file)

    policy = CorpusImportPolicy()

    assert policy.evaluate_directory(metadata_directory, source_root).report == (
        "excluded_directory: _meta"
    )
    assert policy.evaluate_file(metadata_file, source_root).report == "excluded_directory: _meta"
    external_decision = policy.evaluate_file(external_link, source_root)
    assert external_decision.accepted is False
    assert external_decision.reason_code == "symlink_outside_root"


def test_policy_does_not_follow_directory_symlinks_even_within_root(tmp_path: Path) -> None:
    source_root = tmp_path / "corpus"
    source_root.mkdir()
    target = source_root / "chapters"
    target.mkdir()
    directory_link = source_root / "chapter-link"
    directory_link.symlink_to(target, target_is_directory=True)

    decision = CorpusImportPolicy().evaluate_directory(directory_link, source_root)

    assert decision.report == "symlink_directory_not_followed: chapter-link"


def test_policy_normalizes_custom_extensions_and_validates_size_limit(tmp_path: Path) -> None:
    source_root = tmp_path / "corpus"
    source_root.mkdir()
    custom_document = source_root / "notes.foo"
    custom_document.write_text("custom", encoding="utf-8")

    policy = CorpusImportPolicy(max_file_size_bytes=10, allowed_extensions=frozenset({"FOO"}))

    assert policy.allowed_extensions == frozenset({".foo"})
    assert policy.evaluate_file(custom_document, source_root).accepted is True
    with pytest.raises(ValueError, match="max_file_size_bytes must be positive"):
        CorpusImportPolicy(max_file_size_bytes=0)
