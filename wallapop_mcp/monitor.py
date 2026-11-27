"""Transactional, local saved-search monitoring."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .http import ApiError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, filters TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seen_items (
    id TEXT PRIMARY KEY, price TEXT, currency TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_searches (
    item_id TEXT NOT NULL, search_id TEXT NOT NULL, last_seen TEXT NOT NULL,
    PRIMARY KEY (item_id, search_id)
);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, selection TEXT NOT NULL, response TEXT NOT NULL);
"""


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scan_saved_searches(client, path: Path, run_id: str, *,
                        search_ids: Optional[list[str]] = None,
                        max_pages_per_search: int = 20) -> dict:
    if not run_id.strip() or len(run_id) > 200:
        raise ValueError("run_id must be non-empty and at most 200 characters")
    if not 1 <= max_pages_per_search <= 100:
        raise ValueError("max_pages_per_search must be between 1 and 100")
    if search_ids is not None and not search_ids:
        raise ValueError("search_ids must be omitted or a non-empty list")
    selection = _canonical(None if search_ids is None else sorted(set(search_ids)))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db:
        db.executescript(_SCHEMA)
        with db:
            db.execute("BEGIN IMMEDIATE")
            cached = db.execute("SELECT selection, response FROM runs WHERE id=?", (run_id,)).fetchone()
            if cached:
                if cached[0] != selection:
                    raise ValueError("run_id already used with a different search selection")
                return json.loads(cached[1])

            saved = client.list_saved_searches()
            if search_ids is not None:
                missing = set(search_ids) - {s["id"] for s in saved}
                if missing:
                    raise ValueError("unknown saved search ID(s): " + ", ".join(sorted(missing)))
                saved = [s for s in saved if s["id"] in search_ids]

            initialized = dict(db.execute("SELECT id, filters FROM searches"))
            active = set()
            scans = []
            observations = {}
            memberships = {}
            for search in saved:
                sid = search["id"]
                filters = _canonical(search["filters"])
                baseline = initialized.get(sid) != filters
                if not baseline:
                    active.add(sid)
                page = client._saved_search_pages(search, pages=max_pages_per_search)
                if page["has_more"]:
                    raise ApiError(f"saved search {sid} exceeded page limit; retry with a higher max_pages_per_search")
                for listing in page["items"]:
                    iid = listing["id"]
                    memberships.setdefault(iid, set()).add(sid)
                    if iid not in observations or listing["price"] is not None:
                        observations[iid] = listing
                scans.append({"id": sid, "name": search["name"], "baseline": baseline,
                              "pages": page["pages_scanned"], "items": len(page["items"])})
                db.execute("INSERT OR REPLACE INTO searches VALUES (?, ?)", (sid, filters))

            now = datetime.now(timezone.utc).isoformat()
            changes = []
            for iid, listing in observations.items():
                previous = db.execute("SELECT price, currency FROM seen_items WHERE id=?", (iid,)).fetchone()
                price = str(Decimal(str(listing["price"]))) if listing["price"] is not None else None
                currency = listing["currency"]
                members = sorted(memberships[iid])
                kind = None
                if memberships[iid] & active:
                    if previous is None:
                        kind = "new"
                    elif (price is not None and previous[0] is not None
                          and previous[1] == currency and Decimal(price) < Decimal(previous[0])):
                        kind = "price_drop"
                if kind:
                    event = dict(listing, event_id=f"{run_id}:{iid}", kind=kind, search_ids=members)
                    if kind == "price_drop":
                        event["previous_price"] = float(Decimal(previous[0]))
                    changes.append(event)
                if previous is None:
                    db.execute("INSERT INTO seen_items VALUES (?, ?, ?, ?, ?)", (iid, price, currency, now, now))
                elif price is not None:
                    db.execute("UPDATE seen_items SET price=?, currency=?, last_seen=? WHERE id=?",
                               (price, currency, now, iid))
                else:
                    db.execute("UPDATE seen_items SET last_seen=? WHERE id=?", (now, iid))
                for sid in members:
                    db.execute("INSERT OR REPLACE INTO item_searches VALUES (?, ?, ?)", (iid, sid, now))

            response = {"ok": True, "run_id": run_id, "searches": scans,
                        "unique_items": len(observations), "changes": changes,
                        "new_count": sum(c["kind"] == "new" for c in changes),
                        "price_drop_count": sum(c["kind"] == "price_drop" for c in changes)}
            db.execute("INSERT INTO runs VALUES (?, ?, ?)", (run_id, selection, _canonical(response)))
            return response
