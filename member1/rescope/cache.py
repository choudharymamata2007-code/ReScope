"""Small disk cache with TTL (Task 1.12). Stores bytes or JSON-able values under a hashed key."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from typing import Any, Optional
from . import config


class DiskCache:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or config.CACHE_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str):
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        d = self.root / h[:2]
        d.mkdir(exist_ok=True)
        return d / f"{h}.bin", d / f"{h}.meta.json"

    def get(self, key: str, ttl: Optional[float] = None) -> Optional[bytes]:
        data_p, meta_p = self._paths(key)
        if not data_p.exists() or not meta_p.exists():
            return None
        meta = json.loads(meta_p.read_text())
        if ttl is not None and time.time() - meta["stored_at"] > ttl:
            return None
        return data_p.read_bytes()

    def set(self, key: str, value: bytes, **meta: Any) -> None:
        data_p, meta_p = self._paths(key)
        data_p.write_bytes(value)
        meta_p.write_text(json.dumps({"key": key, "stored_at": time.time(), **meta}))

    def get_json(self, key: str, ttl: Optional[float] = None):
        raw = self.get(key, ttl)
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def set_json(self, key: str, value: Any, **meta: Any) -> None:
        self.set(key, json.dumps(value, default=str).encode("utf-8"), **meta)

    def has(self, key: str) -> bool:
        return self._paths(key)[0].exists()

    def label(self, key: str) -> Optional[dict]:
        meta_p = self._paths(key)[1]
        return json.loads(meta_p.read_text()) if meta_p.exists() else None
