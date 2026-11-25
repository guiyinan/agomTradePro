"""Lightweight, database-free contract tests for the v3 source-time witness."""

from __future__ import annotations

from dataclasses import MISSING, replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_next_session_availability import (
    FinancialNextSessionAvailability,
    resolve_financial_next_session_availability,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialApprovalIdentity,
    FinancialDisclosureAvailabilityPolicy,
    FinancialNativeRowBinding,
    FinancialNextSessionGovernanceBinding,
    FinancialNextSessionSourceTimeWitnessV3,
    FinancialOfficialSourceIdentity,
    financial_disclosure_availability_policy_sha256,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    KNOWN_AT as CALENDAR_KNOWN_AT,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    _calendar as _calendar_fixture,
)
from tests.unit.data_center.test_financial_next_session_availability import (
    _opening_rule as _opening_rule_fixture,
)

ASSET = "000001.SZ"
PERIOD_END = date(2026, 6, 30)
NOTICE_DATE = date(2026, 11, 16)
KNOWN_AT = CALENDAR_KNOWN_AT + timedelta(minutes=2)


def _witness() -> object:
    """Build one future-open example from the existing pure calendar fixture."""

    calendar_record, pointer = _calendar_fixture(
        start=NOTICE_DATE,
        end=NOTICE_DATE + timedelta(days=2),
        open_dates=(NOTICE_DATE + timedelta(days=1), NOTICE_DATE + timedelta(days=2)),
        ttl_seconds=600,
    )
    opening_rule = _opening_rule_fixture()
    availability = resolve_financial_next_session_availability(
        source_date=NOTICE_DATE,
        known_at=KNOWN_AT,
        calendar_record=calendar_record,
        calendar_pointer=pointer,
        opening_rule=opening_rule,
    )
    assert type(availability) is FinancialNextSessionAvailability

    evidence = FinancialResponseEvidence(
        body_sha256="a" * 64,
        body_size_bytes=2048,
        response_completed_at=CALENDAR_KNOWN_AT + timedelta(minutes=1),
        request_scope=FinancialRequestScope(
            provider_name="akshare",
            dataset_key="equity.financial.fact",
            asset_code=ASSET,
            period_limit=1,
        ),
        response_scope=FinancialResponseScope(
            asset_codes=(ASSET,),
            period_ends=(PERIOD_END,),
            row_count=1,
        ),
        body_scope=FinancialResponseBodyScope.RECORD,
        response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
    )
    artifact_reference = FinancialResponseArtifactRef(
        capture_id=uuid4(),
        location="encrypted://financial/fact-response/001",
        evidence=evidence,
        format_version="response-artifact.v1",
        encryption_algorithm="AES-256-GCM",
        encryption_key_ref="secret-manager://data-artifacts/key",
        encryption_key_version="v3",
    )
    row = FinancialNativeRowBinding(
        artifact_reference=artifact_reference,
        asset_code=ASSET,
        period_end=PERIOD_END,
        period_type=FinancialPeriodType.SEMI_ANNUAL,
        metric_code="net_profit",
        native_row_id="provider-row:001",
        notice_date=NOTICE_DATE,
        row_projection_sha256="c" * 64,
        matched_row_count=1,
    )

    policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id="financial-disclosure-availability-szse-v1",
        policy_version="v1",
        exchange=opening_rule.exchange,
        opening_phase=opening_rule.phase,
        effective_start=date(2026, 1, 1),
        effective_end=date(2027, 12, 31),
        calendar_response_max_age_seconds=600,
        first_seen_at=KNOWN_AT - timedelta(minutes=10),
        recorded_at=KNOWN_AT - timedelta(minutes=9),
    )
    official_source = FinancialOfficialSourceIdentity(
        document_record_id="statutory-document:szse-rules-2026",
        capture_id=uuid4(),
        source_uri=opening_rule.source_uri,
        body_sha256=opening_rule.source_body_sha256,
        body_size_bytes=500_000,
        artifact_location="encrypted://statutory/szse/trading-rules-2026.pdf",
        format_version="source-artifact.v1",
        encryption_algorithm="AES-256-GCM",
        encryption_key_ref="secret-manager://data-artifacts/key",
        encryption_key_version="v3",
        first_seen_at=opening_rule.first_seen_at,
        recorded_at=opening_rule.recorded_at,
    )
    rule_approval = FinancialApprovalIdentity(
        subject_record_id="opening-rule-record:szse-v1",
        subject_sha256=opening_rule.rule_sha256,
        event_id="owner-approval-event:rule-1",
        event_sha256="d" * 64,
        principal_id="owner-user:1",
        approved_at=opening_rule.approved_at,
        recorded_at=opening_rule.approved_at + timedelta(seconds=1),
    )
    policy_approval = FinancialApprovalIdentity(
        subject_record_id=policy.policy_id,
        subject_sha256=policy.policy_sha256,
        event_id="owner-approval-event:policy-1",
        event_sha256="e" * 64,
        principal_id="owner-user:1",
        approved_at=policy.recorded_at + timedelta(minutes=1),
        recorded_at=policy.recorded_at + timedelta(minutes=1, seconds=1),
    )
    governance = FinancialNextSessionGovernanceBinding(
        opening_rule_record_id="opening-rule-record:szse-v1",
        official_source=official_source,
        opening_rule_approval=rule_approval,
        policy=policy,
        policy_approval=policy_approval,
    )
    return FinancialNextSessionSourceTimeWitnessV3.from_resolved_availability(
        financial_row=row,
        availability=availability,
        governance=governance,
    )


def test_witness_rejects_notice_date_that_does_not_match_resolver_input() -> None:
    witness = _witness()
    changed_row = replace(witness.financial_row, notice_date=NOTICE_DATE + timedelta(days=1))
    with pytest.raises(ValueError, match="NOTICE_DATE"):
        replace(witness, financial_row=changed_row)


def test_calendar_reference_preserves_half_open_supersession_at_resolution() -> None:
    calendar = _witness().availability.calendar
    superseded_at = calendar.known_at + timedelta(minutes=1)
    expected_valid_until = min(
        calendar.snapshot_first_seen_at + timedelta(seconds=calendar.response_max_age_seconds),
        superseded_at,
    )
    historical_input = replace(
        calendar,
        lifecycle_at_resolution=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at_at_resolution=superseded_at,
        valid_until_at_resolution=expected_valid_until,
    )
    assert historical_input.known_at < historical_input.valid_until_at_resolution

    with pytest.raises(ValueError, match="current and fresh"):
        replace(
            historical_input,
            superseded_at_at_resolution=historical_input.known_at,
            valid_until_at_resolution=historical_input.known_at,
        )


def test_explicit_phase_and_ttl_have_no_implicit_values() -> None:
    policy_fields = FinancialDisclosureAvailabilityPolicy.__dataclass_fields__
    for field_name in ("opening_phase", "calendar_response_max_age_seconds"):
        assert policy_fields[field_name].default is MISSING
        assert policy_fields[field_name].default_factory is MISSING


def test_financial_row_binding_rejects_incomplete_or_mismatched_source_scope() -> None:
    witness = _witness()
    row = witness.financial_row
    with pytest.raises(ValueError, match="typed artifact"):
        replace(row, artifact_reference=object())
    with pytest.raises(ValueError, match="period_type"):
        replace(row, period_type="semi_annual")
    with pytest.raises(ValueError, match="row_projection_sha256"):
        replace(row, row_projection_sha256="not-a-hash")
    with pytest.raises(ValueError, match="exactly one"):
        replace(row, matched_row_count=True)

    request = replace(row.artifact_reference.evidence.request_scope, dataset_key="other.dataset")
    bad_evidence = replace(row.artifact_reference.evidence, request_scope=request)
    bad_artifact = replace(row.artifact_reference, evidence=bad_evidence)
    with pytest.raises(ValueError, match="dataset"):
        replace(row, artifact_reference=bad_artifact)

    caller_declared = replace(
        row.artifact_reference.evidence,
        response_scope_basis=FinancialResponseScopeBasis.CALLER_DECLARED,
    )
    with pytest.raises(ValueError, match="body-verified"):
        replace(row, artifact_reference=replace(row.artifact_reference, evidence=caller_declared))

    with pytest.raises(ValueError, match="asset differs"):
        replace(row, asset_code="600000.SH")
    with pytest.raises(ValueError, match="coverage"):
        replace(row, period_end=date(2026, 12, 31))


def test_calendar_reference_rejects_invalid_identity_window_and_knowledge_edges() -> None:
    calendar = _witness().availability.calendar
    with pytest.raises(ValueError, match="canonical UUID"):
        replace(calendar, publication_id="not-a-uuid")
    with pytest.raises(ValueError, match="publication_hash"):
        replace(calendar, publication_hash="bad")
    with pytest.raises(ValueError, match="unsupported"):
        replace(calendar, lifecycle_at_resolution=CalendarPublicationLifecycle.ROLLED_BACK)
    with pytest.raises(ValueError, match="snapshot reference"):
        replace(calendar, snapshot_reference=object())
    with pytest.raises(ValueError, match="publication key"):
        replace(calendar, publication_key="calendar:other")
    with pytest.raises(ValueError, match="snapshot exchange"):
        replace(calendar, snapshot_reference=replace(calendar.snapshot_reference, exchange="SSE"))
    with pytest.raises(ValueError, match="aware UTC"):
        replace(calendar, pointer_updated_at=datetime(2026, 11, 16))
    with pytest.raises(ValueError, match="response max age"):
        replace(calendar, response_max_age_seconds=0)
    with pytest.raises(ValueError, match="superseded_at"):
        replace(calendar, superseded_at_at_resolution=calendar.published_at)

    with pytest.raises(ValueError, match="expiry exceeds"):
        replace(
            calendar,
            snapshot_first_seen_at=datetime.max.replace(tzinfo=UTC),
            snapshot_recorded_at=datetime.max.replace(tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="exact response TTL"):
        replace(
            calendar,
            valid_until_at_resolution=calendar.valid_until_at_resolution - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="current and fresh"):
        replace(calendar, known_at=calendar.valid_until_at_resolution)
    with pytest.raises(ValueError, match="pointer was updated"):
        replace(calendar, pointer_updated_at=calendar.known_at + timedelta(seconds=1))


def test_availability_reference_rechecks_phase_rule_timezone_and_temporal_projection() -> None:
    availability = _witness().availability
    with pytest.raises(ValueError, match="strictly follow"):
        replace(availability, next_session=availability.source_date)
    with pytest.raises(ValueError, match="aware UTC"):
        replace(availability, available_at=datetime(2026, 11, 17, 1, 15))
    with pytest.raises(TypeError, match="exact calendar"):
        replace(availability, calendar=object())
    with pytest.raises(TypeError, match="opening rule"):
        replace(availability, opening_rule=object())
    with pytest.raises(ValueError, match="as-of identities"):
        replace(availability, known_at=availability.known_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="exceed exact calendar coverage"):
        replace(availability, next_session=date(2028, 1, 1))

    ineffective_rule = _opening_rule_fixture(effective_end=NOTICE_DATE)
    with pytest.raises(ValueError, match="effective dates"):
        replace(availability, opening_rule=ineffective_rule)

    unknown_rule = _opening_rule_fixture(
        first_seen_at=KNOWN_AT + timedelta(seconds=1),
        recorded_at=KNOWN_AT + timedelta(seconds=2),
        approved_at=KNOWN_AT + timedelta(seconds=3),
    )
    with pytest.raises(ValueError, match="postdates"):
        replace(availability, opening_rule=unknown_rule)
    with pytest.raises(ValueError, match="explicit opening rule"):
        replace(availability, available_at=availability.available_at + timedelta(minutes=1))

    spring_start = date(2026, 3, 7)
    snapshot = replace(
        availability.calendar.snapshot_reference,
        coverage_start=spring_start,
        coverage_end=spring_start + timedelta(days=2),
    )
    calendar = replace(availability.calendar, snapshot_reference=snapshot)
    dst_rule = _opening_rule_fixture(
        timezone_name="America/New_York",
        local_open_time=time(2, 30),
        effective_start=date(2026, 1, 1),
        effective_end=date(2026, 12, 31),
    )
    with pytest.raises(ValueError, match="nonexistent or ambiguous"):
        replace(
            availability,
            source_date=spring_start,
            next_session=date(2026, 3, 8),
            available_at=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            calendar=calendar,
            opening_rule=dst_rule,
        )


def test_governance_types_reject_non_source_approval_or_future_claims() -> None:
    witness = _witness()
    gov = witness.governance
    with pytest.raises(ValueError, match="canonical text"):
        replace(gov, opening_rule_record_id=" padded ")
    with pytest.raises(ValueError, match="approval references"):
        replace(
            gov,
            opening_rule_approval=replace(
                gov.opening_rule_approval,
                subject_record_id="another-record",
            ),
        )
    with pytest.raises(ValueError, match="exact policy content"):
        replace(
            gov,
            policy_approval=replace(gov.policy_approval, subject_sha256="f" * 64),
        )
    with pytest.raises(ValueError, match="predates policy recording"):
        replace(
            gov,
            policy_approval=replace(
                gov.policy_approval,
                approved_at=gov.policy.recorded_at - timedelta(seconds=1),
                recorded_at=gov.policy.recorded_at,
            ),
        )

    future_approval = replace(
        gov.opening_rule_approval,
        recorded_at=KNOWN_AT + timedelta(seconds=1),
    )
    future_source_governance = replace(gov, opening_rule_approval=future_approval)
    with pytest.raises(ValueError, match="not known"):
        future_source_governance.validate_for(
            opening_rule=witness.availability.opening_rule,
            calendar=witness.availability.calendar,
            next_session=witness.availability.next_session,
            known_at=KNOWN_AT,
        )

    changed_policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id=gov.policy.policy_id,
        policy_version=gov.policy.policy_version,
        exchange="SSE",
        opening_phase=gov.policy.opening_phase,
        effective_start=gov.policy.effective_start,
        effective_end=gov.policy.effective_end,
        calendar_response_max_age_seconds=gov.policy.calendar_response_max_age_seconds,
        first_seen_at=gov.policy.first_seen_at,
        recorded_at=gov.policy.recorded_at,
    )
    changed_policy_governance = replace(
        gov,
        policy=changed_policy,
        policy_approval=replace(
            gov.policy_approval,
            subject_sha256=changed_policy.policy_sha256,
        ),
    )
    with pytest.raises(ValueError, match="scope, phase, or TTL"):
        replace(witness, governance=changed_policy_governance)


def test_policy_and_original_identity_types_reject_invalid_source_shapes() -> None:
    witness = _witness()
    policy = witness.governance.policy
    with pytest.raises(ValueError, match="bounded token"):
        replace(policy, policy_version="bad version")
    with pytest.raises(ValueError, match="explicit and typed"):
        replace(policy, opening_phase="opening_call_auction")
    with pytest.raises(ValueError, match="range is inverted"):
        FinancialDisclosureAvailabilityPolicy.create(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            exchange=policy.exchange,
            opening_phase=policy.opening_phase,
            effective_start=date(2027, 1, 1),
            effective_end=date(2026, 1, 1),
            calendar_response_max_age_seconds=policy.calendar_response_max_age_seconds,
            first_seen_at=policy.first_seen_at,
            recorded_at=policy.recorded_at,
        )
    with pytest.raises(ValueError, match="TTL must be explicit"):
        replace(policy, calendar_response_max_age_seconds=0)
    with pytest.raises(ValueError, match="aware UTC"):
        replace(policy, first_seen_at=datetime(2026, 11, 15))
    with pytest.raises(ValueError, match="knowledge times"):
        replace(policy, first_seen_at=policy.recorded_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="policy hash"):
        replace(policy, policy_sha256="0" * 64)
    with pytest.raises(ValueError, match="payload keys"):
        financial_disclosure_availability_policy_sha256({"unexpected": "value"})
    with pytest.raises(ValueError, match="TTL must be an integer"):
        financial_disclosure_availability_policy_sha256(
            {
                **policy._payload(),
                "calendar_response_max_age_seconds": True,
            }
        )

    source = witness.governance.official_source
    with pytest.raises(ValueError, match="capture_id"):
        replace(source, capture_id="not-a-uuid")
    with pytest.raises(ValueError, match="body_sha256"):
        replace(source, body_sha256="bad")
    with pytest.raises(ValueError, match="body_size_bytes"):
        replace(source, body_size_bytes=0)
    with pytest.raises(ValueError, match="knowledge times"):
        replace(source, first_seen_at=source.recorded_at + timedelta(seconds=1))


def test_approval_identity_rejects_bad_hashes_and_time_order() -> None:
    approval = _witness().governance.policy_approval
    with pytest.raises(ValueError, match="canonical text"):
        replace(approval, event_id=" padded ")
    with pytest.raises(ValueError, match="hashes"):
        replace(approval, event_sha256="not-a-hash")
    with pytest.raises(ValueError, match="aware UTC"):
        replace(approval, approved_at=datetime(2026, 11, 15))
    with pytest.raises(ValueError, match="recording precedes"):
        replace(approval, recorded_at=approval.approved_at - timedelta(seconds=1))


def test_v3_domain_checks_exact_runtime_types_and_time_cutoffs() -> None:
    witness = _witness()
    with pytest.raises(TypeError, match="exact financial row"):
        replace(witness, financial_row=object())
    with pytest.raises(TypeError, match="availability reference"):
        replace(witness, availability=object())
    with pytest.raises(TypeError, match="governance references"):
        replace(witness, governance=object())
    with pytest.raises(ValueError, match="aware UTC"):
        witness.is_temporally_available_at(datetime(2026, 11, 17, 1, 15))
    assert (
        witness.is_temporally_available_at(witness.available_at - timedelta(microseconds=1))
        is False
    )


def test_strict_scalar_validators_reject_controls_dates_and_uuids() -> None:
    witness = _witness()
    with pytest.raises(ValueError, match="control characters"):
        replace(witness.governance.policy, policy_id="policy\nidentifier")
    with pytest.raises(ValueError, match="date without a time"):
        replace(witness.financial_row, notice_date=datetime(2026, 11, 16, tzinfo=UTC))
    with pytest.raises(ValueError, match="canonical UUID"):
        replace(witness.availability.calendar, publication_id="ABC")
