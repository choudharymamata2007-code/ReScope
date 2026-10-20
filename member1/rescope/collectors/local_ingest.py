"""Manual-download fallback that stays inside the same pipeline (Task 1.12 / 1.14).
If a site blocks automated access, download the PDF by hand into data/inbox/<kind>/ and run this.
Files go through exactly the same extraction, tagging and storage as fetched documents, are
labelled 'manual_download' in flags, and are never edited. Judges' rule: no hand-edited data."""
from __future__ import annotations
from pathlib import Path
from ..schema import Role
from ..store import EvidenceStore
from .documents import KINDS, DocumentCollector


def ingest_inbox(collector: DocumentCollector, inbox: Path | str, entity: str, role: Role,
                 store: EvidenceStore | None = None, max_pages: int = 80) -> int:
    """Folder layout: inbox/<kind>/*.pdf where kind in results|annual_report|presentation|transcript."""
    n = 0
    for kind in KINDS:
        d = Path(inbox) / kind
        if not d.exists():
            continue
        for f in sorted(d.glob("*.pdf")):
            collector.fetcher.cache.set(f"manual:{f.name}", f.read_bytes(), content_type="application/pdf", manual=True)  # kept in the shared cache
            items = collector.ingest_bytes(f.read_bytes(), f.resolve().as_uri(), entity, role, kind,
                                           title=f.stem.replace("_", " "), max_pages=max_pages)
            for e in items:
                e.flags.append("manual_download")
            if store:
                n += store.add_many(items)
            else:
                n += len(items)
    return n
