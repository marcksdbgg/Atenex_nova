"""Blob store — file system storage for uploaded documents."""

import hashlib
import logging
import shutil
from pathlib import Path

from atenex_nova.shared.config.settings import get_settings

logger = logging.getLogger(__name__)


class BlobStore:
    """File-system based blob storage."""

    def __init__(self, base_path: str | Path | None = None) -> None:
        self._base = Path(base_path or get_settings().blob_store_path)
        self._base.mkdir(parents=True, exist_ok=True)
        logger.info("BlobStore initialized → %s", self._base.resolve())

    def store(
        self,
        collection_id: str,
        doc_id: str,
        filename: str,
        data: bytes,
        relative_path: str | None = None,
    ) -> Path:
        normalized_relative_path = self._normalize_relative_path(relative_path, filename)
        target_dir = self._base / collection_id / doc_id / normalized_relative_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / normalized_relative_path.name
        target_path.write_bytes(data)
        logger.info("Stored %s (%d bytes)", target_path, len(data))
        return target_path

    def get_path(self, collection_id: str, doc_id: str, filename: str) -> Path:
        return self._base / collection_id / doc_id / filename

    def delete(self, collection_id: str, doc_id: str) -> None:
        target_dir = self._base / collection_id / doc_id
        if target_dir.exists():
            shutil.rmtree(target_dir)
            logger.info("Deleted %s", target_dir)

    @staticmethod
    def compute_checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _normalize_relative_path(relative_path: str | None, fallback_filename: str) -> Path:
        raw = (relative_path or fallback_filename).replace("\\", "/").strip().strip("/")
        parts = [part.strip() for part in raw.split("/") if part.strip() and part not in {".", ".."}]
        if not parts:
            parts = [fallback_filename]
        return Path(*parts)
