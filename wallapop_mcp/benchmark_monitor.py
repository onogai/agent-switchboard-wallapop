"""Opt-in live diagnostics, isolated from production monitoring history.

Run inside the configured container while other Wallapop callers are paused:
    python -m wallapop_mcp.benchmark_monitor [--second-scan]
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from pathlib import Path

from .models import deep_find, first
from .monitor import scan_saved_searches
from .session import build_client
from .tokens import user_hash_of


def size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--second-scan", action="store_true")
    parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    start = time.monotonic()
    client, _ = build_client()
    print(json.dumps({"session_init_ms": round((time.monotonic()-start)*1000),
                      "stable_account_id": bool(user_hash_of(client.token or ""))}), flush=True)
    original = client._request
    calls = Counter()
    fields = Counter()
    response_bytes = Counter()
    page_shapes = Counter()
    status_counts = Counter()
    request_ms = Counter()

    def measured(method, path, *pos, **kw):
        calls[path] += 1
        t0 = time.monotonic()
        try:
            response = original(method, path, *pos, **kw)
        finally:
            request_ms[path] += round((time.monotonic()-t0)*1000)
        status_counts[f"{path}:{response.status}"] += 1
        response_bytes[path] += size(response.data)
        if path == "/search/section":
            items = first(v for v in deep_find(response.data, "items") if isinstance(v, list))
            page_shapes["missing_items" if items is None else "empty_items" if not items else "nonempty_items"] += 1
            for item in items or []:
                if isinstance(item, dict):
                    fields.update(item.keys())
        return response

    client._request = measured
    with tempfile.TemporaryDirectory(prefix="wallapop-monitor-bench-") as directory:
        path = Path(directory) / "monitor.sqlite3"
        try:
            for run_id in (["baseline", "replay", "fresh"] if args.second_scan else ["baseline", "replay"]):
                t0 = time.monotonic()
                before = sum(calls.values())
                result = scan_saved_searches(client, path, "baseline" if run_id == "replay" else run_id,
                                             max_pages_per_search=args.max_pages)
                print(json.dumps({"run": run_id, "ms": round((time.monotonic()-t0)*1000),
                                  "http_requests": sum(calls.values()) - before,
                                  "response_bytes": size(result), "searches": [
                                      {k: s[k] for k in ("baseline", "pages", "items")} for s in result["searches"]],
                                  "unique_items": result["unique_items"],
                                  "new_count": result["new_count"], "price_drop_count": result["price_drop_count"],
                                  "price_conflicts": result["price_conflicts"]}), flush=True)
                if run_id == "replay":
                    assert sum(calls.values()) == before
        except Exception as exc:
            # Do not dump upstream bodies, credentials, cursors or listing contents.
            print(json.dumps({"error_type": type(exc).__name__}), flush=True)
            return_code = 1
        else:
            return_code = 0
        finally:
            print(json.dumps({"requests": calls, "request_ms": request_ms,
                              "parsed_response_bytes": response_bytes, "statuses": status_counts,
                              "page_shapes": page_shapes, "listing_field_counts": fields}), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
