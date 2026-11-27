"""Offline regression tests for the production saved-search implementation."""
import pytest

from wallapop_mcp.client import Wallapop, _saved_search_query
from wallapop_mcp.http import ApiError, Response


def test_filter_replay_preserves_specific_filters():
    assert _saved_search_query({
        "query": "keywords=bike&custom_filter=abc&next_page=old",
        "location": {"lat": 36.7, "lng": -4.4}, "radius_km": 100,
        "condition": "new", "max_sale_price": 400,
    }) == {"keywords": "bike", "custom_filter": "abc", "latitude": 36.7,
           "longitude": -4.4, "max_radius_kms": 100, "condition": "new",
           "max_sale_price": 400}


def test_list_and_replay_cursor_pages(monkeypatch):
    client = Wallapop(token="fake")
    monkeypatch.setattr(client, "_authed", lambda *a, **k: Response(200, {"data": {"saved_searches": [
        {"id": "s1", "title": "bike", "filters": {"keywords": "bike", "max_radius_kms": 100}}
    ]}}, True, False))
    assert client.list_saved_searches() == [{"id": "s1", "name": "bike",
                                            "filters": {"keywords": "bike", "max_radius_kms": 100}}]
    calls = []

    def request(method, path, params=None):
        calls.append((path, dict(params)))
        if path == "/search/components":
            return Response(200, {"search_id": "result"}, True, False)
        return Response(200, {"items": [{"id": "item1", "title": "Bike", "price": 99,
                                         "web_slug": "bike-123"}],
                              "next_page": None if params.get("next_page") else "cursor"}, True, False)

    monkeypatch.setattr(client, "_request", request)
    first = client.saved_search_results("s1")
    assert first["next_page"] == "cursor"
    assert first["result_search_id"] == "result"
    assert first["has_more"] is True
    assert first["items"][0]["url"].endswith("/item/bike-123")
    assert calls[0][1]["max_radius_kms"] == 100
    second = client.saved_search_results("s1", first["next_page"], first["result_search_id"])
    assert second["has_more"] is False
    assert [p for p, _ in calls] == ["/search/components", "/search/section", "/search/section"]
    assert calls[-1][1]["next_page"] == "cursor"
    assert calls[-1][1]["search_id"] == "result"
    with pytest.raises(ValueError, match="result_search_id"):
        client.saved_search_results("s1", "cursor")


def test_errors_are_not_empty_results(monkeypatch):
    client = Wallapop(token="fake")
    monkeypatch.setattr(client, "_authed", lambda *a, **k: Response(503, {}, False, False))
    with pytest.raises(ApiError, match="503"):
        client.list_saved_searches()
    with pytest.raises(ApiError, match="503"):
        client.saved_search_hits()


def test_multiple_pages_reuse_filters_without_detail_requests(monkeypatch):
    client = Wallapop(token="fake")
    list_calls = []
    monkeypatch.setattr(client, "list_saved_searches", lambda: list_calls.append(1) or [
        {"id": "s1", "name": "bike", "filters": {"keywords": "bike"}}])
    calls = []

    def request(method, path, params=None):
        calls.append(path)
        if path == "/search/components":
            return Response(200, {"search_id": "result"}, True, False)
        return Response(200, {"items": [{"id": "item1", "title": "Bike",
                                        "description": "A bike", "location": {"city": "Malaga"}}],
                              "next_page": None if params.get("next_page") else "cursor"}, True, False)

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "item", lambda *_: pytest.fail("unexpected detail lookup"))
    result = client.saved_search_results("s1", pages=2)
    assert list_calls == [1]
    assert calls == ["/search/components", "/search/section", "/search/section"]
    assert result["pages_scanned"] == 2
    assert result["has_more"] is False
    assert result["items"][0]["price"] is None
    assert result["items"][0]["url"] is None
    assert result["items"][0]["city"] == "Malaga"


def test_malformed_saved_search_page_is_not_empty_success(monkeypatch):
    client = Wallapop(token="fake")
    monkeypatch.setattr(client, "list_saved_searches", lambda: [
        {"id": "s1", "name": "bike", "filters": {"keywords": "bike"}}])
    monkeypatch.setattr(client, "_request", lambda *a, **kw: Response(
        200, {"search_id": "result"} if a[1] == "/search/components" else {"unexpected": True}, True, False))
    with pytest.raises(ApiError, match="no items array"):
        client.saved_search_results("s1")
