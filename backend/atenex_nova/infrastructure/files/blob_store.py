"""Blob store — file system storage for uploaded documents."""

import hashlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class BlobStore:
    """File-system based blob storage."""

    def __init__(self, base_path: str | Path = "storage/uploads") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        logger.info("BlobStore initialized → %s", self._base.resolve())

    def store(self, collection_id: str, doc_id: str, filename: str, data: bytes) -> Path:
        target_dir = self._base / collection_id / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
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
