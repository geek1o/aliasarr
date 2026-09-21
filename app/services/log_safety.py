"""Helpers for keeping credentials out of application logs."""

from __future__ import annotations

import re
from typing import Any


_SENSITIVE_QUERY_VALUE_RE = re.compile(
    r"(?i)(\b(?:apikey|api_key|passkey|access_token|token|password)=)([^&\s'\"<>]+)"
)


def redact_sensitive_data(value: Any, *, limit: int | None = None) -> str:
    """Return log-safe text with common query-string credentials redacted."""
    message = str(value)
    message = _SENSITIVE_QUERY_VALUE_RE.sub(r"\1<redacted>", message)
    return message if limit is None else message[:limit]
