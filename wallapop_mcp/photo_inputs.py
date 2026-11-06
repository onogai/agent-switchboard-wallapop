"""Fetch ChatGPT file inputs and prepare JPEGs for Wallapop publishing."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, model_validator


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

    @model_validator(mode="before")
    @classmethod
    def accept_inline_image(cls, value):
        # Some MCP clients expose openai/fileParams as string[] to the agent
        # and forward those strings unchanged. A data URL is self-contained;
        # a bare file_id cannot be fetched without an OpenAI credential.
        if isinstance(value, str):
            if value.startswith("file_"):
                raise ValueError("a ChatGPT file_id alone cannot be downloaded; pass an OpenAIFile object or image data URL")
            if value.startswith("data:image/") or value.startswith("https://"):
                return {"download_url": value, "file_id": "inline"}
        return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def download_photo(file: OpenAIFile, destination: Path) -> None:
    """Download one temporary OpenAI attachment, bounded and converted to JPEG."""
    if file.mime_type and file.mime_type not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("photo must be a JPEG, PNG, or WebP image")

    if file.download_url.startswith("data:"):
        header, separator, encoded = file.download_url.partition(",")
        if not separator or header not in ("data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"):
            raise ValueError("photo data URL must contain a JPEG, PNG, or WebP image")
        if len(encoded) > (MAX_DOWNLOAD_BYTES + 2) // 3 * 4:
            raise ValueError("photo exceeds 15 MB")
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("photo data URL is not valid base64") from exc
    else:
        url = urlsplit(file.download_url)
        host = (url.hostname or "").lower()
        allowed_host = host == "oaisdmntprukwest.blob.core.windows.net" or any(
            host == domain or host.endswith("." + domain)
            for domain in ("oaiusercontent.com", "openai.com", "chatgpt.com")
        )
        if (
            url.scheme != "https"
            or not allowed_host
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
        ):
            safe_host = host[:80] if host and all(char.isalnum() or char in ".-" for char in host) else "unknown"
            raise ValueError(f"photo download URL host is not allowed: {safe_host}")
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
