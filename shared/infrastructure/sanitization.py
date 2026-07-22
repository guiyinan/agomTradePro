"""Compatibility exports for the canonical shared sanitization helpers.

New code should import :mod:`shared.sanitization`. This module remains for
older callers while keeping one implementation and one security allowlist.
"""

from shared.sanitization import (
    SAFE_ATTRS,
    SAFE_TAGS,
    SAFE_URL_SCHEMES,
    SANITIZATION_WHITELIST,
    get_sanitization_config,
    sanitize_field,
    sanitize_inputs,
    sanitize_plain_text,
    sanitize_rich_text,
)

__all__ = [
    "SAFE_ATTRS",
    "SAFE_TAGS",
    "SAFE_URL_SCHEMES",
    "SANITIZATION_WHITELIST",
    "get_sanitization_config",
    "sanitize_field",
    "sanitize_inputs",
    "sanitize_plain_text",
    "sanitize_rich_text",
]
