"""Qualified v3 E1 source-time and numeric evidence replay candidate.

The verifier independently reopens each fact's own retained financial
response. Main NOTICE uses the shared Main-body contract; Balance NOTICE uses
the Balance body's exact parser projection. The C2 temporal composition below
combines reference-only C2 results with actual Owner/source/calendar rereads
and the dual statutory/document capture adapter. No child reference-only
result is accepted as a qualification on its own.

This module is isolated preparation. It creates no database authority and is
not active until the candidate dependencies are reviewed and integrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, DatabaseError, transaction

from apps.data_center.application.financial_availability_current import (
    CurrentFinancialNextSessionTemporalCheck,
    _verify_approval,
    _verify_original_calendar_reference,
    validate_current_financial_next_session_temporal_binding,
)
from apps.data_center.application.financial_availability_governance import (
    FinancialAvailabilityGovernanceReadResult,
    read_financial_availability_governance,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
    GetFinancialAvailabilityGovernanceQuery,
)
from apps.data_center.application.financial_numeric_qualification import (
    ContextualFinancialNumericEvidenceVerifier,
    FinancialNumericVerificationContext,
    FinancialNumericVerificationPurpose,
)
from apps.data_center.application.financial_v3_e1_verification import (
    FinancialV3FactVerificationRequest,
    FinancialV3OfficialSourceProfileExpectation,
    FinancialV3OfficialSourceQualificationObservation,
    FinancialV3OfficialSourceQualificationPort,
)
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.exchange_calendar import next_exchange_calendar_session
from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_e1_capture_contract import (
    FinancialSharedResponseSourceTimeContractV2,
    FinancialSharedResponseSourceTimeReferenceV2,
    match_shared_main_notice_date_v2,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningRule,
    _opening_clock_utc,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_source_evidence import (
    FINANCIAL_FACT_DATASET_KEY,
)
from apps.data_center.domain.financial_statutory_capture_binding import (
    FinancialStatutoryCaptureBinding,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.financial_availability_e1_composition import (
    _read_historical_calendar,
    validate_financial_next_session_witness_current,
)
from apps.data_center.infrastructure.financial_native_numeric_verifier import (
    FinancialNativeRawBodyReader,
)
from apps.data_center.infrastructure.financial_next_session_witness_codec import (
    encode_financial_next_session_witness_v3,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_raw_boundary import (
    BalanceCandidateContract,
    BalanceCandidateRequest,
    build_balance_candidate_query,
    parse_balance_candidate_body,
)
from apps.data_center.infrastructure.financial_numeric_qualification.balance_verifier import (
    AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT,
    BalanceNumericEndpointRouteResolver,
    BalanceNumericOriginalBodyReader,
    _balance_native_row_id,
    _same_exact_mapping,
)
from apps.data_center.infrastructure.financial_source_time_matchers import (
    AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT,
    AKSHARE_PROVIDER_NAME,
)
from apps.data_center.infrastructure.financial_v3_current_uow import (
    require_financial_v3_caller_owned_uow,
)
from core.exceptions import DataFetchError, DataValidationError


class FinancialV3TemporalGateBlocked(DataValidationError):
    """Raised when exact qualified C2/source-time revalidation is unavailable."""

    default_message = "Date-only financial source-time qualification is unavailable."
    default_code = "FINANCIAL_V3_TEMPORAL_QUALIFICATION_BLOCKED"


class FinancialV3StatutoryCapturePort(Protocol):
    """Read the exact official-source and 0116 document bytes at an as-of time."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by statutory and numeric capture stores."""

    def read_as_of(
        self,
        official_source: FinancialStatutorySourceIdentity,
        *,
        known_at: datetime,
    ) -> FinancialStatutoryCaptureBinding:
        """Recheck both exact retained bodies and their persisted clocks at cutoff."""

    def read_current(
        self,
        official_source: FinancialStatutorySourceIdentity,
        *,
        known_at: datetime,
    ) -> FinancialStatutoryCaptureBinding:
        """Lock and recheck both bodies inside the caller's current RC UOW."""


@dataclass(frozen=True, slots=True)
class FinancialV3TemporalGateResolution:
    """Call-local result emitted only after all required C2/source checks pass.

    This value is never persisted and does not replace an Owner row, Audit,
    source identity, or publication record. It binds the exact witness digest,
    selected operation purpose/cutoff, and dual-capture identity to this call.
    """

    witness_sha256: str
    purpose: FinancialNumericVerificationPurpose
    known_at: datetime
    official_source_revision_sha256: str
    statutory_capture_id: UUID
    numeric_document_capture_id: UUID
    official_profile_id: str
    official_profile_version: str
    official_publisher_code: str
    official_publisher_class: str
    official_profile_content_sha256: str
    official_configuration_sha256: str
    verification_mode: Literal["current_exact_capture", "point_in_time_exact_capture"]
    statutory_capture_success_audit_count: int
    numeric_capture_success_audit_count: int
    origin_snapshot_id: str
    origin_snapshot_version: str
    origin_snapshot_sha256: str
    origin_snapshot_recorded_at: datetime

    def __post_init__(self) -> None:
        """Require the exact dual-capture and temporal operation identity."""

        if not _is_sha256(self.witness_sha256) or not _is_sha256(
            self.official_source_revision_sha256
        ):
            raise ValueError("temporal-gate digests must be exact lowercase SHA-256")
        if type(self.purpose) is not FinancialNumericVerificationPurpose:
            raise TypeError("temporal-gate purpose must be typed")
        _require_utc(self.known_at, "temporal gate known_at")
        if (
            type(self.statutory_capture_id) is not UUID
            or type(self.numeric_document_capture_id) is not UUID
        ):
            raise TypeError("temporal gate requires both exact capture UUIDs")
        for name, value, maximum in (
            ("official_profile_id", self.official_profile_id, 128),
            ("official_profile_version", self.official_profile_version, 128),
            ("official_publisher_code", self.official_publisher_code, 40),
            ("official_publisher_class", self.official_publisher_class, 30),
            ("origin_snapshot_id", self.origin_snapshot_id, 64),
            ("origin_snapshot_version", self.origin_snapshot_version, 128),
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} is invalid")
        if not _is_sha256(self.official_profile_content_sha256) or not _is_sha256(
            self.official_configuration_sha256
        ):
            raise ValueError("official source configuration digests are invalid")
        if not _is_sha256(self.origin_snapshot_sha256):
            raise ValueError("official source origin snapshot digest is invalid")
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
            raise ValueError("official source success audit evidence is incomplete")
        _require_utc(self.origin_snapshot_recorded_at, "origin snapshot recorded_at")
        if self.origin_snapshot_recorded_at > self.known_at:
            raise ValueError("origin snapshot was recorded after the exact operation cutoff")
        if self.origin_snapshot_id != str(self.statutory_capture_id):
            raise ValueError("origin snapshot does not bind the exact statutory capture")


class FinancialV3QualifiedTemporalGatePort(Protocol):
    """Require the full qualified C2 current or original-cutoff revalidation."""

    def resolve_current_in_uow(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        purpose: FinancialNumericVerificationPurpose,
    ) -> FinancialV3TemporalGateResolution:
        """Resolve qualified source time while retaining caller-owned current locks."""

    def resolve_point_in_time(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        known_at: datetime,
    ) -> FinancialV3TemporalGateResolution:
        """Resolve C2 source, Owner, and calendar facts at the witness's original cutoff."""


class FinancialV3QualifiedTemporalGate:
    """Compose real C2, calendar, Owner, statutory, and 0116 capture rereads.

    The current branch joins the caller's one default-alias PostgreSQL READ
    COMMITTED UOW and keeps all locks through its outer commit. PIT uses the
    witness's original ``known_at`` for C2/source/calendar reads and leaves
    later revocations outside that historical view. The requested PIT cutoff
    separately must be at or after the witness's earliest temporal usability.
    """

    def __init__(
        self,
        *,
        records: FinancialAvailabilityGovernanceRepositoryPort,
        owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
        source_reader: FinancialAvailabilitySourceReaderPort,
        statutory_capture: FinancialV3StatutoryCapturePort,
        official_source_qualifier: FinancialV3OfficialSourceQualificationPort,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind all current and historical evidence readers to one exact alias."""

        aliases = (
            records.database_alias,
            owner_events.database_alias,
            source_reader.database_alias,
            statutory_capture.database_alias,
            official_source_qualifier.database_alias,
        )
        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise ValueError("E1 v3 temporal verification requires the default alias")
        if any(type(alias) is not str or alias != using for alias in aliases):
            raise ValueError("E1 v3 C2 and dual-capture readers must share the default alias")
        profile_expectation = official_source_qualifier.profile_expectation
        if type(profile_expectation) is not FinancialV3OfficialSourceProfileExpectation:
            raise ValueError("E1 v3 requires an explicit reviewed official-source profile")
        profile_expectation.__post_init__()
        self._records = records
        self._owner_events = owner_events
        self._source_reader = source_reader
        self._statutory_capture = statutory_capture
        self._official_source_qualifier = official_source_qualifier
        self._official_source_profile_expectation = profile_expectation
        self._using = using

    def resolve_current_in_uow(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        purpose: FinancialNumericVerificationPurpose,
    ) -> FinancialV3TemporalGateResolution:
        """Combine current C2 revalidation with the exact statutory dual capture."""

        if purpose not in {
            FinancialNumericVerificationPurpose.CURRENT_READ,
            FinancialNumericVerificationPurpose.CURRENT_WRITE,
            FinancialNumericVerificationPurpose.CURRENT_PUBLICATION,
        }:
            raise ValueError("current temporal gate requires an explicit current purpose")
        require_financial_v3_caller_owned_uow(using=self._using)
        identity = _require_statutory_source_identity(witness)
        temporal = validate_financial_next_session_witness_current(
            witness,
            records=self._records,
            owner_events=self._owner_events,
            source_reader=self._source_reader,
        )
        if (
            type(temporal) is not CurrentFinancialNextSessionTemporalCheck
            or temporal.witness != witness
            or temporal.reference_only is not True
            or temporal.must_not_use_for_decision is not True
        ):
            raise FinancialV3TemporalGateBlocked(
                "C2 current resolver did not return the exact reference-only witness check.",
                code="FINANCIAL_V3_C2_CURRENT_CHECK_INVALID",
            )
        known_at = temporal.governance.known_at
        expected_source = _require_opening_rule_source(
            identity=identity,
            rule=temporal.governance.opening_rule.resolved_content,
            source=temporal.governance.opening_rule.record.source,
        )
        source_read = _require_source_read(
            temporal.governance.opening_rule.source_read,
            expected_source=expected_source,
            known_at=known_at,
        )
        binding = self._statutory_capture.read_current(identity, known_at=known_at)
        self._validate_dual_capture(
            witness=witness,
            binding=binding,
            expected_known_at=known_at,
            expected_statutory_capture=temporal.governance.opening_rule.record.source,
        )
        official = self._official_source_qualifier.verify_current(
            identity,
            expected_source,
            source_read,
            known_at=known_at,
        )
        self._validate_official_source_observation(
            identity=identity,
            capture=expected_source,
            observation=official,
            expected_known_at=known_at,
            expected_mode="current_exact_capture",
        )
        final_checked_at = max(temporal.checked_at, binding.checked_at, official.checked_at)
        try:
            validate_current_financial_next_session_temporal_binding(
                witness,
                temporal.governance,
                temporal.historical_calendar,
                temporal.current_calendar,
                checked_at=final_checked_at,
            )
        except (DataValidationError, TypeError, ValueError) as error:
            raise FinancialV3TemporalGateBlocked(
                "Current calendar or opening rule expired during qualified source verification.",
                code="FINANCIAL_V3_CURRENT_TEMPORAL_WINDOW_EXPIRED",
            ) from error
        return self._resolution(
            witness=witness,
            purpose=purpose,
            known_at=final_checked_at,
            binding=binding,
            official_source=official,
        )

    def resolve_point_in_time(
        self,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        known_at: datetime,
    ) -> FinancialV3TemporalGateResolution:
        """Re-read original C2 source, Owner, and calendar state at witness time."""

        cutoff = _require_utc(known_at, "PIT requested cutoff")
        if cutoff < witness.earliest_temporal_usability_at:
            raise FinancialV3TemporalGateBlocked(
                "PIT cutoff precedes the source response or next-session availability.",
                code="FINANCIAL_V3_PIT_BEFORE_USABILITY",
            )
        if not witness.is_temporally_available_at(cutoff):
            raise FinancialV3TemporalGateBlocked(
                "PIT cutoff precedes the original v3 witness or its source availability.",
                code="FINANCIAL_V3_PIT_BEFORE_USABILITY",
            )
        identity = _require_statutory_source_identity(witness)
        original_known_at = witness.known_at
        with transaction.atomic(using=self._using):
            opening = read_financial_availability_governance(
                GetFinancialAvailabilityGovernanceQuery(
                    kind=FinancialAvailabilityRecordKind.OPENING_RULE,
                    exchange=witness.availability.calendar.exchange,
                    effective_on=witness.availability.next_session,
                    known_at=original_known_at,
                ),
                records=self._records,
                owner_events=self._owner_events,
                source_reader=self._source_reader,
            )
            policy = read_financial_availability_governance(
                GetFinancialAvailabilityGovernanceQuery(
                    kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
                    exchange=witness.availability.calendar.exchange,
                    effective_on=witness.availability.next_session,
                    known_at=original_known_at,
                ),
                records=self._records,
                owner_events=self._owner_events,
                source_reader=self._source_reader,
            )
            historical = _read_historical_calendar(witness, records=self._records)
            binding = self._statutory_capture.read_as_of(
                identity,
                known_at=original_known_at,
            )
            self._validate_pit_governance(witness, opening=opening, policy=policy)
            _verify_original_calendar_reference(witness, historical)
            opening_rule = opening.resolved_content
            if type(opening_rule) is not ExchangeSessionOpeningRule:
                raise FinancialV3TemporalGateBlocked(
                    "PIT opening rule is not the exact applied rule.",
                    code="FINANCIAL_V3_C2_RULE_INVALID",
                )
            expected_source = _require_opening_rule_source(
                identity=identity,
                rule=opening_rule,
                source=opening.record.source,
            )
            source_read = _require_source_read(
                opening.source_read,
                expected_source=expected_source,
                known_at=original_known_at,
            )
            next_session = next_exchange_calendar_session(
                historical.record.seal.snapshot,
                after_date=witness.financial_row.notice_date,
            )
            if (
                next_session != witness.availability.next_session
                or _opening_clock_utc(next_session, opening_rule)
                != witness.availability.available_at
            ):
                raise FinancialV3TemporalGateBlocked(
                    "PIT calendar/rule does not reproduce the original next-open mapping.",
                    code="FINANCIAL_V3_C2_MAPPING_CHANGED",
                )
            self._validate_dual_capture(
                witness=witness,
                binding=binding,
                expected_known_at=original_known_at,
                expected_statutory_capture=opening.record.source,
            )
            official = self._official_source_qualifier.verify_point_in_time(
                identity,
                expected_source,
                source_read,
                known_at=original_known_at,
            )
            self._validate_official_source_observation(
                identity=identity,
                capture=expected_source,
                observation=official,
                expected_known_at=original_known_at,
                expected_mode="point_in_time_exact_capture",
            )
        return self._resolution(
            witness=witness,
            purpose=FinancialNumericVerificationPurpose.POINT_IN_TIME_READ,
            known_at=original_known_at,
            binding=binding,
            official_source=official,
        )

    @staticmethod
    def _validate_pit_governance(
        witness: FinancialNextSessionSourceTimeWitnessV3,
        *,
        opening: FinancialAvailabilityGovernanceReadResult,
        policy: FinancialAvailabilityGovernanceReadResult,
    ) -> None:
        """Bind actual historical C2 records and apply events to the v3 references."""

        if (
            type(opening) is not FinancialAvailabilityGovernanceReadResult
            or type(policy) is not FinancialAvailabilityGovernanceReadResult
            or opening.known_at != witness.known_at
            or policy.known_at != witness.known_at
        ):
            raise FinancialV3TemporalGateBlocked(
                "PIT governance rows did not use the witness's original cutoff.",
                code="FINANCIAL_V3_C2_CUTOFF_MISMATCH",
            )
        opening_rule = opening.resolved_content
        disclosure_policy = policy.resolved_content
        if (
            type(opening_rule) is not ExchangeSessionOpeningRule
            or type(disclosure_policy) is not FinancialDisclosureAvailabilityPolicy
            or opening_rule != witness.availability.opening_rule
            or disclosure_policy != witness.governance.policy
        ):
            raise FinancialV3TemporalGateBlocked(
                "PIT applied rule or policy differs from the exact v3 witness.",
                code="FINANCIAL_V3_C2_GOVERNANCE_CHANGED",
            )
        try:
            _verify_approval(
                witness.governance.opening_rule_approval,
                record=opening.record,
                event=opening.apply_event,
                expected_record_id=witness.governance.opening_rule_record_id,
                expected_subject_sha256=opening_rule.rule_sha256,
            )
            _verify_approval(
                witness.governance.policy_approval,
                record=policy.record,
                event=policy.apply_event,
                expected_record_id=disclosure_policy.policy_id,
                expected_subject_sha256=disclosure_policy.policy_sha256,
            )
        except (DataValidationError, TypeError, ValueError) as error:
            raise FinancialV3TemporalGateBlocked(
                "PIT Owner apply rows differ from the exact v3 approval references.",
                code="FINANCIAL_V3_C2_OWNER_EVENT_CHANGED",
            ) from error
        if (
            opening.record.source is None
            or opening.source_read is None
            or opening.source_read.reference != opening.record.source
            or type(opening.record.source) is not StatutorySourceCaptureReference
        ):
            raise FinancialV3TemporalGateBlocked(
                "PIT opening rule has no exact retained statutory capture.",
                code="FINANCIAL_V3_STATUTORY_CAPTURE_MISSING",
            )
        witness.governance.validate_for(
            opening_rule=opening_rule,
            calendar=witness.availability.calendar,
            next_session=witness.availability.next_session,
            known_at=witness.known_at,
        )

    @staticmethod
    def _validate_dual_capture(
        *,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        binding: FinancialStatutoryCaptureBinding,
        expected_known_at: datetime,
        expected_statutory_capture: StatutorySourceCaptureReference | None,
    ) -> None:
        """Require a real statutory identity and the same 0116 capture as C2."""

        identity = _require_statutory_source_identity(witness)
        if (
            type(binding) is not FinancialStatutoryCaptureBinding
            or binding.official_source != identity
            or binding.known_at != expected_known_at
            or binding.statutory_capture != expected_statutory_capture
            or binding.document_capture.body_sha256 != identity.body_sha256
            or binding.document_capture.body_size_bytes != identity.body_size_bytes
            or binding.reference_only is not True
            or binding.must_not_use_for_decision is not True
        ):
            raise FinancialV3TemporalGateBlocked(
                "C2 source identity and independently retained 0116 capture do not match.",
                code="FINANCIAL_V3_DUAL_CAPTURE_MISMATCH",
            )
        try:
            binding.__post_init__()
        except (TypeError, ValueError) as error:
            raise FinancialV3TemporalGateBlocked(
                "C2 dual-capture body or clock evidence is malformed.",
                code="FINANCIAL_V3_DUAL_CAPTURE_INVALID",
            ) from error

    def _validate_official_source_observation(
        self,
        *,
        identity: FinancialStatutorySourceIdentity,
        capture: StatutorySourceCaptureReference,
        observation: FinancialV3OfficialSourceQualificationObservation,
        expected_known_at: datetime,
        expected_mode: Literal["current_exact_capture", "point_in_time_exact_capture"],
    ) -> None:
        """Require the exact reviewed profile, source, capture, and cutoff."""

        expectation = self._official_source_profile_expectation
        if (
            type(expectation) is not FinancialV3OfficialSourceProfileExpectation
            or type(observation) is not FinancialV3OfficialSourceQualificationObservation
            or observation.official_source != identity
            or observation.statutory_capture != capture
            or observation.known_at != expected_known_at
            or observation.profile_id != expectation.profile_id
            or observation.profile_version != expectation.profile_version
            or observation.publisher_code != expectation.publisher_code
            or observation.publisher_class != expectation.publisher_class
            or observation.profile_content_sha256 != expectation.profile_content_sha256
            or observation.verification_mode != expected_mode
            or observation.checked_at < expected_known_at
            or observation.reference_only is not True
            or observation.must_not_use_for_decision is not True
        ):
            raise FinancialV3TemporalGateBlocked(
                "Exact configured publisher/profile provenance is absent or changed.",
                code="FINANCIAL_V3_OFFICIAL_SOURCE_QUALIFICATION_INVALID",
            )
        try:
            expectation.__post_init__()
            observation.__post_init__()
        except (TypeError, ValueError) as error:
            raise FinancialV3TemporalGateBlocked(
                "Configured publisher/profile provenance is malformed.",
                code="FINANCIAL_V3_OFFICIAL_SOURCE_QUALIFICATION_INVALID",
            ) from error

    @staticmethod
    def _resolution(
        *,
        witness: FinancialNextSessionSourceTimeWitnessV3,
        purpose: FinancialNumericVerificationPurpose,
        known_at: datetime,
        binding: FinancialStatutoryCaptureBinding,
        official_source: FinancialV3OfficialSourceQualificationObservation,
    ) -> FinancialV3TemporalGateResolution:
        """Create the short-lived composite result after every underlying check."""

        if (
            type(binding) is not FinancialStatutoryCaptureBinding
            or binding.official_source != witness.governance.official_source
        ):
            raise FinancialV3TemporalGateBlocked(
                "Composite C2 gate did not retain its exact official source identity.",
                code="FINANCIAL_V3_DUAL_CAPTURE_MISMATCH",
            )
        witness_payload = encode_financial_next_session_witness_v3(witness)
        witness_sha256 = witness_payload.get("witness_sha256")
        if type(witness_sha256) is not str:
            raise FinancialV3TemporalGateBlocked(
                "Exact v3 witness digest is unavailable.",
                code="FINANCIAL_V3_WITNESS_INVALID",
            )
        try:
            return FinancialV3TemporalGateResolution(
                witness_sha256=witness_sha256,
                purpose=purpose,
                known_at=known_at,
                official_source_revision_sha256=binding.official_source.source_revision_sha256,
                statutory_capture_id=binding.statutory_capture.capture_id,
                numeric_document_capture_id=binding.document_capture.capture_id,
                official_profile_id=official_source.profile_id,
                official_profile_version=official_source.profile_version,
                official_publisher_code=official_source.publisher_code,
                official_publisher_class=official_source.publisher_class,
                official_profile_content_sha256=official_source.profile_content_sha256,
                official_configuration_sha256=official_source.configuration_sha256,
                verification_mode=official_source.verification_mode,
                statutory_capture_success_audit_count=(
                    official_source.statutory_capture_success_audit_count
                ),
                numeric_capture_success_audit_count=(
                    official_source.numeric_capture_success_audit_count
                ),
                origin_snapshot_id=official_source.origin_snapshot_id,
                origin_snapshot_version=official_source.origin_snapshot_version,
                origin_snapshot_sha256=official_source.origin_snapshot_sha256,
                origin_snapshot_recorded_at=official_source.origin_snapshot_recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise FinancialV3TemporalGateBlocked(
                "Composite C2 gate result has an invalid source identity.",
                code="FINANCIAL_V3_TEMPORAL_GATE_RESULT_INVALID",
            ) from error


class FinancialFactV3E1EvidenceVerifier:
    """Reopen the fact's own numeric body and NOTICE row before accepting v3."""

    def __init__(
        self,
        *,
        numeric_verifier: ContextualFinancialNumericEvidenceVerifier,
        temporal_gate: FinancialV3QualifiedTemporalGatePort,
        route_resolver: BalanceNumericEndpointRouteResolver,
        main_body_reader: FinancialNativeRawBodyReader,
        balance_body_reader: BalanceNumericOriginalBodyReader,
        main_notice_contract: FinancialSharedResponseSourceTimeContractV2,
        balance_parser_contract: BalanceCandidateContract,
    ) -> None:
        """Require the exact-body readers, source contracts, and C2 gate."""

        if any(
            dependency is None
            for dependency in (
                numeric_verifier,
                temporal_gate,
                route_resolver,
                main_body_reader,
                balance_body_reader,
            )
        ):
            raise TypeError("E1 v3 verifier requires every real verifier boundary")
        if type(main_notice_contract) is not FinancialSharedResponseSourceTimeContractV2:
            raise TypeError("Main NOTICE contract must be the exact shared-response v2 type")
        if type(balance_parser_contract) is not BalanceCandidateContract:
            raise TypeError("Balance parser contract must be explicit and typed")
        if (
            main_notice_contract.provider_name != AKSHARE_PROVIDER_NAME
            or main_notice_contract.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or main_notice_contract.endpoint != AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT
        ):
            raise ValueError("Main NOTICE contract does not bind the exact AKShare Main route")
        self._numeric_verifier = numeric_verifier
        self._temporal_gate = temporal_gate
        self._route_resolver = route_resolver
        self._main_body_reader = main_body_reader
        self._balance_body_reader = balance_body_reader
        self._main_notice_contract = main_notice_contract
        self._balance_parser_contract = balance_parser_contract

    def verify(
        self,
        fact: FinancialFact,
        request: FinancialV3FactVerificationRequest,
    ) -> bool:
        """Require date-only row replay, numeric proof, and C2 qualification."""

        try:
            return self._verify(fact, request)
        except (
            ArithmeticError,
            AttributeError,
            DatabaseError,
            DataFetchError,
            DataValidationError,
            LookupError,
            OSError,
            TypeError,
            ValueError,
        ):
            return False

    def _verify(
        self,
        fact: FinancialFact,
        request: FinancialV3FactVerificationRequest,
    ) -> bool:
        """Recheck one persisted v3 row without synthesizing ANN or timestamps."""

        if (
            type(fact) is not FinancialFact
            or type(request) is not FinancialV3FactVerificationRequest
        ):
            return False
        decision = fact.decision_evidence
        source = fact.source_evidence
        if (
            fact.numeric_schema != "native-decimal-v2"
            or decision is None
            or source is None
            or decision.source_time_witness_v3 is None
            or decision.source_time_witness is not None
            or source.announced_at is not None
            or source.source_record_id != decision.native_row_id
            or source.raw_payload_hash != decision.artifact_reference.body_sha256
            or decision.native_asset_code != fact.asset_code
            or decision.native_period_end != fact.period_end
            or fact.available_at is None
        ):
            return False
        witness = decision.source_time_witness_v3
        row_binding = witness.financial_row
        reference = decision.artifact_reference
        try:
            witness.__post_init__()
            row_binding.__post_init__()
        except (TypeError, ValueError):
            return False
        if (
            row_binding.artifact_reference != reference
            or row_binding.asset_code != fact.asset_code
            or row_binding.period_end != fact.period_end
            or row_binding.period_type is not fact.period_type
            or row_binding.metric_code != fact.metric_code
            or row_binding.native_row_id != decision.native_row_id
            or fact.available_at != witness.available_at
            or row_binding.notice_date != witness.availability.source_date
            or reference.evidence.request_scope.asset_code != fact.asset_code
            or reference.evidence.request_scope.provider_name != AKSHARE_PROVIDER_NAME
            or reference.evidence.request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
            or reference.evidence.response_scope_basis.value != "provider_body_verified"
            or fact.fetched_at < reference.evidence.response_completed_at
        ):
            return False

        endpoint = self._route_resolver.resolve(reference)
        if endpoint == AKSHARE_MAIN_FINANCIAL_DATA_ENDPOINT:
            if not self._replay_main_notice(fact=fact, witness=witness):
                return False
        elif endpoint == AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT:
            if not self._replay_balance_notice(fact=fact, witness=witness):
                return False
        else:
            return False

        if request.purpose is FinancialNumericVerificationPurpose.POINT_IN_TIME_READ:
            cutoff = request.known_at
            if cutoff is None or cutoff < witness.earliest_temporal_usability_at:
                return False
            temporal = self._temporal_gate.resolve_point_in_time(witness, known_at=cutoff)
            if temporal.known_at != witness.known_at:
                return False
            numeric_known_at = cutoff
        else:
            temporal = self._temporal_gate.resolve_current_in_uow(
                witness,
                purpose=request.purpose,
            )
            numeric_known_at = temporal.known_at

        expected_digest = encode_financial_next_session_witness_v3(witness).get("witness_sha256")
        if (
            type(temporal) is not FinancialV3TemporalGateResolution
            or temporal.witness_sha256 != expected_digest
            or temporal.purpose is not request.purpose
        ):
            return False
        numeric_context = FinancialNumericVerificationContext(
            known_at=numeric_known_at,
            purpose=request.purpose,
        )
        return self._numeric_verifier.verify(fact, numeric_context)

    def _replay_main_notice(
        self,
        *,
        fact: FinancialFact,
        witness: FinancialNextSessionSourceTimeWitnessV3,
    ) -> bool:
        """Independently match Main NOTICE_DATE on this fact's exact artifact."""

        row = witness.financial_row
        reference = row.artifact_reference
        body = self._main_body_reader.read_verified_body(reference)
        source_time_reference = FinancialSharedResponseSourceTimeReferenceV2(
            response_reference=reference,
            contract=self._main_notice_contract,
            requested_asset_code=fact.asset_code,
            requested_period_end=fact.period_end,
            requested_announcement_date=row.notice_date,
        )
        notice = match_shared_main_notice_date_v2(
            body,
            artifact_reference=source_time_reference,
        )
        return (
            notice is not None
            and notice.artifact_reference.response_reference == reference
            and notice.native_asset_code == fact.asset_code
            and notice.native_period_end == fact.period_end
            and notice.native_row_id == row.native_row_id
            and notice.notice_date == row.notice_date
            and notice.row_projection_sha256 == row.row_projection_sha256
            and notice.artifact_reference.body_sha256 == reference.body_sha256
        )

    def _replay_balance_notice(
        self,
        *,
        fact: FinancialFact,
        witness: FinancialNextSessionSourceTimeWitnessV3,
    ) -> bool:
        """Replay Balance's own exact row and six-field source projection."""

        reference = witness.financial_row.artifact_reference
        request = _balance_request(fact)
        verified = self._balance_body_reader.read_verified_response(reference)
        expected_params = dict(
            build_balance_candidate_query(request, self._balance_parser_contract).parameters
        )
        expected_params["endpoint"] = AKSHARE_BALANCE_FINANCIAL_DATA_ENDPOINT
        if not _same_exact_mapping(verified.request_params, expected_params):
            return False
        parsed = parse_balance_candidate_body(
            verified.body,
            request=request,
            contract=self._balance_parser_contract,
        )
        identity = parsed.source_row_identity
        return (
            parsed.outcome == "candidate_parsed"
            and parsed.body_sha256 == reference.body_sha256
            and parsed.body_size_bytes == reference.body_size_bytes
            and parsed.row_index == 0
            and identity is not None
            and identity.symbol == fact.asset_code
            and identity.report_date == fact.period_end
            and identity.notice_date == witness.financial_row.notice_date
            and _balance_native_row_id(identity) == witness.financial_row.native_row_id
            and parsed.row_projection_sha256 == witness.financial_row.row_projection_sha256
            and witness.financial_row.artifact_reference == reference
        )


def _balance_request(fact: FinancialFact) -> BalanceCandidateRequest:
    """Build an exact Balance selector without inferring an exchange suffix."""

    symbol = fact.asset_code
    if (
        type(symbol) is not str
        or len(symbol) != 9
        or symbol[6] != "."
        or symbol[7:] not in {"SH", "SZ"}
        or not symbol[:6].isascii()
        or not symbol[:6].isdigit()
    ):
        raise ValueError("Balance v3 replay requires an explicit SH/SZ asset code")
    return BalanceCandidateRequest(
        symbol=symbol,
        security_code=symbol[:6],
        report_date=fact.period_end,
    )


def _require_statutory_source_identity(
    witness: FinancialNextSessionSourceTimeWitnessV3,
) -> FinancialStatutorySourceIdentity:
    """Accept only the source identity branch backed by 0116 capture checks."""

    identity = witness.governance.official_source
    if type(identity) is not FinancialStatutorySourceIdentity:
        raise FinancialV3TemporalGateBlocked(
            "The legacy encrypted source identity has no 0116 statutory capture proof.",
            code="FINANCIAL_V3_STATUTORY_IDENTITY_UNSUPPORTED",
        )
    return identity


def _require_opening_rule_source(
    *,
    identity: FinancialStatutorySourceIdentity,
    rule: object,
    source: StatutorySourceCaptureReference | None,
) -> StatutorySourceCaptureReference:
    """Tie the Owner-applied opening rule to its exact statutory source capture."""

    if (
        type(rule) is not ExchangeSessionOpeningRule
        or type(source) is not StatutorySourceCaptureReference
    ):
        raise FinancialV3TemporalGateBlocked(
            "Applied opening rule has no exact retained source reference.",
            code="FINANCIAL_V3_STATUTORY_CAPTURE_MISSING",
        )
    try:
        identity.__post_init__()
        rule.__post_init__()
        source.__post_init__()
    except (TypeError, ValueError) as error:
        raise FinancialV3TemporalGateBlocked(
            "Applied opening-rule source identity is malformed.",
            code="FINANCIAL_V3_STATUTORY_SOURCE_IDENTITY_INVALID",
        ) from error
    if (
        identity.source_uri != rule.source_uri
        or identity.body_sha256 != rule.source_body_sha256
        or source.canonical_url != rule.source_uri
        or source.body_sha256 != rule.source_body_sha256
        or source.source_revision_sha256 != identity.source_revision_sha256
        or source.capture_id != identity.capture_id
    ):
        raise FinancialV3TemporalGateBlocked(
            "Statutory source does not match the exact Owner-applied opening-rule document.",
            code="FINANCIAL_V3_OPENING_RULE_SOURCE_MISMATCH",
        )
    return source


def _require_source_read(
    value: FinancialAvailabilitySourceRead | None,
    *,
    expected_source: StatutorySourceCaptureReference,
    known_at: datetime,
) -> FinancialAvailabilitySourceRead:
    """Keep the exact C2 bytes, capture and original knowledge cutoff together."""

    if type(value) is not FinancialAvailabilitySourceRead:
        raise FinancialV3TemporalGateBlocked(
            "Opening rule has no typed exact source body read.",
            code="FINANCIAL_V3_STATUTORY_SOURCE_READ_MISSING",
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise FinancialV3TemporalGateBlocked(
            "Opening-rule source bytes or source clocks failed exact validation.",
            code="FINANCIAL_V3_STATUTORY_SOURCE_READ_INVALID",
        ) from error
    if (
        value.reference != expected_source
        or value.known_at != known_at
        or value.reference.capture_id != expected_source.capture_id
        or value.reference.body_reference != expected_source.body_reference
        or value.reference.body_sha256 != expected_source.body_sha256
        or value.reference.body_size_bytes != expected_source.body_size_bytes
        or len(value.body) != expected_source.body_size_bytes
    ):
        raise FinancialV3TemporalGateBlocked(
            "Opening-rule source body differs from its exact capture or cutoff.",
            code="FINANCIAL_V3_STATUTORY_SOURCE_READ_MISMATCH",
        )
    return value


def _require_utc(value: object, name: str) -> datetime:
    """Require one explicit UTC value for a current or historical lookup."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{name} must be an explicit UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} is outside the UTC range") from error


def _is_sha256(value: str) -> bool:
    """Return whether text is one exact lowercase SHA-256 digest."""

    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "FinancialFactV3E1EvidenceVerifier",
    "FinancialV3QualifiedTemporalGate",
    "FinancialV3QualifiedTemporalGatePort",
    "FinancialV3StatutoryCapturePort",
    "FinancialV3TemporalGateBlocked",
    "FinancialV3TemporalGateResolution",
]
