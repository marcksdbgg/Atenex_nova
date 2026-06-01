"""Visual retrieval adapter with Qdrant and local fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import StrictModeViolationError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VisualPage:
    id: str
    collection_id: str
    document_id: str
    page_number: int
    title: str
    text: str
    is_complex: bool = False
    image_path: str | None = None
    metadata: dict[str, Any] | None = None


class ColPaliAdapter:
    """Visual retriever for page-level evidence."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        settings = get_settings()
        qdrant_endpoint = urlparse(settings.qdrant_url)
        qdrant_host = qdrant_endpoint.hostname or "localhost"
        qdrant_port = qdrant_endpoint.port or 6333

        self._strict_visual = settings.visual_required
        self._storage_dir = storage_dir or settings.visual_pages_path
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._embedder = EmbeddingGemmaAdapter(
            dim=settings.embedding_dimensions,
            required=settings.embeddings_required,
        )
        self._qdrant = QdrantAdapter(
            host=qdrant_host,
            port=qdrant_port,
            required=(settings.qdrant_required or self._strict_visual),
        )
        logger.info("VisualPageRetriever initialized")

    async def upsert_pages(self, collection_id: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = [self._normalize_page(collection_id, page) for page in pages]
        if not records:
            return []

        await self._persist_local(collection_id, records)
        vectors = await self._embedder.embed([record.text for record in records])
        await self._qdrant.init_collection("pages_visual", self._embedder.embedding_dim)
        await self._qdrant.upsert(
            "pages_visual",
            [
                QdrantDocument(
                    id=record.id,
                    vector=vector,
                    payload={
                        **asdict(record),
                        "collection_id": collection_id,
                        "retrieval_backend": "page_text_embedding",
                    },
                )
                for record, vector in zip(records, vectors, strict=False)
            ],
        )
        return [asdict(record) for record in records]

    async def search(self, collection_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        query_vector = (await self._embedder.embed([query]))[0]
        qdrant_hits = await self._qdrant.search(
            "pages_visual",
            query_vector,
            limit=limit,
            filter_dict={"collection_id": collection_id},
        )
        if qdrant_hits:
            return [self._from_payload(hit) for hit in qdrant_hits[:limit]]

        if self._strict_visual:
            return []

        local_records = await self._load_local(collection_id)
        if not local_records:
            return []

        texts = [str(record.get("text") or "") for record in local_records]
        sparse_scores = BM25SparseEncoder().score(query, texts)
        query_tokens = set(query.lower().split())
        ranked: list[dict[str, Any]] = []
        for index, record in enumerate(local_records):
            record_text = str(record.get("text") or "")
            vector = (await self._embedder.embed([record_text]))[0]
            dense_score = self._cosine(query_vector, vector)
            lexical_score = sparse_scores[index] if index < len(sparse_scores) else 0.0
            bonus = 0.1 if query_tokens.intersection(set(record_text.lower().split())) else 0.0
            ranked.append({**record, "score": round((dense_score * 0.65) + (lexical_score * 0.35) + bonus, 4)})

        ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return ranked[:limit]

    def _normalize_page(self, collection_id: str, page: dict[str, Any]) -> VisualPage:
        page_number = int(page.get("page_number") or 1)
        source_page_id = str(page.get("id") or f"{page.get('document_id', 'doc')}:{page_number}")
        page_id = str(page.get("id") or new_id())
        text = str(page.get("text") or page.get("content") or "").strip()
        if self._strict_visual and not text:
            raise StrictModeViolationError(
                "visual strict mode requires OCR/text extraction for page-level evidence",
                code="OCR_ENGINE_UNAVAILABLE",
            )
        document_id = str(page.get("document_id") or "")
        source_path = str(page.get("source_path") or "")
        image_path = self._render_page_image(
            source_path=source_path,
            document_id=document_id,
            page_number=page_number,
        )
        metadata = {
            **cast(dict[str, Any], page.get("metadata") or {}),
            "source_page_id": source_page_id,
            "retrieval_backend": "page_text_embedding",
            "visual_asset_status": "rendered" if image_path else "unavailable",
        }
        return VisualPage(
            id=page_id,
            collection_id=collection_id,
            document_id=document_id,
            page_number=page_number,
            title=str(page.get("title") or "Visual page"),
            text=text or str(page.get("title") or "Visual page"),
            is_complex=bool(page.get("is_complex", False)),
            image_path=str(image_path) if image_path else None,
            metadata=metadata,
        )

    def _render_page_image(self, source_path: str, document_id: str, page_number: int) -> Path | None:
        if not source_path:
            if self._strict_visual:
                raise StrictModeViolationError(
                    "visual strict mode requires a source path to render page assets",
                    code="VISUAL_ASSET_UNAVAILABLE",
                )
            return None

        source = Path(source_path).expanduser()
        if not source.exists():
            if self._strict_visual:
                raise StrictModeViolationError(
                    f"visual strict mode could not find source file: {source}",
                    code="VISUAL_ASSET_UNAVAILABLE",
                )
            return None

        page_dir = self._storage_dir / document_id
        page_dir.mkdir(parents=True, exist_ok=True)
        image_path = page_dir / f"page-{page_number}.png"
        if image_path.exists():
            return image_path

        try:
            if source.suffix.lower() == ".pdf":
                import pypdfium2 as pdfium  # type: ignore[import-untyped]

                pdf = pdfium.PdfDocument(str(source))
                index = max(page_number - 1, 0)
                if index >= len(pdf):
                    raise IndexError(f"PDF page {page_number} out of range")
                page = pdf[index]
                bitmap = page.render(scale=2.0)
                pil_image = bitmap.to_pil()
                pil_image.save(image_path)
                return image_path

            from PIL import Image

            with Image.open(source) as image:
                image.convert("RGB").save(image_path)
            return image_path
        except Exception as exc:
            if self._strict_visual:
                raise StrictModeViolationError(
                    f"visual strict mode could not render a real page asset: {exc}",
                    code="VISUAL_ASSET_UNAVAILABLE",
                ) from exc
            logger.warning("Real page render unavailable for %s page %s: %s", source, page_number, exc)
            return None

    async def _persist_local(self, collection_id: str, records: list[VisualPage]) -> None:
        path = self._storage_dir / f"{collection_id}.json"
        current = await self._load_local(collection_id)
        merged = [record for record in current if record.get("id") not in {item.id for item in records}]
        merged.extend(asdict(record) for record in records)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _load_local(self, collection_id: str) -> list[dict[str, Any]]:
        path = self._storage_dir / f"{collection_id}.json"
        if not path.exists():
            return []
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                return [item for item in loaded if isinstance(item, dict)]
            return []
        except Exception:
            return []

    @staticmethod
    def _from_payload(hit: dict[str, Any]) -> dict[str, Any]:
        payload = hit.get("payload") or hit
        payload = dict(cast(dict[str, Any], payload))
        payload["score"] = float(hit.get("score") or payload.get("score") or 0.0)
        return payload

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        limit = min(len(left), len(right))
        numerator = sum(left[i] * right[i] for i in range(limit))
        left_norm = sum(value * value for value in left[:limit]) ** 0.5
        right_norm = sum(value * value for value in right[:limit]) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return float(numerator / (left_norm * right_norm))
