import json
import runpy
from pathlib import Path
import pytest

adopt = runpy.run_path(str(Path(__file__).parents[1] / "scripts/adopt_session.py"))["adopt"]


def paths(tmp_path):
    source, dest = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    dest.mkdir()
    return source, dest


def test_file_session(tmp_path):
    source, dest = paths(tmp_path)
    (source / "credentials.json").write_text('{"access_token":"example"}')
    adopt(source, dest, {})
    assert json.loads((dest / "credentials.json").read_text())["access_token"] == "example"
    assert (dest / "credentials.json").stat().st_mode & 0o777 == 0o600
    assert (source / "credentials.json").exists()


def test_browser_env_replaces_other_account(tmp_path):
    source, dest = paths(tmp_path)
    (source / "credentials.json").write_text('{"access_token":"old"}')
    (source / "session.json").write_text('{"__Secure-next-auth.session-token":"old"}')
    adopt(source, dest, {"WALLAPOP_BROWSER_SESSION_TOKEN":"new", "WALLAPOP_DEVICE_ID":"device"})
    assert json.loads((dest / "credentials.json").read_text()) == {}
    assert json.loads((dest / "session.json").read_text()) == {"__Secure-next-auth.session-token":"new", "device_id":"device"}


def test_explicit_access_token(tmp_path):
    source, dest = paths(tmp_path)
    (source / "session.json").write_text('{"__Secure-next-auth.session-token":"old"}')
    adopt(source, dest, {"WALLAPOP_ACCESS_TOKEN":"new", "WALLAPOP_REFRESH_TOKEN":"refresh"})
    assert json.loads((dest / "session.json").read_text()) == {}
    assert json.loads((dest / "credentials.json").read_text()) == {"access_token":"new", "refresh_token":"refresh"}


def test_refuses_nonempty_destination(tmp_path):
    source, dest = paths(tmp_path)
    (dest / "session.json").write_text("{}")
    with pytest.raises(ValueError):
        adopt(source, dest, {"WALLAPOP_ACCESS_TOKEN":"new"})
    assert (dest / "session.json").read_text() == "{}"
