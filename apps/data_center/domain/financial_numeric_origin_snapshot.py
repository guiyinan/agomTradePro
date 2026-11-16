"""Typed immutable capture-time snapshots of configured statutory source origin.

This candidate records only the already-configured provider/catalog selection
visible while a numeric document capture is appended. It does not prove legal
status, Owner approval, a statutory bundle, or financial decision eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    normalize_document_content_type,
)
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)

FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA = "financial-v3-official-source-origin-snapshot.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: object, *, field_name: str) -> datetime:
    """Require an exact aware UTC timestamp and preserve its represented instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be an aware UTC datetime")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} is outside the representable UTC range") from error


def _text(value: object, *, field_name: str, maximum: int) -> str:
    """Require non-empty bounded text without control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be non-empty bounded text")
    value.encode("utf-8")
    return value


def _date_payload(
    precision: StatutorySourceDatePrecision, value: date | datetime | None
) -> dict[str, object]:
    """Serialize one native source date without inventing missing precision."""

    if precision is StatutorySourceDatePrecision.UNKNOWN:
        return {"precision": precision.value, "value": None}
    if precision is StatutorySourceDatePrecision.DATE:
        if type(value) is not date:
            raise ValueError("date precision requires an exact date")
        return {"precision": precision.value, "value": value.isoformat()}
    if type(value) is not datetime:
        raise ValueError("instant precision requires an exact datetime")
    _utc(value, field_name="source instant")
    return {"precision": precision.value, "value": value.isoformat()}


def _revision_payload(revision: StatutorySourceDocumentRevision) -> dict[str, object]:
    """Serialize every native revision field accepted by the existing catalog codec."""

    return {
        "document_id": revision.document_id,
        "source_version": revision.source_version,
        "canonical_url": revision.canonical_url,
        "issuer": revision.issuer,
        "title": revision.title,
        "legal_number": revision.legal_number,
        "publication_date": _date_payload(
            revision.publication_date.precision,
            (
                revision.publication_date.date_value
                if revision.publication_date.precision is StatutorySourceDatePrecision.DATE
                else revision.publication_date.instant_value
            ),
        ),
        "effective_date": _date_payload(
            revision.effective_date.precision,
            (
                revision.effective_date.date_value
                if revision.effective_date.precision is StatutorySourceDatePrecision.DATE
                else revision.effective_date.instant_value
            ),
        ),
        "body_sha256": revision.body_sha256,
        "body_size_bytes": revision.body_size_bytes,
    }


def _profile_payload(profile: StatutorySourceCatalogProfile) -> dict[str, object]:
    """Serialize only the validated source-catalog subtree, excluding provider secrets."""

    return {
        "schema_version": "data_center.statutory_source_catalog.v1",
        "profile_id": profile.profile_id,
        "version": profile.version,
        "publisher_code": profile.publisher_code,
        "enabled": profile.enabled,
        "allowed_hosts": sorted(profile.allowed_hosts),
        "max_capture_age_seconds": profile.max_capture_age_seconds,
        "documents": [
            {
                "revision": _revision_payload(rule.revision),
                "max_bytes": rule.max_bytes,
                "allowed_media_types": sorted(rule.allowed_media_types),
            }
            for rule in profile.documents
        ],
    }


def _configuration_sha256(
    *,
    provider_id: int,
    provider_name: str,
    provider_source_type: str,
    provider_active: bool,
    provider_updated_at: datetime,
    profile_sha256: str,
    publisher_code: str,
    publisher_name: str,
    publisher_class: str,
    publisher_website: str,
    publisher_active: bool,
    publisher_updated_at: datetime,
) -> str:
    """Match the existing configured-source service's selected-facts fingerprint."""

    payload: dict[str, object] = {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "source_type": provider_source_type,
        "provider_active": provider_active,
        "provider_updated_at": provider_updated_at.isoformat(),
        "profile_sha256": profile_sha256,
        "publisher_code": publisher_code,
        "publisher_name": publisher_name,
        "publisher_class": publisher_class,
        "publisher_website": publisher_website,
        "publisher_active": publisher_active,
        "publisher_updated_at": publisher_updated_at.isoformat(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def origin_configuration_sha256(
    provider: FinancialNumericOriginProviderFacts,
    publisher: FinancialNumericOriginPublisherFacts,
    profile: StatutorySourceCatalogProfile,
) -> str:
    """Fingerprint the configured-source service's exact selected facts."""

    if type(provider) is not FinancialNumericOriginProviderFacts:
        raise TypeError("provider must use the exact origin-snapshot provider type")
    if type(publisher) is not FinancialNumericOriginPublisherFacts:
        raise TypeError("publisher must use the exact origin-snapshot publisher type")
    if type(profile) is not StatutorySourceCatalogProfile:
        raise TypeError("profile must use the exact statutory catalog Domain type")
    return _configuration_sha256(
        provider_id=provider.provider_id,
        provider_name=provider.name,
        provider_source_type=provider.source_type,
        provider_active=provider.is_active,
        provider_updated_at=provider.updated_at,
        profile_sha256=profile.content_sha256,
        publisher_code=publisher.code,
        publisher_name=publisher.canonical_name,
        publisher_class=publisher.publisher_class,
        publisher_website=publisher.website,
        publisher_active=publisher.is_active,
        publisher_updated_at=publisher.updated_at,
    )


@dataclass(frozen=True, slots=True)
class FinancialNumericOriginProviderFacts:
    """Exact non-secret provider facts selected when a document was recorded."""

    provider_id: int
    name: str
    source_type: str
    is_active: bool
    updated_at: datetime

    def __post_init__(self) -> None:
        """Require one active public-document provider and its recorded update clock."""

        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise ValueError("provider_id must be a positive exact integer")
        _text(self.name, field_name="provider name", maximum=100)
        if self.source_type != PUBLIC_DOCUMENT_SOURCE_TYPE:
            raise ValueError("origin snapshots require the public-document provider type")
        if type(self.is_active) is not bool or not self.is_active:
            raise ValueError("origin snapshots require an active provider at capture time")
        _utc(self.updated_at, field_name="provider updated_at")


@dataclass(frozen=True, slots=True)
class FinancialNumericOriginPublisherFacts:
    """Exact non-secret publisher-catalog facts used for origin scoping."""

    code: str
    canonical_name: str
    publisher_class: str
    website: str
    is_active: bool
    updated_at: datetime

    def __post_init__(self) -> None:
        """Require a bounded active publisher with a canonical HTTPS origin."""

        _text(self.code, field_name="publisher code", maximum=40)
        _text(self.canonical_name, field_name="publisher name", maximum=120)
        _text(self.publisher_class, field_name="publisher class", maximum=30)
        _text(self.website, field_name="publisher website", maximum=2048)
        if type(self.is_active) is not bool or not self.is_active:
            raise ValueError("origin snapshots require an active publisher at capture time")
        _utc(self.updated_at, field_name="publisher updated_at")
        self._validate_profile_origin_hosts(frozenset())

    def _validate_profile_origin_hosts(self, hosts: frozenset[str]) -> None:
        """Validate publisher website URL shape and optional profile-host containment."""

        try:
            parsed = urlsplit(self.website)
            root = parsed.hostname
            port = 443 if parsed.port is None else parsed.port
        except ValueError as error:
            raise ValueError("publisher website is invalid") from error
        if (
            parsed.scheme != "https"
            or not root
            or not root.isascii()
            or root != root.lower()
            or root.endswith(".")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port <= 0
            or any(character.isspace() for character in self.website)
        ):
            raise ValueError("publisher website must be an explicit canonical HTTPS origin")
        if any(host != root and not host.endswith(f".{root}") for host in hosts):
            raise ValueError("configured source host lies outside publisher origin")

    def validate_profile_scope(self, profile: StatutorySourceCatalogProfile) -> None:
        """Require every profile host and URL port to remain inside this publisher origin."""

        self._validate_profile_origin_hosts(profile.allowed_hosts)
        parsed = urlsplit(self.website)
        origin_port = 443 if parsed.port is None else parsed.port
        for rule in profile.documents:
            source_port = urlsplit(rule.revision.canonical_url).port or 443
            if source_port != origin_port:
                raise ValueError("source URL port differs from the publisher origin")


@dataclass(frozen=True, slots=True)
class FinancialNumericSourceOriginSnapshot:
    """Validated capture-time provider, publisher, and native-profile snapshot.

    ``snapshot_id`` reuses the exact numeric capture UUID; it does not allocate
    an independent authority or event. ``recorded_at`` is exactly the
    immutable capture row's server record clock.
    """

    snapshot_id: UUID
    recorded_at: datetime
    capture_reference: FinancialNumericSourceDocumentCaptureReference
    dataset_key: str
    deployment_region: str
    provider: FinancialNumericOriginProviderFacts
    publisher: FinancialNumericOriginPublisherFacts
    profile: StatutorySourceCatalogProfile
    selected_rule_index: int
    configuration_sha256: str

    def __post_init__(self) -> None:
        """Bind the snapshot to one exact capture and matching configured revision."""

        if type(self.snapshot_id) is not UUID:
            raise TypeError("snapshot_id must be an exact UUID")
        if type(self.capture_reference) is not FinancialNumericSourceDocumentCaptureReference:
            raise TypeError("capture_reference must be an exact numeric capture reference")
        self.capture_reference.__post_init__()
        if self.snapshot_id != self.capture_reference.capture_id:
            raise ValueError("snapshot ID must reuse the exact capture UUID")
        recorded_at = _utc(self.recorded_at, field_name="origin snapshot recorded_at")
        if recorded_at < _utc(self.capture_reference.captured_at, field_name="capture time"):
            raise ValueError("origin snapshot record predates its response capture")
        _text(self.dataset_key, field_name="dataset key", maximum=120)
        _text(self.deployment_region, field_name="deployment region", maximum=40)
        if type(self.provider) is not FinancialNumericOriginProviderFacts:
            raise TypeError("provider facts must use the exact origin-snapshot type")
        if type(self.publisher) is not FinancialNumericOriginPublisherFacts:
            raise TypeError("publisher facts must use the exact origin-snapshot type")
        if type(self.profile) is not StatutorySourceCatalogProfile or not self.profile.enabled:
            raise ValueError("an enabled validated statutory source profile is required")
        if type(self.selected_rule_index) is not int or not (
            0 <= self.selected_rule_index < len(self.profile.documents)
        ):
            raise ValueError("selected_rule_index must identify one profile rule")
        if (
            type(self.configuration_sha256) is not str
            or _SHA256.fullmatch(self.configuration_sha256) is None
        ):
            raise ValueError("configuration_sha256 must be lowercase SHA-256")
        if self.profile.publisher_code != self.publisher.code:
            raise ValueError("profile publisher code differs from the captured publisher")
        self.publisher.validate_profile_scope(self.profile)
        rule = self.selected_rule
        revision = rule.revision
        capture = self.capture_reference
        if (
            revision.issuer != capture.issuer
            or revision.document_id != capture.document_id
            or revision.canonical_url != capture.canonical_url
            or revision.body_sha256 != capture.body_sha256
            or revision.body_size_bytes != capture.body_size_bytes
            or capture.body_size_bytes > rule.max_bytes
            or normalize_document_content_type(capture.content_type) not in rule.allowed_media_types
        ):
            raise ValueError("selected profile revision differs from the exact captured document")
        if _utc(self.provider.updated_at, field_name="provider updated_at") > recorded_at:
            raise ValueError("provider configuration update postdates the origin snapshot")
        if _utc(self.publisher.updated_at, field_name="publisher updated_at") > recorded_at:
            raise ValueError("publisher configuration update postdates the origin snapshot")
        if recorded_at - _utc(capture.captured_at, field_name="capture time") > timedelta(
            seconds=self.profile.max_capture_age_seconds
        ):
            raise ValueError("capture lies outside the profile's original observation window")
        expected = origin_configuration_sha256(self.provider, self.publisher, self.profile)
        if expected != self.configuration_sha256:
            raise ValueError("configuration fingerprint differs from captured selected facts")

    @property
    def schema_version(self) -> str:
        """Return this immutable payload's explicit schema discriminator."""

        return FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA

    @property
    def selected_rule(self) -> StatutorySourceDocumentCaptureRule:
        """Return the exact selected rule from the full validated profile."""

        return self.profile.documents[self.selected_rule_index]

    @property
    def profile_content_sha256(self) -> str:
        """Return the deterministic hash of the complete validated profile."""

        return self.profile.content_sha256

    def to_payload(self) -> dict[str, object]:
        """Return all validated, non-secret origin facts in a strict JSON shape."""

        self.__post_init__()
        return {
            "schema": self.schema_version,
            "snapshot_id": str(self.snapshot_id),
            "recorded_at": self.recorded_at.isoformat(),
            "numeric_capture": {
                "reference": self.capture_reference.to_dict(),
                "dataset_key": self.dataset_key,
                "deployment_region": self.deployment_region,
            },
            "provider": {
                "provider_id": self.provider.provider_id,
                "name": self.provider.name,
                "source_type": self.provider.source_type,
                "is_active": self.provider.is_active,
                "updated_at": self.provider.updated_at.isoformat(),
            },
            "publisher": {
                "code": self.publisher.code,
                "canonical_name": self.publisher.canonical_name,
                "publisher_class": self.publisher.publisher_class,
                "website": self.publisher.website,
                "is_active": self.publisher.is_active,
                "updated_at": self.publisher.updated_at.isoformat(),
            },
            "profile": _profile_payload(self.profile),
            "profile_content_sha256": self.profile_content_sha256,
            "selected_rule_index": self.selected_rule_index,
            "configuration_sha256": self.configuration_sha256,
        }


def origin_snapshot_sha256(payload: dict[str, object]) -> str:
    """Hash one already-validated, non-secret snapshot payload canonically."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA",
    "FinancialNumericOriginPublisherFacts",
    "FinancialNumericOriginProviderFacts",
    "FinancialNumericSourceOriginSnapshot",
    "origin_configuration_sha256",
    "origin_snapshot_sha256",
]
