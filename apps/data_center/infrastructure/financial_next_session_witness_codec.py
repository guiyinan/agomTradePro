"""Strict JSON codec for the additive financial next-session witness v3."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from uuid import UUID

from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
)
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.exchange_calendar import ExchangeCalendarSnapshotReference
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
    ExchangeSessionOpeningRule,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialApprovalIdentity,
    FinancialCalendarPublicationReference,
    FinancialDisclosureAvailabilityPolicy,
    FinancialNativeRowBinding,
    FinancialNextSessionAvailabilityReference,
    FinancialNextSessionGovernanceBinding,
    FinancialNextSessionSourceTimeWitnessV3,
    FinancialOfficialSourceIdentity,
)
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FINANCIAL_STATUTORY_SOURCE_IDENTITY_SCHEMA,
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from core.exceptions import DataValidationError

_SCHEMA_V3 = "financial-next-session-source-time-witness.v3"
_AVAILABILITY_SCHEMA = "financial-next-session-availability.reference.v1"
_ROOT_KEYS = frozenset(
    {
        "schema",
        "financial_row",
        "availability",
        "governance",
        "reference_only",
        "must_not_use_for_decision",
        "must_not_execute",
        "witness_sha256",
    }
)
_ROW_KEYS = frozenset(
    {
        "artifact_reference",
        "asset_code",
        "period_end",
        "period_type",
        "metric_code",
        "native_row_id",
        "notice_date",
        "row_projection_sha256",
        "matched_row_count",
    }
)
_ARTIFACT_KEYS = frozenset(
    {
        "capture_id",
        "location",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
        "evidence_basis",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "request_scope",
        "response_scope",
        "response_scope_basis",
        "body_scope",
    }
)
_REQUEST_KEYS = frozenset({"provider_name", "dataset_key", "asset_code", "period_limit"})
_RESPONSE_KEYS = frozenset({"asset_codes", "period_ends", "row_count"})
_AVAILABILITY_KEYS = frozenset(
    {
        "schema",
        "source_date",
        "next_session",
        "available_at",
        "known_at",
        "calendar",
        "opening_rule",
    }
)
_CALENDAR_KEYS = frozenset(
    {
        "dataset_key",
        "publication_key",
        "exchange",
        "publication_id",
        "publication_hash",
        "activation_id",
        "lifecycle_at_resolution",
        "superseded_at_at_resolution",
        "pointer_id",
        "pointer_updated_at",
        "contract_recorded_at",
        "policy_version",
        "policy_identity",
        "policy_recorded_at",
        "snapshot_reference",
        "snapshot_first_seen_at",
        "snapshot_recorded_at",
        "published_at",
        "valid_until_at_resolution",
        "response_max_age_seconds",
        "known_at",
    }
)
_SNAPSHOT_KEYS = frozenset(
    {
        "snapshot_id",
        "exchange",
        "coverage_start",
        "coverage_end",
        "content_hash",
        "record_digest",
        "raw_payload_id",
        "raw_payload_hash",
        "raw_record_digest",
    }
)
_OPENING_RULE_KEYS = frozenset(
    {
        "exchange",
        "phase",
        "rule_version",
        "source_uri",
        "source_body_sha256",
        "effective_start",
        "effective_end",
        "timezone_name",
        "local_open_time",
        "first_seen_at",
        "recorded_at",
        "approved_at",
        "rule_sha256",
        "identity",
    }
)
_GOVERNANCE_KEYS = frozenset(
    {
        "opening_rule_record_id",
        "official_source",
        "opening_rule_approval",
        "policy",
        "policy_approval",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "document_record_id",
        "capture_id",
        "source_uri",
        "body_sha256",
        "body_size_bytes",
        "artifact_location",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
        "first_seen_at",
        "recorded_at",
    }
)
_APPROVAL_KEYS = frozenset(
    {
        "subject_record_id",
        "subject_sha256",
        "event_id",
        "event_sha256",
        "principal_id",
        "approved_at",
        "recorded_at",
    }
)
_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "policy_version",
        "exchange",
        "opening_phase",
        "effective_start",
        "effective_end",
        "calendar_response_max_age_seconds",
        "first_seen_at",
        "recorded_at",
        "policy_sha256",
    }
)


class FinancialNextSessionWitnessCodecError(DataValidationError):
    """Raised when a persisted v3 witness is missing, ambiguous, or altered."""

    default_message = "Financial next-session witness projection is invalid"
    default_code = "FINANCIAL_NEXT_SESSION_WITNESS_INVALID"

    def __init__(
        self, message: str = "Financial next-session witness projection is invalid"
    ) -> None:
        """Keep one stable business error code for every strict decode failure."""

        super().__init__(message, code=self.default_code)


def encode_financial_next_session_witness_v3(
    witness: FinancialNextSessionSourceTimeWitnessV3,
) -> dict[str, object]:
    """Encode only the additive v3 reference object; legacy codecs are untouched."""

    if type(witness) is not FinancialNextSessionSourceTimeWitnessV3:
        raise FinancialNextSessionWitnessCodecError("v3 witness must be the exact typed object")
    try:
        return witness.to_dict()
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise FinancialNextSessionWitnessCodecError(
            "v3 witness no longer satisfies its typed invariants"
        ) from error


def decode_financial_next_session_witness_v3(
    raw: object,
) -> FinancialNextSessionSourceTimeWitnessV3:
    """Decode an exact v3 payload and recheck all structural cross-bindings.

    Successful decoding proves only that the payload is internally consistent.
    It does not authenticate its source originals, Owner approvals, catalog
    rows, Audit events, current publication, or historical point-in-time state.
    """

    try:
        root = _mapping(raw, "witness")
        _exact_keys(root, _ROOT_KEYS, "witness")
        if _text(root["schema"], "schema") != _SCHEMA_V3:
            raise FinancialNextSessionWitnessCodecError("v3 witness schema is invalid")
        for flag in ("reference_only", "must_not_use_for_decision", "must_not_execute"):
            if type(root[flag]) is not bool or root[flag] is not True:
                raise FinancialNextSessionWitnessCodecError(f"{flag} must remain true")
        witness = FinancialNextSessionSourceTimeWitnessV3(
            financial_row=_decode_row(root["financial_row"]),
            availability=_decode_availability(root["availability"]),
            governance=_decode_governance(root["governance"]),
        )
        witness.__post_init__()
        expected_hash = witness.to_dict()["witness_sha256"]
        if _text(root["witness_sha256"], "witness_sha256") != expected_hash:
            raise FinancialNextSessionWitnessCodecError("v3 witness integrity hash is invalid")
        return witness
    except FinancialNextSessionWitnessCodecError:
        raise
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as error:
        raise FinancialNextSessionWitnessCodecError(
            "v3 witness contains invalid typed or cross-bound values"
        ) from error


def _decode_row(raw: object) -> FinancialNativeRowBinding:
    row = _mapping(raw, "financial_row")
    _exact_keys(row, _ROW_KEYS, "financial_row")
    try:
        period_type = FinancialPeriodType(_text(row["period_type"], "period_type"))
    except ValueError as error:
        raise FinancialNextSessionWitnessCodecError("financial period_type is invalid") from error
    return FinancialNativeRowBinding(
        artifact_reference=_decode_artifact_reference(row["artifact_reference"]),
        asset_code=_text(row["asset_code"], "asset_code"),
        period_end=_date(row["period_end"], "period_end"),
        period_type=period_type,
        metric_code=_text(row["metric_code"], "metric_code"),
        native_row_id=_text(row["native_row_id"], "native_row_id"),
        notice_date=_date(row["notice_date"], "notice_date"),
        row_projection_sha256=_text(row["row_projection_sha256"], "row_projection_sha256"),
        matched_row_count=_integer(row["matched_row_count"], "matched_row_count"),
    )


def _decode_artifact_reference(raw: object) -> FinancialResponseArtifactRef:
    reference = _mapping(raw, "artifact_reference")
    _exact_keys(reference, _ARTIFACT_KEYS, "artifact_reference")
    if _text(reference["evidence_basis"], "evidence_basis") != "raw_response_bytes":
        raise FinancialNextSessionWitnessCodecError("artifact evidence basis is invalid")
    request = _mapping(reference["request_scope"], "request_scope")
    response = _mapping(reference["response_scope"], "response_scope")
    _exact_keys(request, _REQUEST_KEYS, "request_scope")
    _exact_keys(response, _RESPONSE_KEYS, "response_scope")
    try:
        period_ends = tuple(
            _date(item, "response_scope.period_ends")
            for item in _list(response["period_ends"], "response_scope.period_ends")
        )
        asset_codes = tuple(
            _text(item, "response_scope.asset_codes")
            for item in _list(response["asset_codes"], "response_scope.asset_codes")
        )
        evidence = FinancialResponseEvidence(
            body_sha256=_text(reference["body_sha256"], "body_sha256"),
            body_size_bytes=_integer(reference["body_size_bytes"], "body_size_bytes"),
            response_completed_at=_datetime(
                reference["response_completed_at"], "response_completed_at"
            ),
            request_scope=FinancialRequestScope(
                provider_name=_text(request["provider_name"], "request_scope.provider_name"),
                dataset_key=_text(request["dataset_key"], "request_scope.dataset_key"),
                asset_code=_text(request["asset_code"], "request_scope.asset_code"),
                period_limit=_integer(request["period_limit"], "request_scope.period_limit"),
            ),
            response_scope=FinancialResponseScope(
                asset_codes=asset_codes,
                period_ends=period_ends,
                row_count=_integer(response["row_count"], "response_scope.row_count"),
            ),
            body_scope=FinancialResponseBodyScope(_text(reference["body_scope"], "body_scope")),
            response_scope_basis=FinancialResponseScopeBasis(
                _text(reference["response_scope_basis"], "response_scope_basis")
            ),
        )
        return FinancialResponseArtifactRef(
            capture_id=_uuid(reference["capture_id"], "capture_id"),
            location=_text(reference["location"], "location"),
            evidence=evidence,
            format_version=_text(reference["format_version"], "format_version"),
            encryption_algorithm=_text(reference["encryption_algorithm"], "encryption_algorithm"),
            encryption_key_ref=_text(reference["encryption_key_ref"], "encryption_key_ref"),
            encryption_key_version=_text(
                reference["encryption_key_version"], "encryption_key_version"
            ),
        )
    except (TypeError, ValueError) as error:
        raise FinancialNextSessionWitnessCodecError(
            "financial artifact reference contains invalid evidence"
        ) from error


def _decode_availability(raw: object) -> FinancialNextSessionAvailabilityReference:
    availability = _mapping(raw, "availability")
    _exact_keys(availability, _AVAILABILITY_KEYS, "availability")
    if _text(availability["schema"], "availability.schema") != _AVAILABILITY_SCHEMA:
        raise FinancialNextSessionWitnessCodecError("availability reference schema is invalid")
    return FinancialNextSessionAvailabilityReference(
        source_date=_date(availability["source_date"], "availability.source_date"),
        next_session=_date(availability["next_session"], "availability.next_session"),
        available_at=_datetime(availability["available_at"], "availability.available_at"),
        known_at=_datetime(availability["known_at"], "availability.known_at"),
        calendar=_decode_calendar(availability["calendar"]),
        opening_rule=_decode_opening_rule(availability["opening_rule"]),
    )


def _decode_calendar(raw: object) -> FinancialCalendarPublicationReference:
    calendar = _mapping(raw, "calendar")
    _exact_keys(calendar, _CALENDAR_KEYS, "calendar")
    snapshot = _mapping(calendar["snapshot_reference"], "snapshot_reference")
    _exact_keys(snapshot, _SNAPSHOT_KEYS, "snapshot_reference")
    return FinancialCalendarPublicationReference(
        dataset_key=_text(calendar["dataset_key"], "calendar.dataset_key"),
        publication_key=_text(calendar["publication_key"], "calendar.publication_key"),
        exchange=_text(calendar["exchange"], "calendar.exchange"),
        publication_id=_text(calendar["publication_id"], "calendar.publication_id"),
        publication_hash=_text(calendar["publication_hash"], "calendar.publication_hash"),
        activation_id=_text(calendar["activation_id"], "calendar.activation_id"),
        lifecycle_at_resolution=CalendarPublicationLifecycle(
            _text(calendar["lifecycle_at_resolution"], "calendar.lifecycle_at_resolution")
        ),
        superseded_at_at_resolution=_optional_datetime(
            calendar["superseded_at_at_resolution"], "calendar.superseded_at_at_resolution"
        ),
        pointer_id=_text(calendar["pointer_id"], "calendar.pointer_id"),
        pointer_updated_at=_datetime(calendar["pointer_updated_at"], "calendar.pointer_updated_at"),
        contract_recorded_at=_datetime(
            calendar["contract_recorded_at"], "calendar.contract_recorded_at"
        ),
        policy_version=_text(calendar["policy_version"], "calendar.policy_version"),
        policy_identity=_text(calendar["policy_identity"], "calendar.policy_identity"),
        policy_recorded_at=_datetime(calendar["policy_recorded_at"], "calendar.policy_recorded_at"),
        snapshot_reference=ExchangeCalendarSnapshotReference(
            snapshot_id=_text(snapshot["snapshot_id"], "snapshot.snapshot_id"),
            exchange=_text(snapshot["exchange"], "snapshot.exchange"),
            coverage_start=_date(snapshot["coverage_start"], "snapshot.coverage_start"),
            coverage_end=_date(snapshot["coverage_end"], "snapshot.coverage_end"),
            content_hash=_text(snapshot["content_hash"], "snapshot.content_hash"),
            record_digest=_text(snapshot["record_digest"], "snapshot.record_digest"),
            raw_payload_id=_text(snapshot["raw_payload_id"], "snapshot.raw_payload_id"),
            raw_payload_hash=_text(snapshot["raw_payload_hash"], "snapshot.raw_payload_hash"),
            raw_record_digest=_text(snapshot["raw_record_digest"], "snapshot.raw_record_digest"),
        ),
        snapshot_first_seen_at=_datetime(
            calendar["snapshot_first_seen_at"], "calendar.snapshot_first_seen_at"
        ),
        snapshot_recorded_at=_datetime(
            calendar["snapshot_recorded_at"], "calendar.snapshot_recorded_at"
        ),
        published_at=_datetime(calendar["published_at"], "calendar.published_at"),
        valid_until_at_resolution=_datetime(
            calendar["valid_until_at_resolution"], "calendar.valid_until_at_resolution"
        ),
        response_max_age_seconds=_integer(
            calendar["response_max_age_seconds"], "calendar.response_max_age_seconds"
        ),
        known_at=_datetime(calendar["known_at"], "calendar.known_at"),
    )


def _decode_opening_rule(raw: object) -> ExchangeSessionOpeningRule:
    rule_raw = _mapping(raw, "opening_rule")
    _exact_keys(rule_raw, _OPENING_RULE_KEYS, "opening_rule")
    rule = ExchangeSessionOpeningRule(
        exchange=_text(rule_raw["exchange"], "rule.exchange"),
        phase=ExchangeSessionOpeningPhase(_text(rule_raw["phase"], "rule.phase")),
        rule_version=_text(rule_raw["rule_version"], "rule.rule_version"),
        source_uri=_text(rule_raw["source_uri"], "rule.source_uri"),
        source_body_sha256=_text(rule_raw["source_body_sha256"], "rule.source_body_sha256"),
        effective_start=_date(rule_raw["effective_start"], "rule.effective_start"),
        effective_end=_date(rule_raw["effective_end"], "rule.effective_end"),
        timezone_name=_text(rule_raw["timezone_name"], "rule.timezone_name"),
        local_open_time=_time(rule_raw["local_open_time"], "rule.local_open_time"),
        first_seen_at=_datetime(rule_raw["first_seen_at"], "rule.first_seen_at"),
        recorded_at=_datetime(rule_raw["recorded_at"], "rule.recorded_at"),
        approved_at=_datetime(rule_raw["approved_at"], "rule.approved_at"),
        rule_sha256=_text(rule_raw["rule_sha256"], "rule.rule_sha256"),
    )
    if _text(rule_raw["identity"], "rule.identity") != rule.identity:
        raise FinancialNextSessionWitnessCodecError("opening rule identity token is inconsistent")
    return rule


def _decode_governance(raw: object) -> FinancialNextSessionGovernanceBinding:
    governance = _mapping(raw, "governance")
    _exact_keys(governance, _GOVERNANCE_KEYS, "governance")
    source_raw = _mapping(governance["official_source"], "official_source")
    approval_raw = _mapping(governance["opening_rule_approval"], "opening_rule_approval")
    policy_raw = _mapping(governance["policy"], "policy")
    policy_approval_raw = _mapping(governance["policy_approval"], "policy_approval")
    _exact_keys(approval_raw, _APPROVAL_KEYS, "opening_rule_approval")
    _exact_keys(policy_raw, _POLICY_KEYS, "policy")
    _exact_keys(policy_approval_raw, _APPROVAL_KEYS, "policy_approval")
    policy = FinancialDisclosureAvailabilityPolicy(
        policy_id=_text(policy_raw["policy_id"], "policy.policy_id"),
        policy_version=_text(policy_raw["policy_version"], "policy.policy_version"),
        exchange=_text(policy_raw["exchange"], "policy.exchange"),
        opening_phase=ExchangeSessionOpeningPhase(
            _text(policy_raw["opening_phase"], "policy.opening_phase")
        ),
        effective_start=_date(policy_raw["effective_start"], "policy.effective_start"),
        effective_end=_date(policy_raw["effective_end"], "policy.effective_end"),
        calendar_response_max_age_seconds=_integer(
            policy_raw["calendar_response_max_age_seconds"],
            "policy.calendar_response_max_age_seconds",
        ),
        first_seen_at=_datetime(policy_raw["first_seen_at"], "policy.first_seen_at"),
        recorded_at=_datetime(policy_raw["recorded_at"], "policy.recorded_at"),
        policy_sha256=_text(policy_raw["policy_sha256"], "policy.policy_sha256"),
    )
    return FinancialNextSessionGovernanceBinding(
        opening_rule_record_id=_text(
            governance["opening_rule_record_id"], "opening_rule_record_id"
        ),
        official_source=_decode_official_source(source_raw),
        opening_rule_approval=_decode_approval(approval_raw),
        policy=policy,
        policy_approval=_decode_approval(policy_approval_raw),
    )


def _decode_official_source(
    source_raw: Mapping[str, object],
) -> FinancialOfficialSourceIdentity | FinancialStatutorySourceIdentity:
    """Decode one explicit retained-storage identity without inventing encryption."""

    if "schema" in source_raw:
        schema = _text(source_raw["schema"], "source.schema")
        if schema != FINANCIAL_STATUTORY_SOURCE_IDENTITY_SCHEMA:
            raise FinancialNextSessionWitnessCodecError("official source storage schema is invalid")
        _exact_keys(
            source_raw,
            frozenset(
                {
                    "schema",
                    "issuer",
                    "document_id",
                    "source_version",
                    "source_revision_sha256",
                    "source_uri",
                    "capture_id",
                    "body_reference",
                    "body_sha256",
                    "body_size_bytes",
                    "first_seen_at",
                    "revision_recorded_at",
                    "capture_observed_at",
                    "recorded_at",
                }
            ),
            "official_source",
        )
        return FinancialStatutorySourceIdentity(
            issuer=_text(source_raw["issuer"], "source.issuer"),
            document_id=_text(source_raw["document_id"], "source.document_id"),
            source_version=_text(source_raw["source_version"], "source.source_version"),
            source_revision_sha256=_text(
                source_raw["source_revision_sha256"], "source.source_revision_sha256"
            ),
            source_uri=_text(source_raw["source_uri"], "source.source_uri"),
            body_reference=StatutorySourceBodyReference(
                capture_id=_uuid(source_raw["capture_id"], "source.capture_id"),
                reference=_text(source_raw["body_reference"], "source.body_reference"),
                body_sha256=_text(source_raw["body_sha256"], "source.body_sha256"),
                body_size_bytes=_integer(source_raw["body_size_bytes"], "source.body_size_bytes"),
            ),
            first_seen_at=_datetime(source_raw["first_seen_at"], "source.first_seen_at"),
            revision_recorded_at=_datetime(
                source_raw["revision_recorded_at"], "source.revision_recorded_at"
            ),
            capture_observed_at=_datetime(
                source_raw["capture_observed_at"], "source.capture_observed_at"
            ),
            recorded_at=_datetime(source_raw["recorded_at"], "source.recorded_at"),
        )
    _exact_keys(source_raw, _SOURCE_KEYS, "official_source")
    return FinancialOfficialSourceIdentity(
        document_record_id=_text(source_raw["document_record_id"], "source.document_record_id"),
        capture_id=_uuid(source_raw["capture_id"], "source.capture_id"),
        source_uri=_text(source_raw["source_uri"], "source.source_uri"),
        body_sha256=_text(source_raw["body_sha256"], "source.body_sha256"),
        body_size_bytes=_integer(source_raw["body_size_bytes"], "source.body_size_bytes"),
        artifact_location=_text(source_raw["artifact_location"], "source.artifact_location"),
        format_version=_text(source_raw["format_version"], "source.format_version"),
        encryption_algorithm=_text(
            source_raw["encryption_algorithm"], "source.encryption_algorithm"
        ),
        encryption_key_ref=_text(source_raw["encryption_key_ref"], "source.encryption_key_ref"),
        encryption_key_version=_text(
            source_raw["encryption_key_version"], "source.encryption_key_version"
        ),
        first_seen_at=_datetime(source_raw["first_seen_at"], "source.first_seen_at"),
        recorded_at=_datetime(source_raw["recorded_at"], "source.recorded_at"),
    )


def _decode_approval(raw: Mapping[str, object]) -> FinancialApprovalIdentity:
    return FinancialApprovalIdentity(
        subject_record_id=_text(raw["subject_record_id"], "approval.subject_record_id"),
        subject_sha256=_text(raw["subject_sha256"], "approval.subject_sha256"),
        event_id=_text(raw["event_id"], "approval.event_id"),
        event_sha256=_text(raw["event_sha256"], "approval.event_sha256"),
        principal_id=_text(raw["principal_id"], "approval.principal_id"),
        approved_at=_datetime(raw["approved_at"], "approval.approved_at"),
        recorded_at=_datetime(raw["recorded_at"], "approval.recorded_at"),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    if frozenset(value) != expected:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} keys are invalid")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be canonical text")
    return value


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be an integer")
    return value


def _list(value: object, field_name: str) -> list[object]:
    if type(value) is not list:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be a list")
    return value


def _date(value: object, field_name: str) -> date:
    text = _text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be an ISO date") from error
    if type(parsed) is not date or parsed.isoformat() != text:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be a canonical date")
    return parsed


def _datetime(value: object, field_name: str) -> datetime:
    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise FinancialNextSessionWitnessCodecError(
            f"{field_name} must be an ISO datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or parsed.isoformat() != text:
        raise FinancialNextSessionWitnessCodecError(
            f"{field_name} must be a canonical aware UTC datetime"
        )
    return parsed


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    """Decode a nullable canonical UTC timestamp without coercion."""

    if value is None:
        return None
    return _datetime(value, field_name)


def _time(value: object, field_name: str) -> time:
    text = _text(value, field_name)
    try:
        parsed = time.fromisoformat(text)
    except ValueError as error:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be an ISO clock") from error
    if parsed.tzinfo is not None or parsed.fold != 0 or parsed.isoformat() != text:
        raise FinancialNextSessionWitnessCodecError(
            f"{field_name} must be a canonical local wall clock"
        )
    return parsed


def _uuid(value: object, field_name: str) -> UUID:
    text = _text(value, field_name)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be a UUID") from error
    if str(parsed) != text:
        raise FinancialNextSessionWitnessCodecError(f"{field_name} must be a canonical UUID")
    return parsed


__all__ = [
    "FinancialNextSessionWitnessCodecError",
    "decode_financial_next_session_witness_v3",
    "encode_financial_next_session_witness_v3",
]
