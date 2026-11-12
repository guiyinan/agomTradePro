"""Explicit unqualified source-capture catalog values."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from apps.data_center.domain.provider_document_response import (
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)

_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_MAX_PROFILE_TEXT = 128


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    """Require a bounded, non-empty exact string without control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError(f"{field_name} must be non-empty bounded text without controls")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be UTF-8 representable") from error
    return value


def _validate_dns_hostname(host: object) -> str:
    """Require one canonical ASCII DNS hostname and reject URL/IP forms."""

    if (
        type(host) is not str
        or not host
        or len(host) > 253
        or not host.isascii()
        or host != host.lower()
        or host.endswith(".")
        or "*" in host
    ):
        raise ValueError("allowed host must be a canonical ASCII DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("allowed host must not be an IP address")
    labels = host.split(".")
    if any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        raise ValueError("allowed host must be a canonical ASCII DNS hostname")
    return host


def _revision_payload(revision: StatutorySourceDocumentRevision) -> dict[str, object]:
    """Serialize every pinned native revision field, retaining date precision."""

    return {
        "document_id": revision.document_id,
        "source_version": revision.source_version,
        "canonical_url": revision.canonical_url,
        "issuer": revision.issuer,
        "title": revision.title,
        "legal_number": revision.legal_number,
        "publication_date": _date_payload(revision.publication_date),
        "effective_date": _date_payload(revision.effective_date),
        "body_sha256": revision.body_sha256,
        "body_size_bytes": revision.body_size_bytes,
    }


def _date_payload(evidence: StatutorySourceDateEvidence) -> dict[str, str | None]:
    """Encode date evidence without guessing dates or normalizing source zones."""

    if evidence.precision is StatutorySourceDatePrecision.DATE:
        if evidence.date_value is None:
            raise ValueError("date evidence has no value")
        value = evidence.date_value.isoformat()
    elif evidence.precision is StatutorySourceDatePrecision.INSTANT:
        if evidence.instant_value is None:
            raise ValueError("instant evidence has no value")
        value = evidence.instant_value.isoformat()
    else:
        value = None
    return {"precision": evidence.precision.value, "value": value}


@dataclass(frozen=True, slots=True)
class StatutorySourceDocumentCaptureRule:
    """One explicit source revision and bounded raw-body capture rule.

    The rule is configuration structure only. It does not qualify an official
    publisher, activate policy, or authorize a financial action.
    """

    revision: StatutorySourceDocumentRevision
    max_bytes: int
    allowed_media_types: frozenset[str]

    def __post_init__(self) -> None:
        """Validate exact revision, capacity, and concrete MIME allowlist."""

        if type(self.revision) is not StatutorySourceDocumentRevision:
            raise ValueError("revision must be an exact source document revision")
        if type(self.max_bytes) is not int or self.max_bytes <= 0 or self.max_bytes >= sys.maxsize:
            raise ValueError("max_bytes must be a positive integer below sys.maxsize")
        if self.max_bytes < self.revision.body_size_bytes:
            raise ValueError("max_bytes is smaller than the pinned source body")
        if type(self.allowed_media_types) is not frozenset or any(
            type(media_type) is not str for media_type in self.allowed_media_types
        ):
            raise ValueError("allowed_media_types must be a frozenset of exact strings")
        normalized = normalize_document_media_type_allowlist(self.allowed_media_types)
        object.__setattr__(self, "allowed_media_types", normalized)


@dataclass(frozen=True, slots=True)
class StatutorySourceCatalogProfile:
    """An explicit finite capture catalog with a deterministic integrity hash.

    A profile hash proves only equality of the supplied fields. It does not
    prove official origin, legal status, currentness, or policy activation.
    """

    profile_id: str
    version: str
    publisher_code: str
    enabled: bool
    allowed_hosts: frozenset[str]
    max_capture_age_seconds: int
    documents: tuple[StatutorySourceDocumentCaptureRule, ...]

    def __post_init__(self) -> None:
        """Require complete typed values, scoped hosts, and unique revisions."""

        _required_text(self.profile_id, field_name="profile_id", maximum=_MAX_PROFILE_TEXT)
        _required_text(self.version, field_name="version", maximum=_MAX_PROFILE_TEXT)
        _required_text(self.publisher_code, field_name="publisher_code", maximum=_MAX_PROFILE_TEXT)
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be an exact boolean")
        if type(self.allowed_hosts) is not frozenset or not self.allowed_hosts:
            raise ValueError("allowed_hosts must be a non-empty frozenset")
        hosts = frozenset(_validate_dns_hostname(host) for host in self.allowed_hosts)
        if type(self.max_capture_age_seconds) is not int or self.max_capture_age_seconds <= 0:
            raise ValueError("max_capture_age_seconds must be a positive exact integer")
        try:
            timedelta(seconds=self.max_capture_age_seconds)
        except (OverflowError, ValueError) as error:
            raise ValueError("max_capture_age_seconds exceeds timedelta capacity") from error
        if type(self.documents) is not tuple or not self.documents:
            raise ValueError("documents must be a non-empty tuple")

        identities: set[tuple[str, str, str]] = set()
        canonical_urls: set[str] = set()
        for rule in self.documents:
            if type(rule) is not StatutorySourceDocumentCaptureRule:
                raise ValueError("documents must contain exact capture rules")
            revision = rule.revision
            identity = revision.identity_key
            if identity in identities:
                raise ValueError("documents contain a duplicate native revision")
            identities.add(identity)
            if revision.canonical_url in canonical_urls:
                raise ValueError("documents contain a duplicate canonical URL")
            canonical_urls.add(revision.canonical_url)
            hostname = urlsplit(revision.canonical_url).hostname
            if hostname not in hosts:
                raise ValueError("document URL host does not match allowed_hosts")

    @property
    def content_sha256(self) -> str:
        """Hash all profile, allowlist, capture, and pinned revision fields."""

        payload: dict[str, object] = {
            "schema": "data_center.statutory_source_catalog.v1",
            "profile_id": self.profile_id,
            "version": self.version,
            "publisher_code": self.publisher_code,
            "enabled": self.enabled,
            "allowed_hosts": sorted(self.allowed_hosts),
            "max_capture_age_seconds": self.max_capture_age_seconds,
            "documents": [
                {
                    "revision": _revision_payload(rule.revision),
                    "max_bytes": rule.max_bytes,
                    "allowed_media_types": sorted(rule.allowed_media_types),
                }
                for rule in self.documents
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "StatutorySourceCatalogProfile",
    "StatutorySourceDocumentCaptureRule",
]
