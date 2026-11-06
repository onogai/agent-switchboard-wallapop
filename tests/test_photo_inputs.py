"""ChatGPT photo inputs stay bounded and never fetch arbitrary hosts."""

import base64
from io import BytesIO

import pytest
from PIL import Image

from wallapop_mcp.photo_inputs import OpenAIFile, download_photo


def test_download_photo_converts_png_to_jpeg(monkeypatch, tmp_path):
    image = Image.new("RGB", (4, 3), "red")
    buffer = BytesIO()
    image.save(buffer, "PNG")

    class Response:
        headers = {"Content-Length": str(len(buffer.getvalue()))}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            return buffer.getvalue()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith("https://files.oaiusercontent.com/")
            assert timeout == 20
            return Response()

    monkeypatch.setattr("wallapop_mcp.photo_inputs.build_opener", lambda *_: Opener())
    destination = tmp_path / "photo.jpg"
    download_photo(OpenAIFile(download_url="https://files.oaiusercontent.com/file-1", file_id="file-1", mime_type="image/png"), destination)
    with Image.open(destination) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (4, 3)


def test_data_url_string_is_accepted_and_converted_without_network(monkeypatch, tmp_path):
    image = Image.new("RGB", (4, 3), "blue")
    buffer = BytesIO()
    image.save(buffer, "JPEG")
    value = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    file = OpenAIFile.model_validate(value)
    monkeypatch.setattr("wallapop_mcp.photo_inputs.build_opener", lambda *_: pytest.fail("network attempted"))
    destination = tmp_path / "photo.jpg"
    download_photo(file, destination)
    with Image.open(destination) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (4, 3)


def test_bare_file_id_has_actionable_error():
    with pytest.raises(ValueError, match="file_id alone cannot be downloaded"):
        OpenAIFile.model_validate("file_example")


@pytest.mark.parametrize("url", [
    "http://files.oaiusercontent.com/file-1",
    "https://127.0.0.1/file-1",
    "https://files.oaiusercontent.com.evil.example/file-1",
    "https://user@files.oaiusercontent.com/file-1",
    "https://other.blob.core.windows.net/file-1",
    "https://oaisdmntprukwest.blob.core.windows.net.evil.example/file-1",
])
def test_rejects_non_openai_urls_before_network(monkeypatch, tmp_path, url):
    monkeypatch.setattr("wallapop_mcp.photo_inputs.build_opener", lambda *_: pytest.fail("network attempted"))
    with pytest.raises(ValueError, match="host is not allowed"):
        download_photo(OpenAIFile(download_url=url, file_id="file-1"), tmp_path / "photo.jpg")


@pytest.mark.parametrize("host", ["files.chatgpt.com", "oaisdmntprukwest.blob.core.windows.net"])
def test_chatgpt_download_host_is_accepted(monkeypatch, tmp_path, host):
    image = Image.new("RGB", (2, 2), "green")
    buffer = BytesIO()
    image.save(buffer, "JPEG")

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            return buffer.getvalue()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == f"https://{host}/download"
            return Response()

    monkeypatch.setattr("wallapop_mcp.photo_inputs.build_opener", lambda *_: Opener())
    destination = tmp_path / "photo.jpg"
    download_photo(OpenAIFile(download_url=f"https://{host}/download", file_id="file-1"), destination)
    assert destination.exists()


def test_rejects_oversize_before_read(monkeypatch, tmp_path):
    class Response:
        headers = {"Content-Length": str(16 * 1024 * 1024)}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            pytest.fail("oversize body read")

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr("wallapop_mcp.photo_inputs.build_opener", lambda *_: Opener())
    with pytest.raises(ValueError, match="15 MB"):
        download_photo(OpenAIFile(download_url="https://files.oaiusercontent.com/file-1", file_id="file-1"), tmp_path / "photo.jpg")
