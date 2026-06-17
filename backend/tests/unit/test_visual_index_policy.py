"""Unit tests for visual indexing policy."""

from types import SimpleNamespace

from atenex_nova.application.policies.visual_index_policy import should_index_visual
from atenex_nova.shared.config.settings import Settings


def test_txt_plain_skipped_by_default() -> None:
    document = SimpleNamespace(mime_type="text/plain")
    settings = Settings()
    assert should_index_visual(document, settings) is False


def test_pdf_indexed_when_enabled() -> None:
    document = SimpleNamespace(mime_type="application/pdf")
    settings = Settings(visual_indexing_enabled=True)
    assert should_index_visual(document, settings) is True


def test_text_can_be_enabled_explicitly() -> None:
    document = SimpleNamespace(mime_type="text/plain")
    settings = Settings(visual_index_text_documents=True)
    assert should_index_visual(document, settings) is True
