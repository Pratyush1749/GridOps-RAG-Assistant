"""Local filesystem storage backend.

Mirrors ``S3Storage`` but persists bytes as files under a local root directory.
Used by ``DocCacheService`` when ``STORAGE_BACKEND=local`` (the default).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.storage.storage_backend import StorageBackend

_DEFAULT_ROOT = Path(os.getenv("LOCAL_STORAGE_DIR", ".cache/storage"))


class LocalStorage(StorageBackend):
    """Stores bytes as files under ``root`` (keys may contain ``/`` sub-paths)."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else _DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def save_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def url_for(self, key: str) -> str:
        return self._path(key).resolve().as_uri()
