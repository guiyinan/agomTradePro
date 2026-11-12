"""Domain evidence for exact, non-JSON provider document response bytes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from apps.data_center.domain.provider_response import ProviderResponseTransport

PUBLIC_DOCUMENT_SOURCE_TYPE = "public_document"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE_TOKEN = re.compile(r"[!#$%&'+.^_`|~0-9A-Za-z-]+\Z")


def normalize_document_content_type(content_type: str) -> str:
    """Return a concrete lower-case MIME essence from a Content-Type header."""

    if not isinstance(content_type, str) or len(content_type) > 512:
        raise ValueError("document content type must be a bounded string")
    if any(ord(character) < 32 or ord(character) == 127 for character in content_type):
        raise ValueError("document content type cannot contain control characters")
    essence = content_type.split(";", maxsplit=1)[0].strip()
    pieces = essence.split("/")
    if (
        len(pieces) != 2
        or not _MEDIA_TYPE_TOKEN.fullmatch(pieces[0])
        or not _MEDIA_TYPE_TOKEN.fullmatch(pieces[1])
        or "*" in essence
    ):
        raise ValueError("document content type must be one concrete MIME type")
    return essence.casefold()


def normalize_document_media_type_allowlist(value: object) -> frozenset[str]:
    """Validate an explicit immutable allowlist of concrete MIME essences."""

    if not isinstance(value, frozenset) or not value:
        raise ValueError("document media type allowlist must be a non-empty frozenset")
    normalized: set[str] = set()
    for media_type in value:
        if not isinstance(media_type, str) or ";" in media_type:
            raise ValueError("document media type allowlist cannot contain parameters")
        normalized.add(normalize_document_content_type(media_type))
    return frozenset(normalized)


@dataclass(frozen=True, slots=True)
class ProviderDocumentResponseCapture:
    """Bind exact raw document bytes to one routed request and local receipt time.

    This transport evidence establishes byte integrity and request identity
    only. It does not establish that the response is official, current, or
    applicable to a business policy.
    """

    request_id: UUID
    attempt: int
    egress_id: int | None
    target_url_sha256: str
    target_host: str
    body: bytes = field(repr=False)
    body_sha256: str
    body_size_bytes: int
    response_completed_at: datetime
    status_code: int
    content_type: str
    transport: ProviderResponseTransport

    def __post_init__(self) -> None:
        """Reject byte captures with unverifiable destination or metadata."""

        if not isinstance(self.request_id, UUID):
            raise ValueError("request_id must be a UUID")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if self.egress_id is not None and (
            isinstance(self.egress_id, bool)
            or not isinstance(self.egress_id, int)
            or self.egress_id < 1
        ):
            raise ValueError("egress_id must be positive when provided")
        if not isinstance(self.target_url_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.target_url_sha256
        ):
            raise ValueError("target_url_sha256 must be lowercase SHA-256")
        if (
            not isinstance(self.target_host, str)
            or not self.target_host
            or len(self.target_host) > 253
            or self.target_host != self.target_host.casefold()
            or self.target_host != self.target_host.strip()
            or any(ord(character) < 33 or ord(character) == 127 for character in self.target_host)
        ):
            raise ValueError("target_host must be a normalized host")
        if type(self.body) is not bytes or not self.body:
            raise ValueError("body must contain exact non-empty bytes")
        if not isinstance(self.body_sha256, str) or not _SHA256_PATTERN.fullmatch(self.body_sha256):
            raise ValueError("body_sha256 must be lowercase SHA-256")
        if hashlib.sha256(self.body).hexdigest() != self.body_sha256:
            raise ValueError("body_sha256 does not match body")
        if (
            isinstance(self.body_size_bytes, bool)
            or not isinstance(self.body_size_bytes, int)
            or self.body_size_bytes != len(self.body)
        ):
            raise ValueError("body_size_bytes does not match body")
        if not isinstance(self.response_completed_at, datetime):
            raise ValueError("response_completed_at must be UTC-aware")
        try:
            offset = self.response_completed_at.utcoffset()
        except (OverflowError, ValueError) as exc:
            raise ValueError("response_completed_at must be UTC-aware") from exc
        if self.response_completed_at.tzinfo is None or offset != timedelta(0):
            raise ValueError("response_completed_at must be UTC-aware")
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 200 <= self.status_code < 300
        ):
            raise ValueError("status_code must be successful")
        if not isinstance(self.content_type, str):
            raise ValueError("content_type must be a string")
        normalize_document_content_type(self.content_type)
        if not isinstance(self.transport, ProviderResponseTransport):
            raise ValueError("transport must be a ProviderResponseTransport")

    def is_bound_to(
        self,
        *,
        request_id: UUID,
        attempt: int,
        egress_id: int | None,
        target_url: str,
        target_host: str,
    ) -> bool:
        """Check that this capture belongs to one exact request attempt."""

        return (
            self.request_id == request_id
            and self.attempt == attempt
            and self.egress_id == egress_id
            and self.target_url_sha256 == hashlib.sha256(target_url.encode("utf-8")).hexdigest()
            and self.target_host == target_host
        )


__all__ = [
    "PUBLIC_DOCUMENT_SOURCE_TYPE",
    "ProviderDocumentResponseCapture",
    "normalize_document_content_type",
    "normalize_document_media_type_allowlist",
]
