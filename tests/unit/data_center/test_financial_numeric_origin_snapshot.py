"""Pure contracts for immutable capture-time configured-source origin snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_numeric_origin_snapshot import (
    FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA,
    FinancialNumericOriginProviderFacts,
    FinancialNumericOriginPublisherFacts,
    FinancialNumericSourceOriginSnapshot,
    _date_payload,
    origin_configuration_sha256,
    origin_snapshot_sha256,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceBodyReference,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_codec import (
    FinancialNumericOriginSnapshotCodecError,
    decode_origin_snapshot,
    encode_origin_snapshot,
)

_BASE = datetime(2026, 11, 16, 2, 0, 0, tzinfo=UTC)
_BODY = b"synthetic SZSE rule bytes for origin snapshot tests"
_BODY_SHA = hashlib.sha256(_BODY).hexdigest()
_URL = "https://www.szse.cn/lawrules/synthetic.pdf"


def _date(value: date) -> StatutorySourceDateEvidence:
    """Build exact date-precision evidence for a synthetic native revision."""

    return StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.DATE,
        date_value=value,
    )


def _revision(
    *,
    publication: StatutorySourceDateEvidence | None = None,
    effective: StatutorySourceDateEvidence | None = None,
) -> StatutorySourceDocumentRevision:
    """Build one source revision whose bytes are fixed by this synthetic test."""

    return StatutorySourceDocumentRevision(
        document_id="szse-test-rules-2026",
        source_version="2026-r1",
        canonical_url=_URL,
        issuer="SZSE",
        title="Synthetic exchange rules",
        legal_number="SZSE-TEST-2026",
        publication_date=publication or _date(date(2026, 11, 15)),
        effective_date=effective or _date(date(2026, 11, 16)),
        body_sha256=_BODY_SHA,
        body_size_bytes=len(_BODY),
    )


def _profile(
    *,
    revision: StatutorySourceDocumentRevision | None = None,
    max_age: int = 3600,
) -> StatutorySourceCatalogProfile:
    """Create a configured source-catalog profile without business defaults."""

    selected = revision or _revision()
    return StatutorySourceCatalogProfile(
        profile_id="szse-synthetic-profile",
        version="fixture-r1",
        publisher_code="SZSE",
        enabled=True,
        allowed_hosts=frozenset({"www.szse.cn"}),
        max_capture_age_seconds=max_age,
        documents=(
            StatutorySourceDocumentCaptureRule(
                revision=selected,
                max_bytes=len(_BODY) + 100,
                allowed_media_types=frozenset({"application/pdf"}),
            ),
        ),
    )


def _pair(
    *,
    profile: StatutorySourceCatalogProfile | None = None,
    provider_updated_at: datetime | None = None,
    publisher_updated_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> tuple[
    FinancialStatutorySourceIdentity,
    StatutorySourceCaptureReference,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceOriginSnapshot,
    str,
]:
    """Construct one exact same-response identity pair and origin snapshot."""

    selected_profile = profile or _profile()
    selected_revision = selected_profile.documents[0].revision
    capture_id = uuid4()
    captured_at = _BASE + timedelta(seconds=10)
    stat_recorded_at = _BASE + timedelta(seconds=12)
    numeric_recorded_at = recorded_at or (_BASE + timedelta(seconds=15))
    body_reference = StatutorySourceBodyReference(
        capture_id=capture_id,
        reference=f"statutory-source-body:///v1/{capture_id}.body",
        body_sha256=_BODY_SHA,
        body_size_bytes=len(_BODY),
    )
    statutory = StatutorySourceCaptureReference(
        issuer=selected_revision.issuer,
        document_id=selected_revision.document_id,
        source_version=selected_revision.source_version,
        title=selected_revision.title,
        legal_number=selected_revision.legal_number,
        source_revision_sha256=selected_revision.source_revision_sha256,
        capture_id=capture_id,
        capture_content_type="application/pdf",
        body_reference=body_reference.reference,
        canonical_url=selected_revision.canonical_url,
        body_sha256=_BODY_SHA,
        body_size_bytes=len(_BODY),
        publication_date=selected_revision.publication_date,
        source_effective_date=selected_revision.effective_date,
        first_seen_at=_BASE + timedelta(seconds=9),
        capture_observed_at=captured_at,
        revision_recorded_at=_BASE + timedelta(seconds=11),
        capture_recorded_at=stat_recorded_at,
    )
    identity = FinancialStatutorySourceIdentity(
        issuer=statutory.issuer,
        document_id=statutory.document_id,
        source_version=statutory.source_version,
        source_revision_sha256=statutory.source_revision_sha256,
        source_uri=statutory.canonical_url,
        body_reference=body_reference,
        first_seen_at=statutory.first_seen_at,
        revision_recorded_at=statutory.revision_recorded_at,
        capture_observed_at=statutory.capture_observed_at,
        recorded_at=statutory.capture_recorded_at,
    )
    numeric = FinancialNumericSourceDocumentCaptureReference(
        capture_id=capture_id,
        document_id=statutory.document_id,
        issuer=statutory.issuer,
        canonical_url=statutory.canonical_url,
        body_sha256=statutory.body_sha256,
        body_size_bytes=statutory.body_size_bytes,
        captured_at=statutory.capture_observed_at,
        content_type=statutory.capture_content_type,
    )
    provider = FinancialNumericOriginProviderFacts(
        provider_id=7,
        name="szse_public_docs",
        source_type="public_document",
        is_active=True,
        updated_at=provider_updated_at or (_BASE + timedelta(seconds=1)),
    )
    publisher = FinancialNumericOriginPublisherFacts(
        code="SZSE",
        canonical_name="深圳证券交易所",
        publisher_class="market_infrastructure",
        website="https://www.szse.cn/",
        is_active=True,
        updated_at=publisher_updated_at or (_BASE + timedelta(seconds=2)),
    )
    snapshot = FinancialNumericSourceOriginSnapshot(
        snapshot_id=capture_id,
        recorded_at=numeric_recorded_at,
        capture_reference=numeric,
        dataset_key="statutory_source_documents",
        deployment_region="qa",
        provider=provider,
        publisher=publisher,
        profile=selected_profile,
        selected_rule_index=0,
        configuration_sha256=origin_configuration_sha256(provider, publisher, selected_profile),
    )
    payload, digest = encode_origin_snapshot(snapshot)
    assert origin_snapshot_sha256(payload) == digest
    return identity, statutory, numeric, snapshot, digest


def test_snapshot_round_trips_full_profile_and_selected_configuration() -> None:
    identity, statutory, numeric, snapshot, digest = _pair()
    payload, encoded_digest = encode_origin_snapshot(snapshot)

    restored = decode_origin_snapshot(payload, digest)

    assert restored == snapshot
    assert encoded_digest == digest
    assert payload["schema"] == FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_SCHEMA
    assert payload["snapshot_id"] == str(numeric.capture_id) == str(statutory.capture_id)
    assert payload["profile_content_sha256"] == snapshot.profile.content_sha256
    assert payload["selected_rule_index"] == 0
    assert restored.profile.documents[0].revision.source_revision_sha256 == (
        identity.source_revision_sha256
    )
    assert "extra_config" not in payload
    assert "api_key" not in json.dumps(payload)


def test_configuration_fingerprint_matches_existing_service_selected_facts() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()
    provider = snapshot.provider
    publisher = snapshot.publisher
    profile = snapshot.profile
    expected_payload = {
        "provider_id": provider.provider_id,
        "provider_name": provider.name,
        "source_type": provider.source_type,
        "provider_active": provider.is_active,
        "provider_updated_at": provider.updated_at.isoformat(),
        "profile_sha256": profile.content_sha256,
        "publisher_code": publisher.code,
        "publisher_name": publisher.canonical_name,
        "publisher_class": publisher.publisher_class,
        "publisher_website": publisher.website,
        "publisher_active": publisher.is_active,
        "publisher_updated_at": publisher.updated_at.isoformat(),
    }
    expected = hashlib.sha256(
        json.dumps(
            expected_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    assert origin_configuration_sha256(provider, publisher, profile) == expected
    assert snapshot.configuration_sha256 == expected


def test_unknown_and_instant_native_dates_round_trip_without_coercion() -> None:
    revision = _revision(
        publication=StatutorySourceDateEvidence(StatutorySourceDatePrecision.UNKNOWN),
        effective=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=_BASE + timedelta(days=3),
        ),
    )
    profile = _profile(revision=revision)
    _identity, _statutory, _numeric, snapshot, digest = _pair(profile=profile)

    restored = decode_origin_snapshot(snapshot.to_payload(), digest)
    revision_payload = restored.profile.documents[0].revision

    assert revision_payload.publication_date.precision is StatutorySourceDatePrecision.UNKNOWN
    assert revision_payload.publication_date.date_value is None
    assert revision_payload.effective_date.precision is StatutorySourceDatePrecision.INSTANT
    assert revision_payload.effective_date.instant_value == _BASE + timedelta(days=3)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda payload: payload.update(unknown_field=True), "unknown fields"),
        (lambda payload: payload.pop("profile_content_sha256"), "fields"),
        (lambda payload: payload.update(schema="financial-v3-origin.v0"), "schema"),
        (lambda payload: payload.update(snapshot_id="not-a-uuid"), "UUID"),
        (lambda payload: payload.update(selected_rule_index=True), "integer"),
        (lambda payload: payload["provider"].update(is_active="true"), "boolean"),
    ],
)
def test_codec_rejects_malformed_shape_even_with_recomputed_outer_hash(mutate, error: str) -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()
    payload = snapshot.to_payload()
    mutate(payload)

    with pytest.raises(FinancialNumericOriginSnapshotCodecError, match=error):
        decode_origin_snapshot(payload, origin_snapshot_sha256(payload))


def test_codec_rejects_wrong_outer_hash_and_profile_hash() -> None:
    _identity, _statutory, _numeric, snapshot, digest = _pair()
    payload = snapshot.to_payload()

    with pytest.raises(FinancialNumericOriginSnapshotCodecError, match="digest"):
        decode_origin_snapshot(payload, "0" * 64)

    payload["profile_content_sha256"] = "0" * 64
    with pytest.raises(FinancialNumericOriginSnapshotCodecError, match="profile content digest"):
        decode_origin_snapshot(payload, origin_snapshot_sha256(payload))


def test_codec_rejects_profile_content_change_and_configuration_hash_change() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()
    payload = snapshot.to_payload()
    cast_profile = payload["profile"]
    assert type(cast_profile) is dict
    cast_profile["profile_id"] = "tampered-profile"

    with pytest.raises(FinancialNumericOriginSnapshotCodecError, match="Domain validation"):
        decode_origin_snapshot(payload, origin_snapshot_sha256(payload))

    payload = snapshot.to_payload()
    payload["configuration_sha256"] = "0" * 64
    with pytest.raises(FinancialNumericOriginSnapshotCodecError, match="Domain validation"):
        decode_origin_snapshot(payload, origin_snapshot_sha256(payload))


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot_id": uuid4()},
        {"dataset_key": ""},
        {"deployment_region": " "},
        {"selected_rule_index": True},
        {"recorded_at": _BASE - timedelta(seconds=1)},
        {"recorded_at": _BASE + timedelta(days=2)},
    ],
)
def test_snapshot_domain_rejects_invalid_identity_scope_and_clocks(
    changes: dict[str, object],
) -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()
    with pytest.raises((TypeError, ValueError)):
        replace(snapshot, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_id": 0},
        {"name": ""},
        {"source_type": "akshare"},
        {"is_active": False},
        {"updated_at": datetime(2026, 11, 16)},
    ],
)
def test_provider_facts_fail_closed(changes: dict[str, object]) -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()
    with pytest.raises((TypeError, ValueError)):
        replace(snapshot.provider, **changes)


def test_provider_and_publisher_facts_reject_non_utc_control_and_unencodable_text() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()

    with pytest.raises(ValueError, match="UTC"):
        replace(
            snapshot.provider,
            updated_at=_BASE.astimezone(timezone(timedelta(hours=8))),
        )
    with pytest.raises(ValueError, match="bounded text"):
        replace(snapshot.provider, name="bad\nprovider")
    with pytest.raises(UnicodeEncodeError):
        replace(snapshot.provider, name="\ud800")
    with pytest.raises(ValueError, match="active publisher"):
        replace(snapshot.publisher, is_active=False)


def test_configuration_fingerprint_rejects_untyped_inputs() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()

    with pytest.raises(TypeError, match="provider"):
        origin_configuration_sha256(None, snapshot.publisher, snapshot.profile)
    with pytest.raises(TypeError, match="publisher"):
        origin_configuration_sha256(snapshot.provider, None, snapshot.profile)
    with pytest.raises(TypeError, match="profile"):
        origin_configuration_sha256(snapshot.provider, snapshot.publisher, None)


@pytest.mark.parametrize(
    ("precision", "value"),
    [
        (StatutorySourceDatePrecision.DATE, datetime(2026, 1, 2, tzinfo=UTC)),
        (StatutorySourceDatePrecision.INSTANT, date(2026, 1, 2)),
    ],
)
def test_profile_date_serializer_rejects_precision_type_mismatch(precision, value) -> None:
    with pytest.raises(ValueError):
        _date_payload(precision, value)


def test_publisher_scope_rejects_wrong_origin_and_non_https() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()

    with pytest.raises(ValueError, match="outside publisher origin"):
        replace(snapshot.publisher, website="https://unrelated.invalid/").validate_profile_scope(
            snapshot.profile
        )
    with pytest.raises(ValueError, match="canonical HTTPS"):
        FinancialNumericOriginPublisherFacts(
            code="SZSE",
            canonical_name="Synthetic",
            publisher_class="market_infrastructure",
            website="http://www.szse.cn/",
            is_active=True,
            updated_at=_BASE,
        )
    with pytest.raises(ValueError, match="website is invalid"):
        FinancialNumericOriginPublisherFacts(
            code="SZSE",
            canonical_name="Synthetic",
            publisher_class="market_infrastructure",
            website="https://[invalid/",
            is_active=True,
            updated_at=_BASE,
        )
    with pytest.raises(ValueError, match="port differs"):
        replace(snapshot.publisher, website="https://www.szse.cn:8443/").validate_profile_scope(
            snapshot.profile
        )


def test_snapshot_rejects_wrong_types_disabled_profiles_and_changed_config_facts() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()

    with pytest.raises(TypeError, match="UUID"):
        replace(snapshot, snapshot_id="capture-id")
    with pytest.raises(TypeError, match="capture reference"):
        replace(snapshot, capture_reference=None)
    with pytest.raises(TypeError, match="provider facts"):
        replace(snapshot, provider=None)
    with pytest.raises(TypeError, match="publisher facts"):
        replace(snapshot, publisher=None)
    disabled_profile = replace(snapshot.profile, enabled=False)
    with pytest.raises(ValueError, match="enabled"):
        replace(
            snapshot,
            profile=disabled_profile,
            configuration_sha256=origin_configuration_sha256(
                snapshot.provider, snapshot.publisher, disabled_profile
            ),
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(snapshot, configuration_sha256="A" * 64)
    other_publisher = replace(snapshot.publisher, code="OTHER")
    with pytest.raises(ValueError, match="publisher code"):
        replace(
            snapshot,
            publisher=other_publisher,
            configuration_sha256=origin_configuration_sha256(
                snapshot.provider, other_publisher, snapshot.profile
            ),
        )


def test_snapshot_rejects_source_and_configuration_clocks_that_do_not_match() -> None:
    _identity, _statutory, _numeric, snapshot, _digest = _pair()

    mismatching_body = replace(snapshot.capture_reference, body_sha256="0" * 64)
    with pytest.raises(ValueError, match="selected profile revision"):
        replace(snapshot, capture_reference=mismatching_body)
    mismatching_mime = replace(snapshot.capture_reference, content_type="text/html")
    with pytest.raises(ValueError, match="selected profile revision"):
        replace(snapshot, capture_reference=mismatching_mime)
    late_provider = replace(
        snapshot.provider, updated_at=snapshot.recorded_at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="provider configuration update"):
        replace(
            snapshot,
            provider=late_provider,
            configuration_sha256=origin_configuration_sha256(
                late_provider, snapshot.publisher, snapshot.profile
            ),
        )
    late_publisher = replace(
        snapshot.publisher,
        updated_at=snapshot.recorded_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="publisher configuration update"):
        replace(
            snapshot,
            publisher=late_publisher,
            configuration_sha256=origin_configuration_sha256(
                snapshot.provider, late_publisher, snapshot.profile
            ),
        )
