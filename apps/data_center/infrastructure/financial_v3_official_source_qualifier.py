"""Verify exact configured official-source capture, snapshot and audit evidence.

This infrastructure adapter does not create or imply legal status. The exact
dual-capture adapter separately compares statutory and numeric response bytes;
this adapter qualifies the selected source revision against its existing
publisher/profile configuration and capture-time snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3OfficialSourceOriginSnapshot,
    FinancialV3OfficialSourceOriginSnapshotPort,
    FinancialV3OfficialSourceProfileExpectation,
    FinancialV3OfficialSourceQualificationObservation,
    FinancialV3OfficialSourceQualificationPort,
)
from apps.data_center.application.statutory_source_catalog import (
    decode_statutory_source_catalog_profile,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    normalize_document_content_type,
)
from apps.data_center.domain.statutory_source_catalog import StatutorySourceCatalogProfile
from apps.data_center.infrastructure.egress_models import EgressRequestAuditModel
from apps.data_center.infrastructure.financial_v3_current_uow import (
    require_financial_v3_caller_owned_uow,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.statutory_source_capture_composition import _publisher_scope
from core.exceptions import DataValidationError

_CATALOG_CONFIG_KEY = "statutory_source_catalog"
_STATUTORY_DOCUMENT_DATASET = "statutory_source_documents"


class FinancialV3ConfiguredOfficialSourceQualifier(FinancialV3OfficialSourceQualificationPort):
    """Join exact source profile, capture-time snapshot, bytes and audits.

    Current verification locks ProviderConfig and PublisherCatalog rows inside
    the caller's one default-alias PostgreSQL READ COMMITTED UOW. PIT uses only
    the immutable origin snapshot and exact historical source/audit reads at
    the supplied cutoff; it never falls back to current configuration.
    """

    def __init__(
        self,
        *,
        origin_snapshots: FinancialV3OfficialSourceOriginSnapshotPort,
        profile_expectation: FinancialV3OfficialSourceProfileExpectation,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind the snapshot reader and independently reviewed profile to one alias."""

        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 official-source qualification requires the default database alias")
        if type(profile_expectation) is not FinancialV3OfficialSourceProfileExpectation:
            raise TypeError("E1 official-source qualification requires a reviewed profile")
        profile_expectation.__post_init__()
        alias = origin_snapshots.database_alias
        if type(alias) is not str or alias != using:
            raise ValueError("origin snapshot reader must use the default database alias")
        self._origin_snapshots = origin_snapshots
        self._profile_expectation = profile_expectation
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias shared by all exact source and capture readers."""

        return self._using

    @property
    def profile_expectation(self) -> FinancialV3OfficialSourceProfileExpectation:
        """Return the independently supplied reviewed profile identity."""

        return self._profile_expectation

    def verify_current(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        source_read: FinancialAvailabilitySourceRead,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceQualificationObservation:
        """Require exact live configuration, source bytes and one success audit."""

        require_financial_v3_caller_owned_uow(using=self._using)
        snapshot = self._origin_snapshots.verify_current(
            official_source,
            statutory_capture,
            known_at=known_at,
        )
        _validate_origin_snapshot(
            snapshot,
            identity=official_source,
            capture=statutory_capture,
            known_at=known_at,
            expectation=self._profile_expectation,
        )
        _validate_source_read(
            source_read,
            identity=official_source,
            capture=statutory_capture,
            known_at=known_at,
        )
        profile = self._read_locked_current_profile(snapshot)
        if (
            profile != snapshot.profile
            or profile.content_sha256 != self._profile_expectation.profile_content_sha256
        ):
            raise _blocked(
                "Live configured source profile differs from the reviewed capture-time snapshot.",
                "FINANCIAL_V3_OFFICIAL_PROFILE_CHANGED",
            )
        _exact_profile_rule(profile, identity=official_source, capture=statutory_capture)

        audit_cutoff = _database_clock(self._using)
        _require_source_success_audit(
            capture=statutory_capture,
            provider_id=snapshot.provider_id,
            upper_bound=audit_cutoff,
            lock_rows=True,
            using=self._using,
        )
        checked_at = _database_clock(self._using)
        if checked_at < max(known_at, snapshot.checked_at, source_read.checked_at, audit_cutoff):
            raise _blocked(
                "Official-source verification clock predates a locked source read.",
                "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
            )
        return _observation(
            snapshot=snapshot,
            capture=statutory_capture,
            profile=profile,
            known_at=known_at,
            checked_at=checked_at,
            verification_mode="current_exact_capture",
            statutory_audit_count=1,
        )

    def verify_point_in_time(
        self,
        official_source: FinancialStatutorySourceIdentity,
        statutory_capture: StatutorySourceCaptureReference,
        source_read: FinancialAvailabilitySourceRead,
        *,
        known_at: datetime,
    ) -> FinancialV3OfficialSourceQualificationObservation:
        """Replay archived profile, exact source bytes and audits at the cutoff."""

        snapshot = self._origin_snapshots.verify_point_in_time(
            official_source,
            statutory_capture,
            known_at=known_at,
        )
        _validate_origin_snapshot(
            snapshot,
            identity=official_source,
            capture=statutory_capture,
            known_at=known_at,
            expectation=self._profile_expectation,
        )
        _validate_source_read(
            source_read,
            identity=official_source,
            capture=statutory_capture,
            known_at=known_at,
        )
        profile = snapshot.profile
        _exact_profile_rule(profile, identity=official_source, capture=statutory_capture)
        _require_source_success_audit(
            capture=statutory_capture,
            provider_id=snapshot.provider_id,
            upper_bound=known_at,
            lock_rows=False,
            using=self._using,
        )
        checked_at = _database_clock(self._using)
        if checked_at < max(known_at, snapshot.checked_at, source_read.checked_at):
            raise _blocked(
                "Historical official-source readback clock is earlier than its evidence.",
                "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
            )
        return _observation(
            snapshot=snapshot,
            capture=statutory_capture,
            profile=profile,
            known_at=known_at,
            checked_at=checked_at,
            verification_mode="point_in_time_exact_capture",
            statutory_audit_count=1,
        )

    def _read_locked_current_profile(
        self,
        snapshot: FinancialV3OfficialSourceOriginSnapshot,
    ) -> StatutorySourceCatalogProfile:
        """Read and lock the exact configured provider and publisher in the outer UOW."""

        provider = (
            ProviderConfigModel._default_manager.using(self._using)
            .select_for_update()
            .filter(pk=snapshot.provider_id)
            .first()
        )
        if (
            provider is None
            or type(provider.pk) is not int
            or provider.pk != snapshot.provider_id
            or not provider.is_active
            or provider.source_type != PUBLIC_DOCUMENT_SOURCE_TYPE
            or provider.http_url
            or provider.api_endpoint
        ):
            raise _blocked(
                "The exact active public-document provider is unavailable or overridden.",
                "FINANCIAL_V3_OFFICIAL_PROVIDER_CHANGED",
            )
        raw: object = provider.extra_config
        if type(raw) is not dict or _CATALOG_CONFIG_KEY not in raw:
            raise _blocked(
                "The exact active provider has no explicit source catalog.",
                "FINANCIAL_V3_OFFICIAL_PROFILE_MISSING",
            )
        try:
            profile = decode_statutory_source_catalog_profile(raw[_CATALOG_CONFIG_KEY])
        except (DataValidationError, TypeError, ValueError) as error:
            raise _blocked(
                "The current configured source profile is malformed.",
                "FINANCIAL_V3_OFFICIAL_PROFILE_INVALID",
            ) from error
        if not profile.enabled:
            raise _blocked(
                "The exact configured source profile is disabled.",
                "FINANCIAL_V3_OFFICIAL_PROFILE_DISABLED",
            )
        publisher = (
            PublisherCatalogModel._default_manager.using(self._using)
            .select_for_update()
            .filter(code=profile.publisher_code)
            .first()
        )
        if publisher is None or not publisher.is_active:
            raise _blocked(
                "The exact configured active publisher is unavailable.",
                "FINANCIAL_V3_OFFICIAL_PUBLISHER_UNAVAILABLE",
            )
        try:
            _publisher_scope(profile, publisher)
        except (DataValidationError, TypeError, ValueError) as error:
            raise _blocked(
                "The configured source profile no longer matches its publisher origin.",
                "FINANCIAL_V3_OFFICIAL_PUBLISHER_SCOPE_INVALID",
            ) from error
        current_fingerprint = _configured_origin_fingerprint(
            provider_id=provider.pk,
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
        if (
            provider.name != snapshot.provider_name
            or provider.source_type != snapshot.provider_source_type
            or provider.is_active is not snapshot.provider_active
            or provider.updated_at != snapshot.provider_updated_at
            or publisher.code != snapshot.publisher_code
            or publisher.canonical_name != snapshot.publisher_name
            or publisher.publisher_class != snapshot.publisher_class
            or publisher.website != snapshot.publisher_website
            or publisher.is_active is not snapshot.publisher_active
            or publisher.updated_at != snapshot.publisher_updated_at
            or current_fingerprint != snapshot.configuration_sha256
        ):
            raise _blocked(
                "Live provider or publisher facts differ from the immutable origin snapshot.",
                "FINANCIAL_V3_OFFICIAL_PROFILE_CHANGED",
            )
        return profile


def _validate_origin_snapshot(
    snapshot: FinancialV3OfficialSourceOriginSnapshot,
    *,
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
    known_at: datetime,
    expectation: FinancialV3OfficialSourceProfileExpectation,
) -> None:
    """Bind the immutable numeric-capture snapshot to the reviewed exact source."""

    if type(snapshot) is not FinancialV3OfficialSourceOriginSnapshot:
        raise _blocked(
            "Origin snapshot reader returned an untyped result.",
            "FINANCIAL_V3_OFFICIAL_ORIGIN_SNAPSHOT_INVALID",
        )
    try:
        snapshot.__post_init__()
    except (TypeError, ValueError) as error:
        raise _blocked(
            "Origin snapshot failed exact capture, configuration or clock validation.",
            "FINANCIAL_V3_OFFICIAL_ORIGIN_SNAPSHOT_INVALID",
        ) from error
    if (
        snapshot.official_source != identity
        or snapshot.statutory_capture != capture
        or snapshot.known_at != known_at
        or snapshot.profile.profile_id != expectation.profile_id
        or snapshot.profile.version != expectation.profile_version
        or snapshot.profile.publisher_code != expectation.publisher_code
        or snapshot.profile.content_sha256 != expectation.profile_content_sha256
        or snapshot.publisher_class != expectation.publisher_class
        or snapshot.reference_only is not True
        or snapshot.must_not_use_for_decision is not True
    ):
        raise _blocked(
            "Origin snapshot differs from the exact reviewed source/profile identity.",
            "FINANCIAL_V3_OFFICIAL_ORIGIN_SNAPSHOT_MISMATCH",
        )
    publisher_snapshot = PublisherCatalogModel(
        code=snapshot.publisher_code,
        canonical_name=snapshot.publisher_name,
        publisher_class=snapshot.publisher_class,
        website=snapshot.publisher_website,
        is_active=snapshot.publisher_active,
    )
    try:
        _publisher_scope(snapshot.profile, publisher_snapshot)
    except (DataValidationError, TypeError, ValueError) as error:
        raise _blocked(
            "Origin snapshot profile does not remain within its captured publisher origin.",
            "FINANCIAL_V3_OFFICIAL_PUBLISHER_SCOPE_INVALID",
        ) from error


def _validate_source_read(
    source_read: FinancialAvailabilitySourceRead,
    *,
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
    known_at: datetime,
) -> None:
    """Require the exact C2 source row/body read at the unchanged cutoff."""

    if type(source_read) is not FinancialAvailabilitySourceRead:
        raise _blocked(
            "C2 source reader returned an untyped statutory body.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_BODY_INVALID",
        )
    try:
        source_read.__post_init__()
    except (TypeError, ValueError) as error:
        raise _blocked(
            "C2 source body bytes or clocks failed exact readback validation.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_BODY_INVALID",
        ) from error
    if (
        source_read.reference != capture
        or source_read.known_at != known_at
        or identity.capture_id != capture.capture_id
        or identity.body_reference.reference != capture.body_reference
        or identity.body_sha256 != capture.body_sha256
        or identity.body_size_bytes != capture.body_size_bytes
        or len(source_read.body) != capture.body_size_bytes
    ):
        raise _blocked(
            "C2 source body is not the exact approved capture at its original cutoff.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_BODY_MISMATCH",
        )


def _exact_profile_rule(
    profile: StatutorySourceCatalogProfile,
    *,
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
) -> None:
    """Require one exact profile rule for the selected immutable source revision."""

    matches = tuple(
        rule
        for rule in profile.documents
        if rule.revision.identity_key
        == (identity.issuer, identity.document_id, identity.source_version)
    )
    if len(matches) != 1:
        raise _blocked(
            "Configured source profile does not contain one exact native rule.",
            "FINANCIAL_V3_OFFICIAL_PROFILE_RULE_MISMATCH",
        )
    selected = matches[0]
    revision = selected.revision
    try:
        content_type = normalize_document_content_type(capture.capture_content_type)
    except ValueError as error:
        raise _blocked(
            "Exact source capture has an invalid content type.",
            "FINANCIAL_V3_OFFICIAL_PROFILE_RULE_MISMATCH",
        ) from error
    if (
        revision.source_revision_sha256 != identity.source_revision_sha256
        or revision.canonical_url != identity.source_uri
        or revision.body_sha256 != identity.body_sha256
        or revision.body_size_bytes != identity.body_size_bytes
        or revision.identity_key != (capture.issuer, capture.document_id, capture.source_version)
        or revision.title != capture.title
        or revision.legal_number != capture.legal_number
        or revision.publication_date != capture.publication_date
        or revision.effective_date != capture.source_effective_date
        or capture.body_size_bytes > selected.max_bytes
        or content_type not in selected.allowed_media_types
    ):
        raise _blocked(
            "Configured profile revision differs from the exact approved source capture.",
            "FINANCIAL_V3_OFFICIAL_PROFILE_RULE_MISMATCH",
        )


def _require_source_success_audit(
    *,
    capture: StatutorySourceCaptureReference,
    provider_id: int,
    upper_bound: datetime,
    lock_rows: bool,
    using: str,
) -> None:
    """Require exactly one persisted successful source-capture egress audit."""

    host = urlsplit(capture.canonical_url).hostname
    if type(host) is not str or not host:
        raise _blocked(
            "Exact source capture has no canonical audit host.",
            "FINANCIAL_V3_OFFICIAL_CAPTURE_AUDIT_UNAVAILABLE",
        )
    audits = EgressRequestAuditModel._default_manager.using(using)
    if lock_rows:
        audits = audits.select_for_update()
    rows = tuple(
        audits.filter(
            request_id=capture.capture_id,
            provider_id=provider_id,
            dataset_key=_STATUTORY_DOCUMENT_DATASET,
            target_host=host,
            outcome="success",
            created_at__gte=capture.capture_observed_at,
            created_at__lte=upper_bound,
        ).order_by("pk")[:2]
    )
    if len(rows) != 1:
        raise _blocked(
            "Exact successful statutory capture audit is missing or ambiguous at this cutoff.",
            "FINANCIAL_V3_OFFICIAL_CAPTURE_AUDIT_UNAVAILABLE",
        )
    audit = rows[0]
    if (
        audit.request_id != capture.capture_id
        or audit.provider_id != provider_id
        or audit.dataset_key != _STATUTORY_DOCUMENT_DATASET
        or audit.target_host != host
        or audit.outcome != "success"
        or audit.created_at < capture.capture_observed_at
        or audit.created_at > upper_bound
    ):
        raise _blocked(
            "Statutory capture audit differs from the exact source selector or cutoff.",
            "FINANCIAL_V3_OFFICIAL_CAPTURE_AUDIT_UNAVAILABLE",
        )


def _observation(
    *,
    snapshot: FinancialV3OfficialSourceOriginSnapshot,
    capture: StatutorySourceCaptureReference,
    profile: StatutorySourceCatalogProfile,
    known_at: datetime,
    checked_at: datetime,
    verification_mode: Literal["current_exact_capture", "point_in_time_exact_capture"],
    statutory_audit_count: int,
) -> FinancialV3OfficialSourceQualificationObservation:
    """Create a reference-only result after exact source, snapshot and audit checks."""

    return FinancialV3OfficialSourceQualificationObservation(
        official_source=snapshot.official_source,
        statutory_capture=capture,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        publisher_code=profile.publisher_code,
        publisher_class=snapshot.publisher_class,
        profile_content_sha256=profile.content_sha256,
        configuration_sha256=snapshot.configuration_sha256,
        verification_mode=verification_mode,
        statutory_capture_success_audit_count=statutory_audit_count,
        numeric_capture_success_audit_count=snapshot.numeric_capture_success_audit_count,
        origin_snapshot_id=snapshot.origin_snapshot_id,
        origin_snapshot_version=snapshot.origin_snapshot_version,
        origin_snapshot_sha256=snapshot.origin_snapshot_sha256,
        origin_snapshot_recorded_at=snapshot.origin_snapshot_recorded_at,
        known_at=known_at,
        checked_at=checked_at,
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
    """Recompute the existing twelve-fact provider/profile/publisher fingerprint."""

    return _origin_fingerprint(
        {
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
    )


def _origin_fingerprint(payload: dict[str, object]) -> str:
    """Hash the existing configuration payload with its exact canonical JSON form."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _database_clock(using: str) -> datetime:
    """Sample PostgreSQL time after the current profile/audit reads."""

    connection = connections[using]
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
    except DatabaseError as error:
        raise _blocked(
            "Cannot sample the official-source verification clock.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
        ) from error
    if row is None or len(row) != 1 or type(row[0]) is not datetime:
        raise _blocked(
            "Official-source verification clock is missing or untyped.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
        )
    value = row[0]
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise _blocked(
            "Official-source verification clock is not explicit UTC.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
        )
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise _blocked(
            "Official-source verification clock is outside UTC range.",
            "FINANCIAL_V3_OFFICIAL_SOURCE_CLOCK_INVALID",
        ) from error


def _blocked(message: str, code: str) -> DataValidationError:
    """Return a stable fail-closed error without exposing mutable configuration."""

    return DataValidationError(message, code=code)


__all__ = ["FinancialV3ConfiguredOfficialSourceQualifier"]
