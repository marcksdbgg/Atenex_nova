"""Policy: when to run visual page indexing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atenex_nova.domain.entities.document import Document
    from atenex_nova.shared.config.settings import Settings

_TEXT_ONLY_MIMES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "text/x-markdown",
        "application/json",
        "application/xml",
        "text/xml",
    }
)

_VISUAL_MIMES = frozenset({"application/pdf"})


def should_index_visual(document: Document, settings: Settings | Any) -> bool:
    """Return True when visual indexing should run for *document*."""
    if not getattr(settings, "visual_indexing_enabled", True):
        return False

    mime = (document.mime_type or "").lower().strip()
    if not mime:
        return False

    if mime in _TEXT_ONLY_MIMES or mime.startswith("text/"):
        return bool(getattr(settings, "visual_index_text_documents", False))

    return mime in _VISUAL_MIMES or mime.startswith("image/")
