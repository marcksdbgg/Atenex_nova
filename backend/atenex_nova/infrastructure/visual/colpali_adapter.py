"""Visual retrieval adapter with Qdrant and local fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from textwrap import wrap

from atenex_nova.infrastructure.embeddings.bm25_encoder import BM25SparseEncoder
from atenex_nova.infrastructure.embeddings.embedding_adapter import EmbeddingGemmaAdapter
from atenex_nova.infrastructure.qdrant.qdrant_adapter import QdrantAdapter, QdrantDocument
from atenex_nova.shared.config.settings import get_settings

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
    metadata: dict | None = None


class ColPaliAdapter:
    """Visual retriever for page-level evidence."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or get_settings().visual_pages_path
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._embedder = EmbeddingGemmaAdapter(dim=384)
        self._qdrant = QdrantAdapter(host="localhost", port=6333)
        logger.info("ColPaliAdapter initialized")

    async def upsert_pages(self, collection_id: str, pages: list[dict]) -> list[dict]:
        records = [self._normalize_page(collection_id, page) for page in pages]
        if not records:
            return []

        await self._persist_local(collection_id, records)
        vectors = await self._embedder.embed([record.text for record in records])
        await self._qdrant.init_collection("pages_visual", 384)
        await self._qdrant.upsert(
            "pages_visual",
            [
                QdrantDocument(
                    id=record.id,
                    vector=vector,
                    payload={
                        **asdict(record),
                        "collection_id": collection_id,
                    },
                )
                for record, vector in zip(records, vectors, strict=False)
            ],
        )
        return [asdict(record) for record in records]

    async def search(self, collection_id: str, query: str, limit: int = 5) -> list[dict]:
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

        local_records = await self._load_local(collection_id)
        if not local_records:
            return []

        texts = [record["text"] for record in local_records]
        sparse_scores = BM25SparseEncoder().score(query, texts)
        query_tokens = set(query.lower().split())
        ranked: list[dict] = []
        for index, record in enumerate(local_records):
            vector = (await self._embedder.embed([record["text"]]))[0]
            dense_score = self._cosine(query_vector, vector)
            lexical_score = sparse_scores[index] if index < len(sparse_scores) else 0.0
            bonus = 0.1 if query_tokens.intersection(set(record["text"].lower().split())) else 0.0
            ranked.append({**record, "score": round((dense_score * 0.65) + (lexical_score * 0.35) + bonus, 4)})

        ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return ranked[:limit]

    def _normalize_page(self, collection_id: str, page: dict) -> VisualPage:
        page_number = int(page.get("page_number") or 1)
        page_id = str(page.get("id") or f"{page.get('document_id', 'doc')}:{page_number}")
        text = str(page.get("text") or page.get("content") or "").strip()
        image_path = self._render_page_image(collection_id, page_id, page.get("title", "Visual page"), text)
        return VisualPage(
            id=page_id,
            collection_id=collection_id,
            document_id=str(page.get("document_id") or ""),
            page_number=page_number,
            title=str(page.get("title") or "Visual page"),
            text=text or str(page.get("title") or "Visual page"),
            is_complex=bool(page.get("is_complex", False)),
            image_path=str(image_path) if image_path else None,
            metadata=page.get("metadata") or {},
        )

    def _render_page_image(self, collection_id: str, page_id: str, title: str, text: str) -> Path | None:
        page_dir = self._storage_dir / collection_id
        page_dir.mkdir(parents=True, exist_ok=True)
        image_path = page_dir / f"{page_id}.png"
        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

            image = Image.new("RGB", (1400, 1800), color="white")
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("arial.ttf", 28)
                title_font = ImageFont.truetype("arial.ttf", 36)
            except Exception:
                font = ImageFont.load_default()
                title_font = ImageFont.load_default()
            draw.text((64, 48), title, fill="black", font=title_font)
            cursor_y = 120
            for line in wrap(text or "No content", width=96):
                draw.text((64, cursor_y), line, fill="black", font=font)
                cursor_y += 38
            image.save(image_path)
            return image_path
        except Exception:
            placeholder = image_path.with_suffix(".txt")
            placeholder.write_text(f"{title}\n\n{text}", encoding="utf-8")
            return placeholder

    async def _persist_local(self, collection_id: str, records: list[VisualPage]) -> None:
        path = self._storage_dir / f"{collection_id}.json"
        current = await self._load_local(collection_id)
        merged = [record for record in current if record.get("id") not in {item.id for item in records}]
        merged.extend(asdict(record) for record in records)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _load_local(self, collection_id: str) -> list[dict]:
        path = self._storage_dir / f"{collection_id}.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    @staticmethod
    def _from_payload(hit: dict) -> dict:
        payload = hit.get("payload") or hit
        payload = dict(payload)
        payload["score"] = float(hit.get("score", payload.get("score", 0.0)))
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
        return numerator / (left_norm * right_norm)
