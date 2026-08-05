"""Public evidence payloads stay bounded."""

from atenex_nova.presentation.api.dto.schemas import compact_evidence_metadata


def test_compact_evidence_metadata_removes_full_source_text() -> None:
    metadata = {
        "source_text": "transcripción " * 10_000,
        "heading_path": ["Capítulo", "Sección"],
        "retrieval_stage": "dense_qdrant",
    }

    compact = compact_evidence_metadata(metadata)

    assert "source_text" not in compact
    assert compact["source_text_chars"] == len(metadata["source_text"])
    assert compact["heading_path"] == ["Capítulo", "Sección"]
