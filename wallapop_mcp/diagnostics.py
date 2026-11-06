"""Small, allowlisted API error summaries safe to return through MCP."""

from __future__ import annotations

import re
from typing import Any


_TEXT_KEYS = frozenset({"message", "error_message", "reason", "detail", "description"})
_IDENTIFIER_KEYS = frozenset({"code", "error_code", "field", "attribute", "path", "property"})
_CONTAINER_KEYS = frozenset({"status", "error", "errors", "details", "violations", "validation_errors", "upstream", "data"})
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{12,}(?:\.[A-Za-z0-9_-]+){1,}\b")
_BEARER = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_NAMED_SECRET = re.compile(r"\b(access[_-]?token|refresh[_-]?token|session[_-]?token|authorization|cookie)\s*[:=]\s*[^\s,;]+", re.IGNORECASE)
_LONG_VALUE = re.compile(r"\b[A-Za-z0-9_=-]{48,}\b")


def safe_text(value: Any) -> str:
    """Remove common credentials and signed links from diagnostic text."""
    if not isinstance(value, str):
        return ""
    text = _URL.sub("[URL redacted]", value)
    text = _BEARER.sub("[credential redacted]", text)
    text = _JWT.sub("[credential redacted]", text)
    text = _NAMED_SECRET.sub("[credential redacted]", text)
    text = _LONG_VALUE.sub("[value redacted]", text)
    return text[:300]


def safe_error_payload(value: Any, depth: int = 0) -> Any:
    """Keep Wallapop's status, field, and message, never unknown payload keys."""
    if depth > 3:
        return None
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, list):
        return [item for raw in value[:10] if (item := safe_error_payload(raw, depth + 1))]
    if not isinstance(value, dict):
        return None
    result = {}
    for key, raw in value.items():
        if key in _TEXT_KEYS:
            if text := safe_text(raw):
                result[key] = text
        elif key in _IDENTIFIER_KEYS and isinstance(raw, (str, int)):
            if text := safe_text(str(raw)):
                result[key] = text
        elif key in _CONTAINER_KEYS:
            if nested := safe_error_payload(raw, depth + 1):
                result[key] = nested
    return result


def diagnostic_message(value: Any) -> str:
    """Find the most useful allowlisted upstream message, if available."""
    if isinstance(value, dict):
        if "upstream" in value and (message := diagnostic_message(value["upstream"])):
            return message
        for key in ("message", "detail", "reason", "error", "error_message"):
            candidate = value.get(key)
            if isinstance(candidate, str) and (message := safe_text(candidate)):
                return message
        for key in ("upstream", "status", "errors", "details", "violations", "data"):
            if message := diagnostic_message(value.get(key)):
                return message
    elif isinstance(value, list):
        for item in value[:10]:
            if message := diagnostic_message(item):
                return message
    elif isinstance(value, str):
        return safe_text(value)
    return ""
