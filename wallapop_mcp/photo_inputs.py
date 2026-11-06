"""Fetch ChatGPT file inputs and prepare JPEGs for Wallapop publishing."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict


MAX_PHOTOS = 10
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000


class OpenAIFile(BaseModel):
    """File object supplied by ChatGPT's openai/fileParams extension."""

    model_config = ConfigDict(extra="forbid")

    download_url: str
    file_id: str
    mime_type: str = None
    file_name: str = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def download_photo(file: OpenAIFile, destination: Path) -> None:
    """Download one temporary OpenAI attachment, bounded and converted to JPEG."""
    url = urlsplit(file.download_url)
    host = (url.hostname or "").lower()
    if (
        url.scheme != "https"
        or not (host == "oaiusercontent.com" or host.endswith(".oaiusercontent.com"))
        or url.username is not None
        or url.password is not None
        or url.port not in (None, 443)
    ):
        raise ValueError("photo download URL must be an OpenAI HTTPS file URL")
    if file.mime_type and file.mime_type not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("photo must be a JPEG, PNG, or WebP image")

    try:
        request = Request(file.download_url, headers={"Accept": "image/*"})
        with build_opener(_NoRedirect).open(request, timeout=20) as response:
            if int(response.headers.get("Content-Length", "0")) > MAX_DOWNLOAD_BYTES:
                raise ValueError("photo exceeds 15 MB")
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("could not download ChatGPT photo") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("photo exceeds 15 MB")

    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("photo must be a JPEG, PNG, or WebP image")
            if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("photo exceeds 40 million pixels")
            image.load()
            converted = ImageOps.exif_transpose(image).convert("RGB")
            converted.save(destination, format="JPEG", quality=90)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("photo is invalid or too large to decode") from exc
