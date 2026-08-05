"""Canonical hashing helpers for immutable scenario research evidence."""

from __future__ import annotations

from hashlib import sha256
from re import fullmatch

_SHA256_PATTERN = r"[0-9a-f]{64}"


def hash_components(*components: str) -> str:
    """Return an unambiguous SHA-256 digest for ordered UTF-8 components."""

    digest = sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def require_sha256(value: str, field_name: str) -> None:
    """Require one lowercase 64-character SHA-256 hexadecimal digest."""

    if fullmatch(_SHA256_PATTERN, value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def require_token(value: str, field_name: str, *, maximum: int = 128) -> None:
    """Require a bounded non-blank token without whitespace or controls."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or len(value) > maximum or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} contains control characters")


def require_text(value: str, field_name: str, *, maximum: int = 256) -> None:
    """Require bounded, non-blank immutable text."""

    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-blank text")
    if any(ord(character) < 32 and character not in "\t\n" for character in value):
        raise ValueError(f"{field_name} contains unsupported control characters")
