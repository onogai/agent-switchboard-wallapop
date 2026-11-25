"""Tests for the Python MCP server (wallapop_mcp.mcp_server).

No network: these only check tool registration, read/write gating, session
enforcement and argument shaping.
"""
import asyncio

import pytest

import wallapop_mcp.mcp_server as mcp_server
from wallapop_mcp.photo_inputs import OpenAIFile

READ_TOOLS = {
    "session_status", "search", "get_item", "get_seller", "list_categories",
    "list_inbox", "get_conversation", "unread_count", "list_purchases",
    "list_sales", "get_offer_constraints", "get_offer_status",
    "seller_items", "suggest", "list_favorites", "list_saved_searches",
    "saved_search_results", "saved_search_hits",
    "check_saved_search",
}
WRITE_TOOLS = {
    "set_favorite", "send_message", "send_offer", "respond_offer",
    "counter_offer", "publish_item", "edit_item", "reserve_item",
    "mark_sold", "pause_item", "delete_item", "save_search",
    "remove_saved_search",
}


def _tool_names(allow_writes):
    srv = mcp_server.build_server(allow_writes)
    return {t.name for t in asyncio.run(srv.list_tools())}


def test_writes_hidden_by_default(tmp_path):
    mcp_server._init(str(tmp_path), allow_writes=False)
    reads = _tool_names(False)
    assert reads == READ_TOOLS
    assert not (reads & WRITE_TOOLS)


def test_allow_writes_exposes_mutations(tmp_path):
    mcp_server._init(str(tmp_path), allow_writes=True)
    both = _tool_names(True)
    assert both == READ_TOOLS | WRITE_TOOLS
    assert len(both) == 32


def test_account_tool_requires_a_session(tmp_path, monkeypatch):
    monkeypatch.delenv("WALLAPOP_ACCESS_TOKEN", raising=False)
    mcp_server._init(str(tmp_path), allow_writes=True)  # empty dir -> no token
    with pytest.raises(RuntimeError, match="session"):
        mcp_server.unread_count()


def test_publish_rejects_non_shipping(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    result = mcp_server.publish_item(
        title="t", description="d", price=10.0, category_leaf_id="10311",
        condition="good", photo_paths=["x.jpg"], shipping_allowed=False,
    )
    assert result["ok"] is False
    assert "shipping" in result["error"]


def test_publish_downloads_chatgpt_files_before_publishing(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    downloaded = []

    def fake_download(file, destination):
        downloaded.append(file.file_id)
        destination.write_bytes(b"jpeg")

    def fake_publish(**kwargs):
        assert [open(path, "rb").read() for path in kwargs["photo_paths"]] == [b"jpeg", b"jpeg"]
        return mcp_server.Response(200, {"id": "item-1"}, True, False)

    monkeypatch.setattr(mcp_server, "download_photo", fake_download)
    monkeypatch.setattr(mcp_server._c(), "publish", fake_publish)
    files = [OpenAIFile(download_url=f"https://files.oaiusercontent.com/file-{i}", file_id=f"file-{i}") for i in (1, 2)]
    result = mcp_server.publish_item("T", "D", 10.0, "10311", "good", photo_files=files)
    assert result["ok"] is True
    assert downloaded == ["file-1", "file-2"]


def test_publish_rejects_missing_or_ambiguous_photos(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    assert "exactly one" in mcp_server.publish_item("T", "D", 10.0, "10311", "good")["error"]
    assert "exactly one" in mcp_server.publish_item(
        "T", "D", 10.0, "10311", "good", photo_paths=["a.jpg"],
        photo_files=[OpenAIFile(download_url="https://files.oaiusercontent.com/1", file_id="1")],
    )["error"]


@pytest.mark.parametrize("file_input", [
    {"download_url": "https://files.oaiusercontent.com/1", "file_id": "file_1"},
    "data:image/jpeg;base64,YQ==",
])
def test_mcp_publish_accepts_object_and_inline_string_file_inputs(tmp_path, monkeypatch, file_input):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    monkeypatch.setattr(mcp_server, "download_photo", lambda _file, destination: destination.write_bytes(b"jpeg"))
    monkeypatch.setattr(mcp_server._c(), "publish", lambda **_kwargs: mcp_server.Response(200, {"id": "item-1"}, True, False))
    result = asyncio.run(mcp_server.build_server(True).call_tool("publish_item", {
        "title": "T", "description": "D", "price": 10.0,
        "category_leaf_id": "10311", "condition": "good", "photo_files": [file_input],
    }))
    assert not result.is_error


def test_publish_returns_download_error_without_creating_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    monkeypatch.setattr(mcp_server._c(), "publish", lambda **_kwargs: pytest.fail("listing creation attempted"))
    result = mcp_server.publish_item("T", "D", 10.0, "10311", "good", photo_files=[
        OpenAIFile(download_url="https://private.example/file", file_id="file-1")
    ])
    assert result["ok"] is False
    assert result["data"]["error_message"] == "photo 1: photo download URL host is not allowed: private.example"


def test_mcp_publish_reports_upstream_400_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    monkeypatch.setattr(mcp_server._c(), "publish", lambda **_kwargs: mcp_server.Response(
        400, {"error_message": "publish POST failed with HTTP 400", "upstream": {
            "code": "INVALID_ATTRIBUTE", "message": "unsupported color", "field": "color",
            "authorization": "Bearer secret", "redirect": "https://example.test/?sig=secret",
        }}, False, False,
    ))
    response = mcp_server.publish_item("T", "D", 10.0, "10311", "good", photo_paths=["photo.jpg"])
    assert response["status"] == 400
    assert response["data"]["upstream"]["field"] == "color"
    assert "unsupported color" in response["error"]
    assert "secret" not in str(response)


def test_listing_tools_reject_numeric_id_with_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    monkeypatch.setattr(mcp_server._c(), "item", lambda *_args: pytest.fail("get_item called"))
    monkeypatch.setattr(mcp_server._c(), "delete_item", lambda *_args: pytest.fail("delete_item called"))
    monkeypatch.setattr(mcp_server._c(), "edit_item", lambda *_args, **_kwargs: pytest.fail("edit_item called"))
    for call in (mcp_server.get_item, mcp_server.delete_item, mcp_server.edit_item):
        response = call("1321487684")
        assert response["ok"] is False
        assert "internal item_id" in response["error"]


def test_get_item_upstream_404_is_structured(tmp_path, monkeypatch):
    mcp_server._init(str(tmp_path), allow_writes=False)
    monkeypatch.setattr(mcp_server._c(), "item", lambda _id: (_ for _ in ()).throw(
        mcp_server.ApiError("item 9jdw3gx0ml6k unavailable (404): no error detail supplied")
    ))
    response = mcp_server.get_item("9jdw3gx0ml6k")
    assert response["ok"] is False
    assert response["status"] == 404
    assert "unavailable" in response["error"]


def test_publish_tool_schema_explains_files_and_optional_attributes():
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.build_server(True).list_tools())}
    publish = tools["publish_item"]
    props = publish.input_schema["properties"]
    assert "download_url" in props["photo_files"]["description"]
    assert "category" in props["brand"]["description"]
    assert "numeric ID" in tools["delete_item"].input_schema["properties"]["item_id"]["description"]


def test_save_search_sends_the_web_filter_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    seen = {}
    monkeypatch.setattr(mcp_server._c(), "top_level_category", lambda cid: 24200)
    monkeypatch.setattr(mcp_server._c(), "save_search", lambda params: seen.update(params) or "uuid-1")
    out = mcp_server.save_search(
        "switch 2", category_id=24203, max_price=300, shippable=True,
        latitude=40.4, longitude=-3.7,
    )
    assert out == {"ok": True, "id": "uuid-1"}
    assert seen == {
        "keywords": "switch 2", "source": "search_box", "filters_source": "search_box",
        "order_by": "most_relevance", "category_id": 24200, "max_sale_price": 300,
        "is_shippable": "true", "latitude": 40.4, "longitude": -3.7,
    }


def test_saved_search_rejects_half_a_coordinate(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=True)
    with pytest.raises(ValueError, match="latitude"):
        mcp_server.check_saved_search("switch", latitude=40.4)


def test_check_saved_search_reports_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=False)
    monkeypatch.setattr(mcp_server._c(), "saved_search_exists", lambda params: None)
    assert mcp_server.check_saved_search("switch") == {"saved": False, "id": None}


def test_saved_search_read_tools_delegate(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLAPOP_ACCESS_TOKEN", "tok")
    mcp_server._init(str(tmp_path), allow_writes=False)
    searches = [{"id": "s1", "name": "bike", "filters": {"keywords": "bike"}}]
    monkeypatch.setattr(mcp_server._c(), "list_saved_searches", lambda: searches)
    assert mcp_server.list_saved_searches() == searches
    seen = []
    monkeypatch.setattr(mcp_server._c(), "saved_search_results",
                        lambda *args: seen.append(args) or {"items": [], "has_more": False})
    assert mcp_server.saved_search_results("s1", "cursor", "result")["has_more"] is False
    assert seen == [("s1", "cursor", "result")]
