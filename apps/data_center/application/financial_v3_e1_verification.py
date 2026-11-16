"""Typed use boundary for v3 date-only financial source-time verification.

This module is an isolated E1 candidate. Its verifier request is not an
authority token: trusted composition must supply the real qualified temporal
gate, retained body readers, and contextual numeric verifier.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.financial_numeric_qualification import (
    FinancialNumericVerificationPurpose,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    normalize_document_content_type,
)
from apps.data_center.domain.statutory_source_catalog import StatutorySourceCatalogProfile


def _utc(value: object, *, name: str) -> datetime:
    """Require an exact aware UTC timestamp without normalizing the evidence."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{name} must be an aware UTC datetime")
    try:
        offset = value.utcoffset()
        if offset != timedelta(0):
            raise ValueError(f"{name} must be an aware UTC datetime")
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be a representable UTC datetime") from error


@dataclass(frozen=True, slots=True)
class FinancialV3FactVerificationRequest:
    """Select one explicit current operation or historical PIT cutoff.

    Current cutoffs are acquired by the trusted gate after it has joined and
    locked the caller's current UOW. PIT callers provide their exact cutoff;
    that cutoff never replaces the v3 witness's original ``known_at``.
    """

    purpose: FinancialNumericVerificationPurpose
    known_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject implicit current clocks and implicit historical cutoffs."""

        if type(self.purpose) is not FinancialNumericVerificationPurpose:
            raise TypeError("purpose must be the exact financial verification purpose")
        if self.purpose is FinancialNumericVerificationPurpose.POINT_IN_TIME_READ:
            if self.known_at is None:
                raise ValueError("point-in-time financial reads require an explicit cutoff")
            object.__setattr__(self, "known_at", _utc(self.known_at, name="known_at"))
        elif self.known_at is not None:
            raise ValueError("current financial requests obtain their cutoff inside the UOW")


class FinancialV3FactEvidenceVerifier(Protocol):
    """Independently reverify v3 NOTICE, numeric, source, and temporal evidence."""

    def verify(
        self,
        fact: FinancialFact,
        request: FinancialV3FactVerificationRequest,
    ) -> bool:
        """Return true only after all exact body and qualified C2 checks pass."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialV3OfficialSourceProfileExpectation:
    """Reviewed exact existing profile identity supplied by trusted composition.

    This is a call configuration contract, not a new database authority. The
    composition root must supply the expected values from its reviewed source
    setup; copying values from the mutable catalog being checked defeats the
    independent comparison.
    """

    profile_id: str
    profile_version: str
    publisher_code: str
    publisher_class: str
    profile_content_sha256: str

    def __post_init__(self) -> None:
        """Require complete bounded publisher/profile identity and digest."""

        for name, value, maximum in (
            ("profile_id", self.profile_id, 128),
            ("profile_version", self.profile_version, 128),
            ("publisher_code", self.publisher_code, 40),
            ("publisher_class", self.publisher_class, 30),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} must be explicit bounded text")
        if type(self.profile_content_sha256) is not str or not _is_sha256(
            self.profile_content_sha256
        ):
            raise ValueError("profile_content_sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class FinancialV3OfficialSourceOriginSnapshot:
    """Immutable, non-authorizing capture-time publisher/profile observation.

    The DTO contains the exact fields selected by the existing public-document
    configuration fingerprint. It proves only that a particular configured
    profile/publisher snapshot accompanied the exact response capture; E1 must
    still verify the exact opening-rule source, full retained bundle and real
    capture audit. It is not a legal-status or Owner-approval token.
    """

    official_source: FinancialStatutorySourceIdentity
    statutory_capture: StatutorySourceCaptureReference
    numeric_capture: FinancialNumericSourceDocumentCaptureReference
    profile: StatutorySourceCatalogProfile
    selected_rule_index: int
    provider_id: int
    provider_name: str
    provider_source_type: str
    provider_active: bool
    provider_updated_at: datetime
    publisher_code: str
    publisher_name: str
    publisher_class: str
    publisher_website: str
    publisher_active: bool
    publisher_updated_at: datetime
    numeric_capture_success_audit_count: int
    configuration_sha256: str
    origin_snapshot_id: str
    origin_snapshot_version: str
    origin_snapshot_sha256: str
    origin_snapshot_recorded_at: datetime
    known_at: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Bind profile, selected config fingerprint, capture and cutoff clocks."""

        if type(self.official_source) is not FinancialStatutorySourceIdentity:
            raise TypeError("origin snapshot requires the exact statutory source identity")
        if type(self.statutory_capture) is not StatutorySourceCaptureReference:
            raise TypeError("origin snapshot requires the exact statutory capture")
        if type(self.numeric_capture) is not FinancialNumericSourceDocumentCaptureReference:
            raise TypeError("origin snapshot requires the exact numeric source capture")
        if type(self.profile) is not StatutorySourceCatalogProfile:
            raise TypeError("origin snapshot requires the exact decoded catalog profile")
        self.official_source.__post_init__()
        self.statutory_capture.__post_init__()
        self.numeric_capture.__post_init__()
        self.profile.__post_init__()
        _validate_origin_profile_rule(
            profile=self.profile,
            selected_rule_index=self.selected_rule_index,
            identity=self.official_source,
            capture=self.statutory_capture,
        )
        if (
            type(self.provider_id) is not int
            or self.provider_id <= 0
            or type(self.provider_active) is not bool
            or type(self.publisher_active) is not bool
            or type(self.numeric_capture_success_audit_count) is not int
            or self.numeric_capture_success_audit_count != 1
        ):
            raise ValueError("origin snapshot provider/publisher status is invalid")
        for name, value, maximum in (
            ("provider_name", self.provider_name, 160),
            ("provider_source_type", self.provider_source_type, 40),
            ("publisher_code", self.publisher_code, 40),
            ("publisher_name", self.publisher_name, 120),
            ("publisher_class", self.publisher_class, 30),
            ("publisher_website", self.publisher_website, 512),
            ("origin_snapshot_id", self.origin_snapshot_id, 64),
            ("origin_snapshot_version", self.origin_snapshot_version, 128),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} must be explicit bounded text")
        if (
            not self.provider_active
            or self.provider_source_type != PUBLIC_DOCUMENT_SOURCE_TYPE
            or not self.publisher_active
            or not self.profile.enabled
            or self.profile.publisher_code != self.publisher_code
        ):
            raise ValueError("origin snapshot must bind an enabled public publisher profile")
        for name, value in (
            ("configuration_sha256", self.configuration_sha256),
            ("origin_snapshot_sha256", self.origin_snapshot_sha256),
        ):
            if type(value) is not str or not _is_sha256(value):
                raise ValueError(f"{name} must be lowercase SHA-256")
        provider_updated_at = _utc(self.provider_updated_at, name="provider_updated_at")
        publisher_updated_at = _utc(self.publisher_updated_at, name="publisher_updated_at")
        recorded_at = _utc(
            self.origin_snapshot_recorded_at,
            name="origin snapshot recorded_at",
        )
        known_at = _utc(self.known_at, name="origin snapshot known_at")
        checked_at = _utc(self.checked_at, name="origin snapshot checked_at")
        if (
            self.origin_snapshot_id != str(self.numeric_capture.capture_id)
            or self.origin_snapshot_id != str(self.statutory_capture.capture_id)
            or self.origin_snapshot_version != "financial-v3-official-source-origin-snapshot.v1"
            or self.numeric_capture.document_id != self.statutory_capture.document_id
            or self.numeric_capture.issuer != self.statutory_capture.issuer
            or self.numeric_capture.canonical_url != self.statutory_capture.canonical_url
            or self.numeric_capture.body_sha256 != self.statutory_capture.body_sha256
            or self.numeric_capture.body_size_bytes != self.statutory_capture.body_size_bytes
            or self.numeric_capture.captured_at != self.statutory_capture.capture_observed_at
            or self.numeric_capture.content_type != self.statutory_capture.capture_content_type
            or recorded_at < self.numeric_capture.captured_at
            or recorded_at > known_at
            or checked_at < known_at
            or provider_updated_at > known_at
            or publisher_updated_at > known_at
            or not _official_identity_matches_capture(self.official_source, self.statutory_capture)
            or self.configuration_sha256
            != _configured_origin_fingerprint(
                provider_id=self.provider_id,
                provider_name=self.provider_name,
                provider_source_type=self.provider_source_type,
                provider_active=self.provider_active,
                provider_updated_at=self.provider_updated_at,
                profile_sha256=self.profile.content_sha256,
                publisher_code=self.publisher_code,
                publisher_name=self.publisher_name,
                publisher_class=self.publisher_class,
                publisher_website=self.publisher_website,
                publisher_active=self.publisher_active,
                publisher_updated_at=self.publisher_updated_at,
            )
        ):
            raise ValueError("origin snapshot differs from the exact captured source configuration")

    @property
    def reference_only(self) -> bool:
        """Keep configuration/body identity separate from decision qualification."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Require the exact source, Owner, temporal, and numeric gates to pass later."""

        return True


class FinancialV3OfficialSourceOriginSnapshotPort(Protocol):
    """Read immutable provider/publisher facts tied to the exact numeric capture."""

    @property
    def database_alias(self) -> str:
        """Return the source and numeric capture database alias."""
        ...

    def verify_current(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceOriginSnapshot:
        """Lock and compare current configuration with the immutable saved snapshot."""
        ...

    def verify_point_in_time(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceOriginSnapshot:
        """Read only the capture-time snapshot and audit facts visible at cutoff."""
        ...


@dataclass(frozen=True, slots=True)
class FinancialV3OfficialSourceQualificationObservation:
    """Configured publisher/profile readback for one exact statutory capture.

    This observation binds the source to the existing configured publisher,
    exact profile rule, immutable source capture, independent body rereads,
    and exact successful egress audits. It does not claim legal validity or
    policy approval; the C2 Owner event and opening-rule checks remain separate.
    """

    official_source: FinancialStatutorySourceIdentity
    statutory_capture: StatutorySourceCaptureReference
    profile_id: str
    profile_version: str
    publisher_code: str
    publisher_class: str
    profile_content_sha256: str
    configuration_sha256: str
    verification_mode: Literal["current_exact_capture", "point_in_time_exact_capture"]
    statutory_capture_success_audit_count: int
    numeric_capture_success_audit_count: int
    origin_snapshot_id: str
    origin_snapshot_version: str
    origin_snapshot_sha256: str
    origin_snapshot_recorded_at: datetime
    known_at: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Require one exact identity, configured profile, and completed readback."""

        if type(self.official_source) is not FinancialStatutorySourceIdentity:
            raise TypeError("official source observation requires the exact statutory identity")
        if type(self.statutory_capture) is not StatutorySourceCaptureReference:
            raise TypeError("official source observation requires the exact native capture")
        self.official_source.__post_init__()
        self.statutory_capture.__post_init__()
        for name, value, maximum in (
            ("profile_id", self.profile_id, 128),
            ("profile_version", self.profile_version, 128),
            ("publisher_code", self.publisher_code, 128),
            ("publisher_class", self.publisher_class, 30),
            ("origin_snapshot_id", self.origin_snapshot_id, 64),
            ("origin_snapshot_version", self.origin_snapshot_version, 128),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} must be explicit bounded text")
        for name, value in (
            ("profile_content_sha256", self.profile_content_sha256),
            ("configuration_sha256", self.configuration_sha256),
        ):
            if type(value) is not str or not _is_sha256(value):
                raise ValueError(f"{name} must be lowercase SHA-256")
        known_at = _utc(self.known_at, name="official source known_at")
        checked_at = _utc(self.checked_at, name="official source checked_at")
        snapshot_recorded_at = _utc(
            self.origin_snapshot_recorded_at,
            name="official source origin snapshot recorded_at",
        )
        if (
            self.origin_snapshot_id != str(self.statutory_capture.capture_id)
            or self.origin_snapshot_version != "financial-v3-official-source-origin-snapshot.v1"
            or type(self.origin_snapshot_sha256) is not str
            or not _is_sha256(self.origin_snapshot_sha256)
            or snapshot_recorded_at > known_at
        ):
            raise ValueError("official source origin snapshot is invalid at the explicit cutoff")
        if checked_at < known_at:
            raise ValueError("official source check predates its explicit cutoff")
        if self.verification_mode not in {
            "current_exact_capture",
            "point_in_time_exact_capture",
        }:
            raise ValueError("official source verification mode is unsupported")
        if (
            type(self.statutory_capture_success_audit_count) is not int
            or self.statutory_capture_success_audit_count != 1
            or type(self.numeric_capture_success_audit_count) is not int
            or self.numeric_capture_success_audit_count != 1
        ):
            raise ValueError("official source requires one success audit per exact capture")
        if not _official_identity_matches_capture(self.official_source, self.statutory_capture):
            raise ValueError("official source identity differs from the exact native capture")

    @property
    def reference_only(self) -> bool:
        """Keep configured origin, bytes, and audit separate from legal status."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Require the separate C2 rule and Owner approval checks."""

        return True


class FinancialV3OfficialSourceQualificationPort(Protocol):
    """Verify an exact source capture against existing publisher/profile storage."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by the configured provider/publisher repositories."""

    def verify_current(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        source_read: FinancialAvailabilitySourceRead,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceQualificationObservation:
        """Read current configured-origin evidence in the caller's current UOW."""
        ...

    @property
    def profile_expectation(self) -> FinancialV3OfficialSourceProfileExpectation:
        """Return the independently supplied reviewed profile identity."""
        ...

    def verify_point_in_time(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        source_read: FinancialAvailabilitySourceRead,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceQualificationObservation:
        """Read historical configured-origin evidence at an explicit cutoff."""
        ...


def _official_identity_matches_capture(
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
) -> bool:
    """Compare every source/capture fact available in the typed identity pair."""

    body = identity.body_reference
    return (
        identity.issuer == capture.issuer
        and identity.document_id == capture.document_id
        and identity.source_version == capture.source_version
        and identity.source_revision_sha256 == capture.source_revision_sha256
        and identity.source_uri == capture.canonical_url
        and body.capture_id == capture.capture_id
        and body.reference == capture.body_reference
        and body.body_sha256 == capture.body_sha256
        and body.body_size_bytes == capture.body_size_bytes
        and identity.first_seen_at == capture.first_seen_at
        and identity.revision_recorded_at == capture.revision_recorded_at
        and identity.capture_observed_at == capture.capture_observed_at
        and identity.recorded_at == capture.capture_recorded_at
    )


def _configured_origin_fingerprint(
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
    """Recompute the exact existing configured-origin fingerprint payload."""

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


def _validate_origin_profile_rule(
    *,
    profile: StatutorySourceCatalogProfile,
    selected_rule_index: int,
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
) -> None:
    """Recheck indexed profile rule, raw source fields, MIME and byte bounds."""

    if type(selected_rule_index) is not int or not (
        0 <= selected_rule_index < len(profile.documents)
    ):
        raise ValueError("origin snapshot selected rule index is invalid")
    selected = profile.documents[selected_rule_index]
    revision = selected.revision
    matches = tuple(
        rule
        for rule in profile.documents
        if rule.revision.identity_key
        == (identity.issuer, identity.document_id, identity.source_version)
    )
    try:
        content_type = normalize_document_content_type(capture.capture_content_type)
    except ValueError as error:
        raise ValueError("origin snapshot capture MIME is invalid") from error
    if (
        len(matches) != 1
        or matches[0] != selected
        or revision.identity_key != (identity.issuer, identity.document_id, identity.source_version)
        or revision.source_revision_sha256 != identity.source_revision_sha256
        or revision.canonical_url != identity.source_uri
        or revision.body_sha256 != identity.body_sha256
        or revision.body_size_bytes != identity.body_size_bytes
        or revision.issuer != capture.issuer
        or revision.document_id != capture.document_id
        or revision.source_version != capture.source_version
        or revision.title != capture.title
        or revision.legal_number != capture.legal_number
        or revision.publication_date != capture.publication_date
        or revision.effective_date != capture.source_effective_date
        or capture.body_size_bytes > selected.max_bytes
        or content_type not in selected.allowed_media_types
    ):
        raise ValueError("origin snapshot profile rule differs from the exact retained source")


def _is_sha256(value: str) -> bool:
    """Return whether text is one lowercase SHA-256 digest."""

    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "FinancialV3FactEvidenceVerifier",
    "FinancialV3FactVerificationRequest",
    "FinancialV3OfficialSourceOriginSnapshot",
    "FinancialV3OfficialSourceOriginSnapshotPort",
    "FinancialV3OfficialSourceQualificationObservation",
    "FinancialV3OfficialSourceQualificationPort",
    "FinancialV3OfficialSourceProfileExpectation",
]
