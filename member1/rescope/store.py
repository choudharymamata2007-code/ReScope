"""SQLite evidence store (Task 1.1). Member 2 reads Evidence rows from here with the same model."""
from __future__ import annotations
import json, sqlite3, threading
from pathlib import Path
from typing import Iterable, Optional
from . import config
from .schema import Evidence, MetricSeries

SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence(
  id TEXT PRIMARY KEY, entity TEXT, role TEXT, source_type TEXT, period TEXT, date TEXT,
  origin_hash TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ev_entity ON evidence(entity, role, source_type);
CREATE INDEX IF NOT EXISTS idx_ev_hash ON evidence(origin_hash);
CREATE TABLE IF NOT EXISTS series(
  entity TEXT, name TEXT, role TEXT, payload TEXT NOT NULL, PRIMARY KEY(entity, name));
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT, started TEXT, payload TEXT);
"""


class EvidenceStore:
    def __init__(self, path: Path | str | None = None):
        self._lock = threading.Lock()
        p = str(path or config.DB_PATH)
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(p, check_same_thread=False)
        with self._lock:
            self.db.executescript(SCHEMA)

    def add(self, ev: Evidence) -> bool:
        """Insert or replace; returns True if the id was new."""
        with self._lock:
            new = self.db.execute("SELECT 1 FROM evidence WHERE id=?", (ev.id,)).fetchone() is None
            self.db.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?,?,?)",
                (ev.id, ev.entity, ev.role.value, ev.source_type.value, ev.period,
                 ev.date.isoformat() if ev.date else None, ev.origin_hash, ev.model_dump_json()))
            self.db.commit()
            return new

    def add_many(self, items: Iterable[Evidence]) -> int:
        return sum(1 for e in items if self.add(e))

    def get(self, ev_id: str) -> Optional[Evidence]:
        with self._lock:
            r = self.db.execute("SELECT payload FROM evidence WHERE id=?", (ev_id,)).fetchone()
        return Evidence.model_validate_json(r[0]) if r else None

    def query(self, entity=None, role=None, source_type=None, period=None) -> list[Evidence]:
        sql, args = "SELECT payload FROM evidence WHERE 1=1", []
        for col, val in (("entity", entity), ("role", role), ("source_type", source_type), ("period", period)):
            if val is not None:
                sql += f" AND {col}=?"
                args.append(val.value if hasattr(val, "value") else val)
        sql += " ORDER BY date, id"
        with self._lock:
            rows = self.db.execute(sql, args).fetchall()
        return [Evidence.model_validate_json(r[0]) for r in rows]

    def all(self) -> list[Evidence]:
        return self.query()

    def count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    def save_series(self, s: MetricSeries) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO series VALUES (?,?,?,?)",
                            (s.entity, s.name, s.role.value, s.model_dump_json()))
            self.db.commit()

    def load_series(self, entity: str) -> dict[str, MetricSeries]:
        with self._lock:
            rows = self.db.execute("SELECT payload FROM series WHERE entity=?", (entity,)).fetchall()
        out = {}
        for (payload,) in rows:
            s = MetricSeries.model_validate_json(payload)
            out[s.name] = s
        return out

    def export_json(self, path: Path | str, entity: str | None = None) -> int:
        items = self.query(entity=entity)
        Path(path).write_text(json.dumps([json.loads(e.model_dump_json()) for e in items], indent=2))
        return len(items)

    @staticmethod
    def load_json(path: Path | str) -> list[Evidence]:
        return [Evidence.model_validate(d) for d in json.loads(Path(path).read_text())]
