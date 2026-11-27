import pytest

from wallapop_mcp.http import ApiError
from wallapop_mcp.monitor import scan_saved_searches


def item(iid, price):
    return {"id": iid, "price": price, "currency": "EUR", "title": iid}


class Client:
    def __init__(self):
        self.results = {"a": [item("old", 100)], "b": [item("old", 100)]}
        self.fail = None
        self.truncated = None
        self.calls = 0

    def list_saved_searches(self):
        self.calls += 1
        return [{"id": sid, "name": sid, "filters": {"keywords": sid}} for sid in self.results]

    def _saved_search_pages(self, saved, *, pages):
        sid = saved["id"]
        if self.fail == sid:
            raise ApiError("network error")
        return {"items": self.results[sid], "has_more": self.truncated == sid, "pages_scanned": 1}


def test_baseline_delta_dedup_and_replay(tmp_path):
    path = tmp_path / "monitor.db"
    c = Client()
    assert scan_saved_searches(c, path, "first")["changes"] == []
    c.results = {"a": [item("old", 80), item("new", 50)], "b": [item("new", 50)]}
    result = scan_saved_searches(c, path, "second")
    assert result["new_count"] == result["price_drop_count"] == 1
    changes = {x["id"]: x for x in result["changes"]}
    assert changes["old"]["previous_price"] == 100
    assert changes["new"]["search_ids"] == ["a", "b"]
    assert c.calls == 2
    assert scan_saved_searches(c, path, "second") == result
    assert c.calls == 2
    assert scan_saved_searches(c, path, "third")["changes"] == []


def test_failure_and_truncation_rollback(tmp_path):
    path = tmp_path / "monitor.db"
    c = Client()
    scan_saved_searches(c, path, "first")
    c.results["a"] = [item("old", 90), item("new", 10)]
    c.results["b"] = [item("old", 90)]
    c.fail = "b"
    with pytest.raises(ApiError):
        scan_saved_searches(c, path, "retry")
    c.fail = None
    c.truncated = "b"
    with pytest.raises(ApiError, match="page limit"):
        scan_saved_searches(c, path, "retry")
    c.truncated = None
    result = scan_saved_searches(c, path, "retry")
    assert result["new_count"] == result["price_drop_count"] == 1


def test_added_search_silent_and_unknown_price(tmp_path):
    path = tmp_path / "monitor.db"
    c = Client()
    scan_saved_searches(c, path, "first")
    c.results["a"] = [item("old", None)]
    c.results["b"] = []
    c.results["c"] = [item("baseline", 10)]
    assert scan_saved_searches(c, path, "second")["changes"] == []
    c.results["a"] = [item("old", 90)]
    c.results["c"].append(item("new", 2))
    result = scan_saved_searches(c, path, "third")
    assert result["new_count"] == result["price_drop_count"] == 1


def test_replay_rejects_changed_selection(tmp_path):
    c = Client()
    path = tmp_path / "monitor.db"
    scan_saved_searches(c, path, "same", search_ids=["a"])
    with pytest.raises(ValueError, match="different search selection"):
        scan_saved_searches(c, path, "same", search_ids=["b"])


@pytest.mark.parametrize("prices", [(80, 100), (100, 80)])
def test_conflicting_prices_do_not_report_or_advance_price(tmp_path, prices):
    c = Client()
    path = tmp_path / "monitor.db"
    scan_saved_searches(c, path, "first")
    c.results = {"a": [item("old", prices[0])], "b": [item("old", prices[1])]}
    result = scan_saved_searches(c, path, "conflict")
    assert result["price_conflicts"] == 1
    assert result["changes"] == []
    c.results = {"a": [item("old", 80)], "b": [item("old", 80)]}
    result = scan_saved_searches(c, path, "confirmed")
    assert result["price_drop_count"] == 1
    assert result["changes"][0]["previous_price"] == 100
