"""Typed helpers for normalizing HTTP request payloads at interface boundaries."""

from collections.abc import Mapping
from typing import Any

from rest_framework.request import Request


def request_data_mapping(request: Request) -> dict[str, Any]:
    """Return a string-key mapping, treating non-object JSON bodies as empty input."""

    raw_payload = request.data
    if not isinstance(raw_payload, Mapping):
        return {}
    return {str(key): value for key, value in raw_payload.items()}
