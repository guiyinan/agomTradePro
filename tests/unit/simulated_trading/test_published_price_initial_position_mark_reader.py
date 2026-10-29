"""Contracts for the opt-in published-price first-position mark reader."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.application.price_response_capture import ExactPriceBarValues
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.published_price_source import (
    PublishedPriceSourceEvidence,
    PublishedPriceSourceResult,
)
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.raw_audit_manifest import (
    RAW_AUDIT_REFERENCE_VERSION,
    CandidateRawAuditReference,
)
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    ExecutionCurrentReferenceSelectorItemV2,
    ExecutionCurrentReferenceSelectorV2,
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.initial_position_mark import (
    InitialPositionMarkProof,
    InitialPositionMarkValidationError,
)
from apps.simulated_trading.domain.initial_position_mark_policy import (
    InitialPositionMarkPolicy,
    InitialPositionMarkPolicyBinding,
    InitialPositionMarkRuntimeProvenance,
)
from apps.simulated_trading.infrastructure.published_price_initial_position_mark_reader import (
    PublishedPriceInitialPositionMarkReader,
)

_AS_OF = datetime(2026, 10, 28, 6, 59, tzinfo=UTC)
_SECURITY_ID = "risk-security-fixture-001"
_ASSET_CODE = "600000.SH"
_ASSET_TYPE = "fixture_simulated_type_v7"
_RULE_MARKET = "FIXTURE_SSE"
_BOARD = "FIXTURE_MAIN"
_SOURCE_EXCHANGE = "SSE"
_POLICY_KEY = "fixture-first-buy-mark-reference"
_LEGACY_POLICY_SCHEMA = "simulated-initial-position-mark-policy.v1"
_DAILY_POLICY_SCHEMA = "simulated-initial-position-mark-policy.daily-interval.v1"
_RUN_ID = "11111111-1111-4111-8111-111111111111"
_INGESTED_RUN_ID = "22222222-2222-4222-8222-222222222222"
_SNAPSHOT_ID = UUID("33333333-3333-4333-8333-333333333333")
_MAPPING_RECORD_ID = UUID("44444444-4444-4444-8444-444444444444")
_OCCURRENCE_ID = UUID("55555555-5555-4555-8555-555555555555")


def _hash(character: str) -> str:
    """Return one deterministic lowercase digest for typed evidence fixtures."""

    return character * 64


def _prefixed_hash(character: str) -> str:
    """Return one calendar-domain digest in its canonical prefixed form."""

    return f"sha256:{_hash(character)}"


def _policy(**changes: object) -> InitialPositionMarkPolicy:
    """Create the full explicit source policy used by these reader contracts."""

    values: dict[str, object] = {
        "schema_version": _LEGACY_POLICY_SCHEMA,
        "purpose": "apply_time_initial_position_mark",
        "policy_id": "first-buy-mark-policy",
        "version": "v7",
        "publication_key": _POLICY_KEY,
        "source": "tushare",
        "frequency": "1d",
        "adjustment": "none",
        "supported_asset_types": (_ASSET_TYPE,),
        "freshness_window_seconds": 86400,
    }
    values.update(changes)
    return InitialPositionMarkPolicy(**values)  # type: ignore[arg-type]


def _daily_policy(**changes: object) -> InitialPositionMarkPolicy:
    """Create a daily-interval policy with its observation basis explicit."""

    values: dict[str, object] = {
        "schema_version": _DAILY_POLICY_SCHEMA,
        "observation_basis": "daily_interval_end",
    }
    values.update(changes)
    return _policy(**values)


def _binding(
    as_of: datetime = _AS_OF,
    *,
    policy: InitialPositionMarkPolicy | None = None,
    provenance_changes: dict[str, object] | None = None,
) -> InitialPositionMarkPolicyBinding:
    """Bind one explicit policy to a versioned active runtime profile and snapshot."""

    values: dict[str, object] = {
        "runtime_environment": "development",
        "profile_id": "initial-mark-profile-7",
        "profile_key": "simulated-initial-mark",
        "profile_version": 7,
        "profile_content_hash": _hash("a"),
        "profile_activated_at": as_of - timedelta(hours=5),
        "snapshot_id": "initial-mark-snapshot-7",
        "snapshot_content_hash": _hash("b"),
        "snapshot_generated_at": as_of - timedelta(hours=4),
        "snapshot_effective_from": as_of - timedelta(hours=5),
        "read_at": as_of,
    }
    if provenance_changes is not None:
        values.update(provenance_changes)
    provenance = InitialPositionMarkRuntimeProvenance(**values)  # type: ignore[arg-type]
    return InitialPositionMarkPolicyBinding(policy=policy or _daily_policy(), provenance=provenance)


def _classification(
    as_of: datetime = _AS_OF,
    *,
    provenance: InitialPositionMarkRuntimeProvenance | None = None,
) -> SimulatedInstrumentClassificationEvidenceV1:
    """Build real source-pinned classification evidence for the exact requested identity."""

    selector_item = ExecutionCurrentReferenceSelectorItemV2(
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        source_code=_ASSET_CODE,
        snapshot_id=_SNAPSHOT_ID,
        snapshot_content_hash=_prefixed_hash("a"),
        snapshot_record_digest=_prefixed_hash("b"),
        mapping_record_id=_MAPPING_RECORD_ID,
        mapping_id="fixture-instrument-map",
        mapping_version="v1",
        mapping_content_hash=_prefixed_hash("c"),
        mapping_record_digest=_prefixed_hash("d"),
        simulated_asset_type=_ASSET_TYPE,
    )
    selector = ExecutionCurrentReferenceSelectorV2(
        purpose="normal_simulated_current_reference",
        max_local_reference_age_seconds=3600,
        items=(selector_item,),
    )
    reference_at = as_of - timedelta(minutes=10)
    snapshot_recorded_at = as_of - timedelta(minutes=5)
    mapping_recorded_at = as_of - timedelta(hours=1)
    activated_at = as_of - timedelta(hours=5)
    source = ExecutionInstrumentIdentityEvidenceV1(
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        source_code=_ASSET_CODE,
        source_exchange=_SOURCE_EXCHANGE,
        source_market="FIXTURE_MAIN",
        rule_market=_RULE_MARKET,
        board=_BOARD,
        snapshot_id=_SNAPSHOT_ID,
        snapshot_content_hash=_prefixed_hash("a"),
        snapshot_record_digest=_prefixed_hash("b"),
        first_seen_at=reference_at,
        snapshot_recorded_at=snapshot_recorded_at,
        mapping_record_id=_MAPPING_RECORD_ID,
        mapping_id="fixture-instrument-map",
        mapping_version="v1",
        mapping_content_hash=_prefixed_hash("c"),
        mapping_record_digest=_prefixed_hash("d"),
        mapping_recorded_at=mapping_recorded_at,
        response_completed_at=reference_at,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(activated_at, snapshot_recorded_at, mapping_recorded_at),
        identity_valid_until=reference_at + timedelta(hours=1),
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    runtime = provenance or _binding(as_of).provenance
    selection = CurrentReferenceSelectionV1(
        purpose=selector.purpose,
        profile_id=runtime.profile_id,
        profile_key=runtime.profile_key,
        environment=runtime.runtime_environment,
        profile_version=runtime.profile_version,
        profile_content_hash=runtime.profile_content_hash,
        runtime_snapshot_id=runtime.snapshot_id,
        runtime_snapshot_hash=runtime.snapshot_content_hash,
        selector_content_hash=selector.content_hash,
        profile_activated_at=runtime.profile_activated_at,
        runtime_snapshot_generated_at=runtime.snapshot_generated_at,
        selected_at=as_of,
        max_local_reference_age_seconds=selector.max_local_reference_age_seconds,
    )
    identity = ExecutionInstrumentIdentityEvidenceV2(
        source_evidence=source,
        selection=selection,
        source_occurrence_id=_OCCURRENCE_ID,
        reference_response_completed_at=reference_at,
    )
    return SimulatedInstrumentClassificationEvidenceV1(
        selector=selector,
        identity_evidence=identity,
        read_at=as_of,
    )


def _calendar(
    as_of: datetime = _AS_OF,
    *,
    timezone_name: str = "Asia/Shanghai",
    covered_days: int = 3,
    end_before_today: bool = False,
    closed_dates: frozenset[date] = frozenset(),
) -> ExecutionCalendarEvidence:
    """Create full explicit, formally published calendar evidence around the cutoff."""

    local_today = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
    coverage_end = local_today - timedelta(days=1) if end_before_today else local_today
    start = coverage_end - timedelta(days=covered_days - 1)
    prior_open = start - timedelta(days=1)
    day_rows: list[ExchangeCalendarDay] = []
    for offset in range(covered_days):
        calendar_date = start + timedelta(days=offset)
        is_open = calendar_date not in closed_dates
        day_rows.append(
            ExchangeCalendarDay(
                exchange=_SOURCE_EXCHANGE,
                calendar_date=calendar_date,
                is_open=is_open,
                previous_open_date=prior_open,
            )
        )
        if is_open:
            prior_open = calendar_date

    response_completed_at = as_of - timedelta(hours=3)
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="66666666-6666-4666-8666-666666666666",
        exchange=_SOURCE_EXCHANGE,
        coverage_start=day_rows[0].calendar_date,
        coverage_end=day_rows[-1].calendar_date,
        days=tuple(day_rows),
        provider_name="fixture-calendar-provider",
        raw_reference=RawCalendarReference(
            payload_id="77777777-7777-4777-8777-777777777777",
            payload_hash=_prefixed_hash("1"),
            record_digest=_prefixed_hash("2"),
            body_sha256=_hash("3"),
            retained_content_sha256=_hash("3"),
            request_scope_sha256=_hash("4"),
            original_body_retained=True,
            response_completed_at=response_completed_at,
            provider_name="fixture-calendar-provider",
            dataset_key="trade_cal",
            transport="direct",
        ),
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=as_of - timedelta(hours=2),
        source_published_at=None,
    )
    publication = CalendarPublicationReference(
        publication_id="fixture-calendar-publication",
        member_id=snapshot.snapshot_id,
        publication_hash=_hash("5"),
        fact_content_hash=_hash("6"),
        policy_hash=_hash("7"),
        published_at=as_of - timedelta(hours=1),
        recorded_at=as_of - timedelta(minutes=50),
        reference_valid_from=as_of - timedelta(days=1),
        reference_valid_until=as_of + timedelta(days=1),
        timezone_name=timezone_name,
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _source_evidence(
    as_of: datetime = _AS_OF,
    *,
    trade_date: date | None = None,
    source_published_at: datetime | None = None,
    **changes: object,
) -> PublishedPriceSourceEvidence:
    """Construct the exact public price-source evidence DTO consumed by the reader."""

    selected_date = trade_date or as_of.astimezone(UTC).date() - timedelta(days=1)
    observed_at = cn_market_session_close_utc(selected_date)
    completed_at = as_of - timedelta(minutes=40)
    publication_as_of = as_of - timedelta(minutes=30)
    published_at = as_of - timedelta(minutes=20)
    body = b'{"code":"fixture"}'
    body_hash = sha256(body).hexdigest()
    payload_hash = f"sha256:{_hash('8')}"
    payload_reference = ProviderResponsePayloadReference(
        payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
        payload_hash=payload_hash,
        record_digest=f"sha256:{_hash('9')}",
        body_sha256=body_hash,
        retained_content_sha256=body_hash,
        original_body_retained=True,
        retained_content_encoding="exact_original_utf8_json",
        body_size_bytes=len(body),
        response_completed_at=completed_at,
        provider_name="tushare",
        dataset_key="equity.price.bar",
        transport=ProviderResponseTransport.DIRECT,
        run_id=_RUN_ID,
    )
    raw_audit_reference = CandidateRawAuditReference(
        raw_audit_id="1",
        version=RAW_AUDIT_REFERENCE_VERSION,
        content_hash=_hash("a"),
        provider_name="tushare",
        capability="historical_price",
        run_id=_RUN_ID,
        ingested_run_id=_INGESTED_RUN_ID,
    )
    values = ExactPriceBarValues(
        open=Decimal("10.12"),
        high=Decimal("10.38"),
        low=Decimal("10.01"),
        close=Decimal("10.27"),
        volume=Decimal("120000"),
        amount=Decimal("1232400"),
    )
    fields: dict[str, object] = {
        "publication_id": "fixture-price-publication",
        "publication_hash": _hash("b"),
        "publication_key": _POLICY_KEY,
        "manifest_id": "fixture-price-manifest",
        "manifest_hash": _hash("c"),
        "member_id": "fixture-price-member",
        "fact_pk": "321",
        "fact_content_hash": _hash("d"),
        "asset_code": _ASSET_CODE,
        "trade_date": selected_date,
        "values": values,
        "adjustment": PriceAdjustment.NONE,
        "source": "tushare",
        "observed_at": observed_at,
        "available_at": completed_at,
        "source_published_at": source_published_at,
        "fact_recorded_at": max(observed_at, as_of - timedelta(hours=2)),
        "publication_as_of": publication_as_of,
        "publication_published_at": published_at,
        "knowledge_cutoff": as_of,
        "raw_audit_reference": raw_audit_reference,
        "raw_payload_reference": payload_reference,
    }
    fields.update(changes)
    return PublishedPriceSourceEvidence(**fields)  # type: ignore[arg-type]


class _PolicyReader:
    """Return a fixed sequence of runtime-bound policy reads."""

    def __init__(self, bindings: tuple[InitialPositionMarkPolicyBinding | None, ...]) -> None:
        self.bindings = bindings
        self.calls: list[datetime] = []

    def read_policy(self, *, as_of: datetime) -> InitialPositionMarkPolicyBinding | None:
        """Record the exact cutoff and replay the final configured sequence value."""

        self.calls.append(as_of)
        index = min(len(self.calls) - 1, len(self.bindings) - 1)
        return self.bindings[index]


class _ClassificationReader:
    """Return one exact classification receipt while recording its requested identity."""

    def __init__(self, classification: SimulatedInstrumentClassificationEvidenceV1 | None) -> None:
        self.classification = classification
        self.calls: list[tuple[str, str, datetime]] = []

    def resolve_simulated_instrument_classification(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> SimulatedInstrumentClassificationEvidenceV1 | None:
        """Record the exact request before returning configured evidence."""

        self.calls.append((security_id, asset_code, as_of))
        return self.classification


class _CalendarReader:
    """Return one formal calendar publication and record all requested scopes."""

    def __init__(self, evidence: ExecutionCalendarEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, datetime, date | None]] = []

    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: date | None
    ) -> ExecutionCalendarEvidence | None:
        """Record the requested exchange, cutoff, and explicit coverage boundary."""

        self.calls.append((exchange, as_of, coverage_start))
        return self.evidence


class _PriceSourceReader:
    """Return one verified public price-source result and retain the request tuple."""

    def __init__(self, result: PublishedPriceSourceResult) -> None:
        self.result = result
        self.calls: list[tuple[str, date, datetime, str]] = []

    def __call__(
        self,
        asset_code: str,
        *,
        trade_date: date,
        knowledge_cutoff: datetime,
        publication_key: str,
    ) -> PublishedPriceSourceResult:
        """Record the precise source query before returning its configured outcome."""

        self.calls.append((asset_code, trade_date, knowledge_cutoff, publication_key))
        return self.result


def _reader(
    *,
    as_of: datetime = _AS_OF,
    policy_reader: _PolicyReader | None = None,
    classification_reader: _ClassificationReader | None = None,
    calendar_reader: _CalendarReader | None = None,
    price_source_reader: _PriceSourceReader | None = None,
) -> tuple[
    PublishedPriceInitialPositionMarkReader,
    _PolicyReader,
    _ClassificationReader,
    _CalendarReader,
    _PriceSourceReader,
]:
    """Compose the pure reader from four fake ports and expose their read traces."""

    policies = policy_reader or _PolicyReader((_binding(as_of), _binding(as_of)))
    classifications = classification_reader or _ClassificationReader(_classification(as_of))
    calendars = calendar_reader or _CalendarReader(_calendar(as_of))
    price_sources = price_source_reader or _PriceSourceReader(
        PublishedPriceSourceResult(_source_evidence(as_of), "", "fresh")
    )
    return (
        PublishedPriceInitialPositionMarkReader(
            policy_reader=policies,
            classification_reader=classifications,
            calendar_reader=calendars,
            get_price_source=price_sources,
        ),
        policies,
        classifications,
        calendars,
        price_sources,
    )


def _read(
    reader: PublishedPriceInitialPositionMarkReader,
    *,
    as_of: datetime = _AS_OF,
    security_id: str = _SECURITY_ID,
    asset_code: str = _ASSET_CODE,
    asset_type: str = _ASSET_TYPE,
    market: str = _RULE_MARKET,
    board: str = _BOARD,
) -> InitialPositionMarkProof | None:
    """Call the public reader port with one explicit five-field identity."""

    return reader.read_initial_position_mark(
        security_id=security_id,
        asset_code=asset_code,
        asset_type=asset_type,
        market=market,
        board=board,
        read_at=as_of,
    )


def test_policy_payload_is_exact_and_policy_hash_is_derived_from_all_fields() -> None:
    """Policy round-trips without accepting a caller-supplied hash or hidden defaults."""

    policy = _policy()

    assert policy.to_payload() == {
        "schema_version": _LEGACY_POLICY_SCHEMA,
        "purpose": "apply_time_initial_position_mark",
        "policy_id": "first-buy-mark-policy",
        "version": "v7",
        "publication_key": _POLICY_KEY,
        "source": "tushare",
        "frequency": "1d",
        "adjustment": "none",
        "supported_asset_types": [_ASSET_TYPE],
        "freshness_window_seconds": 86400,
    }
    restored = InitialPositionMarkPolicy.from_payload(policy.to_payload())
    assert restored == policy
    assert restored.observation_basis == "legacy_source_observed"
    assert restored.content_hash == policy.content_hash
    assert policy.content_hash == "7397c2b123d5e8228a7d57d70d83c4ee1bcdb984297e36908fdef1365c2f2123"
    expected_hash = sha256(
        json.dumps(
            policy.to_payload(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert policy.content_hash == expected_hash
    assert _policy(freshness_window_seconds=86401).content_hash != policy.content_hash
    assert _policy(publication_key="another-explicit-reference").content_hash != policy.content_hash


def test_daily_policy_requires_and_seals_its_observation_basis() -> None:
    """Daily policy is a distinct schema and never infers its basis from missing data."""

    daily = _daily_policy()
    payload = daily.to_payload()

    assert payload["schema_version"] == _DAILY_POLICY_SCHEMA
    assert payload["observation_basis"] == "daily_interval_end"
    restored = InitialPositionMarkPolicy.from_payload(payload)
    assert restored == daily
    assert restored.content_hash == daily.content_hash
    expected_hash = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert daily.content_hash == expected_hash

    incomplete = dict(payload)
    del incomplete["observation_basis"]
    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicy.from_payload(incomplete)
    wrong_basis = dict(payload)
    wrong_basis["observation_basis"] = "legacy_source_observed"
    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicy.from_payload(wrong_basis)
    with pytest.raises(InitialPositionMarkValidationError):
        _policy(schema_version=_DAILY_POLICY_SCHEMA)
    with pytest.raises(InitialPositionMarkValidationError):
        _daily_policy(observation_basis="legacy_source_observed")

    class DailyBasis(StrEnum):
        DAILY_INTERVAL_END = "daily_interval_end"

    with pytest.raises(InitialPositionMarkValidationError):
        _daily_policy(observation_basis=DailyBasis.DAILY_INTERVAL_END)


@pytest.mark.parametrize(
    "changes",
    (
        {"purpose": "normal_simulated_current_reference"},
        {"publication_key": "m1-rebalance-reference"},
        {"adjustment": "forward"},
        {"frequency": "1m"},
        {"supported_asset_types": ()},
        {"freshness_window_seconds": True},
        {"freshness_window_seconds": 0},
    ),
)
def test_policy_rejects_wrong_purpose_or_incomplete_qualification(
    changes: dict[str, object],
) -> None:
    """The policy never inherits authority from a selector or the M1 lane."""

    with pytest.raises(ValueError):
        _policy(**changes)


def test_policy_decoder_rejects_unknown_and_missing_json_fields() -> None:
    """Policy decoding requires the exact versioned public JSON schema."""

    payload = _policy().to_payload()
    with pytest.raises(ValueError):
        InitialPositionMarkPolicy.from_payload({**payload, "caller_hash": _hash("f")})
    missing = dict(payload)
    del missing["adjustment"]
    with pytest.raises(ValueError):
        InitialPositionMarkPolicy.from_payload(missing)


def test_policy_rejects_unsupported_schema_version() -> None:
    """The policy constructor cannot silently interpret an unknown schema version."""

    with pytest.raises(InitialPositionMarkValidationError):
        _policy(schema_version="simulated-initial-position-mark-policy.v2")


def test_policy_decoder_rejects_non_object_payload() -> None:
    """The runtime boundary must provide one JSON object before field access."""

    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicy.from_payload(("not", "an", "object"))


@pytest.mark.parametrize(
    "field_name,value",
    (
        ("supported_asset_types", (_ASSET_TYPE,)),
        ("supported_asset_types", [_ASSET_TYPE, True]),
        ("freshness_window_seconds", True),
    ),
)
def test_policy_decoder_rejects_invalid_collection_and_integer_types(
    field_name: str, value: object
) -> None:
    """The exact JSON shape uses a string array and a non-boolean integer window."""

    payload = _policy().to_payload()
    payload[field_name] = value

    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicy.from_payload(payload)


def test_policy_decoder_rejects_non_string_text_field() -> None:
    """Every policy identity and source field must decode as exact text."""

    payload = _policy().to_payload()
    payload["purpose"] = 17

    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicy.from_payload(payload)


def test_reader_blocks_daily_price_evidence_when_only_legacy_policy_is_active() -> None:
    """A decoded v1 policy cannot acquire daily-interval meaning from new evidence."""

    evidence = _source_evidence()
    assert evidence.observation_basis == "daily_interval_end"
    assert evidence.interval_end_at == evidence.observed_at
    assert evidence.source_observed_at is None
    assert evidence.local_known_at == evidence.available_at
    legacy_binding = _binding(policy=_policy())
    reader, _, classifications, calendars, prices = _reader(
        policy_reader=_PolicyReader((legacy_binding, legacy_binding)),
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh")),
    )

    assert _read(reader) is None
    assert classifications.calls == []
    assert calendars.calls == []
    assert prices.calls == []


def test_runtime_policy_binding_hash_covers_profile_snapshot_and_read_clocks() -> None:
    """A stable policy value with different active provenance receives another proof seal."""

    binding = _binding()
    changed = _binding(
        provenance_changes={"snapshot_content_hash": _hash("c")},
    )

    assert binding.proof_content_hash != changed.proof_content_hash
    assert (
        binding.proof_content_hash
        != _binding(
            provenance_changes={"profile_version": 8},
        ).proof_content_hash
    )


def test_runtime_policy_binding_requires_verified_effective_and_active_clocks() -> None:
    """Missing or divergent profile/snapshot chronology cannot seal a mark policy."""

    with pytest.raises(ValueError):
        _binding(provenance_changes={"snapshot_effective_from": None})
    with pytest.raises(ValueError):
        _binding(provenance_changes={"snapshot_effective_from": _AS_OF - timedelta(hours=3)})
    with pytest.raises(ValueError):
        _binding(provenance_changes={"snapshot_generated_at": _AS_OF + timedelta(seconds=1)})


def test_runtime_provenance_rejects_nonpositive_or_boolean_profile_version() -> None:
    """Runtime profile versions are positive exact integers, not booleans."""

    with pytest.raises(InitialPositionMarkValidationError):
        _binding(provenance_changes={"profile_version": True})
    with pytest.raises(InitialPositionMarkValidationError):
        _binding(provenance_changes={"profile_version": 0})


def test_policy_binding_rejects_invalid_nested_runtime_or_policy_types() -> None:
    """A binding must contain the two exact immutable domain values."""

    provenance = _binding().provenance
    policy = _policy()
    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicyBinding(policy=object(), provenance=provenance)  # type: ignore[arg-type]
    with pytest.raises(InitialPositionMarkValidationError):
        InitialPositionMarkPolicyBinding(policy=policy, provenance=object())  # type: ignore[arg-type]


def test_policy_binding_validation_requires_the_exact_requested_read_cutoff() -> None:
    """A provenance receipt from a different cutoff cannot be re-used."""

    binding = _binding()
    with pytest.raises(InitialPositionMarkValidationError):
        binding.validate_at(as_of=_AS_OF + timedelta(seconds=1))


def test_reader_maps_verified_source_to_first_position_mark_and_preserves_unknown_clock() -> None:
    """The proof binds source identity, publication, policy and exact close without local substitution."""

    reader, policies, classifications, calendars, prices = _reader()

    proof = _read(reader)

    assert type(proof) is InitialPositionMarkProof
    assert proof is not None
    source = prices.result.evidence
    assert source is not None
    assert proof.security_id == _SECURITY_ID
    assert proof.asset_code == _ASSET_CODE
    assert proof.asset_type == _ASSET_TYPE
    assert proof.market == _RULE_MARKET
    assert proof.board == _BOARD
    assert proof.price == source.values.close
    assert proof.observation_basis == "daily_interval_end"
    assert proof.source_observed_at is None
    assert proof.interval_end_at == source.interval_end_at
    assert proof.local_known_at == source.local_known_at
    assert proof.source_available_at is None
    assert proof.read_at == _AS_OF
    assert proof.publication_as_of == source.publication_as_of
    assert proof.published_at == source.publication_published_at
    assert proof.valid_until == source.interval_end_at + timedelta(seconds=86400)
    assert proof.freshness_window_seconds == 86400
    assert proof.source_identity == source.source
    assert proof.source_record_id == source.fact_pk
    assert proof.source_content_hash == source.fact_content_hash
    assert proof.publication_id == source.publication_id
    assert proof.publication_hash == source.publication_hash
    assert proof.policy_identity == _daily_policy().identity
    initial_binding = policies.bindings[0]
    assert initial_binding is not None
    assert proof.policy_content_hash == initial_binding.proof_content_hash
    assert policies.calls == [_AS_OF, _AS_OF]
    assert classifications.calls == [(_SECURITY_ID, _ASSET_CODE, _AS_OF)]
    assert calendars.calls == [(_SOURCE_EXCHANGE, _AS_OF, None)]
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 27), _AS_OF, _POLICY_KEY)]


def test_reader_uses_only_provider_source_publication_time_for_source_availability() -> None:
    """A known upstream publication clock is retained; local response completion is ignored."""

    provider_time = cn_market_session_close_utc(date(2026, 10, 27)) + timedelta(minutes=2)
    evidence = _source_evidence(source_published_at=provider_time)
    reader, _, _, _, _ = _reader(
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh"))
    )

    proof = _read(reader)

    assert proof is not None
    assert proof.source_available_at == provider_time
    assert proof.source_available_at != evidence.available_at


def test_reader_blocks_provider_publication_after_local_response_completion() -> None:
    """A supplier clock later than the verified local response cannot be retained as known."""

    local_known_at = _AS_OF - timedelta(minutes=40)
    evidence = _source_evidence(
        source_published_at=local_known_at + timedelta(seconds=1),
    )
    reader, _, _, _, _ = _reader(
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh"))
    )

    assert _read(reader) is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("security_id", "different-security"),
        ("asset_code", "000001.SZ"),
        ("asset_type", "unconfigured_type"),
        ("market", "different-market"),
        ("board", "different-board"),
    ),
)
def test_reader_blocks_each_requested_identity_field_that_differs_from_source_classification(
    field_name: str, value: str
) -> None:
    """No requested identity field is echoed into a proof when source classification disagrees."""

    reader, _, _, _, prices = _reader()
    request = {
        "security_id": _SECURITY_ID,
        "asset_code": _ASSET_CODE,
        "asset_type": _ASSET_TYPE,
        "market": _RULE_MARKET,
        "board": _BOARD,
    }
    request[field_name] = value

    assert _read(reader, **request) is None
    assert prices.calls == []


def test_reader_blocks_policy_profile_or_snapshot_drift_between_reads() -> None:
    """A mid-read runtime profile or snapshot switch cannot produce a proof."""

    first = _binding()
    second = _binding(provenance_changes={"snapshot_id": "replacement-snapshot"})
    reader, policies, _, _, _ = _reader(policy_reader=_PolicyReader((first, second)))

    assert _read(reader) is None
    assert policies.calls == [_AS_OF, _AS_OF]


def test_reader_blocks_daily_policy_content_change_between_reads() -> None:
    """A daily observation basis and freshness window stay bound across the source read."""

    first = _binding(policy=_daily_policy())
    second = _binding(policy=_daily_policy(freshness_window_seconds=172800))
    reader, policies, _, _, prices = _reader(policy_reader=_PolicyReader((first, second)))

    assert _read(reader) is None
    assert policies.calls == [_AS_OF, _AS_OF]
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 27), _AS_OF, _POLICY_KEY)]


@pytest.mark.parametrize(
    "provenance_changes",
    (
        {"profile_id": "other-profile"},
        {"profile_key": "other-profile-key"},
        {"runtime_environment": "production"},
        {"profile_version": 8},
        {"profile_content_hash": _hash("c")},
        {"snapshot_id": "other-snapshot"},
        {"snapshot_content_hash": _hash("d")},
        {
            "profile_activated_at": _AS_OF - timedelta(hours=6),
            "snapshot_effective_from": _AS_OF - timedelta(hours=6),
        },
        {"snapshot_generated_at": _AS_OF - timedelta(hours=3)},
    ),
)
def test_reader_blocks_classification_from_a_different_active_runtime_identity(
    provenance_changes: dict[str, object],
) -> None:
    """A policy A→B→A read cannot seal classification facts captured under runtime B."""

    other_runtime = _binding(provenance_changes=provenance_changes).provenance
    reader, _, _, calendars, prices = _reader(
        classification_reader=_ClassificationReader(_classification(provenance=other_runtime))
    )

    assert _read(reader) is None
    assert calendars.calls == []
    assert prices.calls == []


def test_reader_blocks_when_runtime_policy_is_missing() -> None:
    """A missing policy stops before classification, calendar or price reads."""

    reader, _, classifications, calendars, prices = _reader(policy_reader=_PolicyReader((None,)))

    assert _read(reader) is None
    assert classifications.calls == []
    assert calendars.calls == []
    assert prices.calls == []


def test_reader_blocks_runtime_policy_bound_to_a_different_cutoff() -> None:
    """A valid binding at another cutoff cannot be reused for this mark request."""

    other_cutoff = _AS_OF - timedelta(seconds=1)
    reader, _, classifications, calendars, prices = _reader(
        policy_reader=_PolicyReader((_binding(other_cutoff), _binding(other_cutoff)))
    )

    assert _read(reader) is None
    assert classifications.calls == []
    assert calendars.calls == []
    assert prices.calls == []


def test_reader_rejects_invalid_caller_identity_before_any_external_read() -> None:
    """Malformed scope is stopped before runtime, identity, calendar, or price reads."""

    reader, policies, classifications, calendars, prices = _reader()

    assert _read(reader, security_id="invalid security token") is None
    assert policies.calls == []
    assert classifications.calls == []
    assert calendars.calls == []
    assert prices.calls == []


def test_reader_blocks_when_source_classification_is_missing() -> None:
    """The requested identity is never used to fill absent source identity evidence."""

    reader, _, _, calendars, prices = _reader(classification_reader=_ClassificationReader(None))

    assert _read(reader) is None
    assert calendars.calls == []
    assert prices.calls == []


def test_reader_blocks_when_published_calendar_does_not_cover_the_cutoff_local_date() -> None:
    """An older calendar cannot be treated as coverage for the current exchange date."""

    calendar = _calendar(covered_days=2, end_before_today=True)
    reader, _, _, _, prices = _reader(calendar_reader=_CalendarReader(calendar))

    assert _read(reader) is None
    assert prices.calls == []


def test_reader_blocks_non_china_calendar_timezone() -> None:
    """The A-share close calculation requires the formal calendar's China timezone."""

    calendar = _calendar(timezone_name="Asia/Tokyo")
    reader, _, _, _, prices = _reader(calendar_reader=_CalendarReader(calendar))

    assert _read(reader) is None
    assert prices.calls == []


def test_reader_uses_previous_closed_session_during_an_open_intraday_session() -> None:
    """A current open session before 15:00 China resolves to the prior closed session."""

    as_of = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)
    evidence = _source_evidence(as_of, trade_date=date(2026, 10, 27))
    reader, _, _, _, prices = _reader(
        as_of=as_of,
        policy_reader=_PolicyReader((_binding(as_of), _binding(as_of))),
        classification_reader=_ClassificationReader(_classification(as_of)),
        calendar_reader=_CalendarReader(_calendar(as_of)),
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh")),
    )

    assert _read(reader, as_of=as_of) is not None
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 27), as_of, _POLICY_KEY)]


def test_reader_uses_current_session_after_formal_close_when_its_bar_is_published() -> None:
    """After 15:00 China, an available current-session bar is the selected daily close."""

    as_of = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
    evidence = _source_evidence(as_of, trade_date=date(2026, 10, 28))
    reader, _, _, _, prices = _reader(
        as_of=as_of,
        policy_reader=_PolicyReader((_binding(as_of), _binding(as_of))),
        classification_reader=_ClassificationReader(_classification(as_of)),
        calendar_reader=_CalendarReader(_calendar(as_of)),
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh")),
    )

    proof = _read(reader, as_of=as_of)

    assert proof is not None
    assert proof.source_observed_at is None
    assert proof.interval_end_at == cn_market_session_close_utc(date(2026, 10, 28))
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 28), as_of, _POLICY_KEY)]


def test_reader_uses_last_open_session_when_the_cutoff_date_is_a_published_holiday() -> None:
    """An explicit closed-day fact allows the prior open session without weekday inference."""

    as_of = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
    evidence = _source_evidence(as_of, trade_date=date(2026, 10, 27))
    holiday_binding = _binding(as_of, policy=_daily_policy(freshness_window_seconds=172800))
    reader, _, _, _, prices = _reader(
        as_of=as_of,
        policy_reader=_PolicyReader((holiday_binding, holiday_binding)),
        classification_reader=_ClassificationReader(_classification(as_of)),
        calendar_reader=_CalendarReader(
            _calendar(as_of, closed_dates=frozenset({date(2026, 10, 28)}))
        ),
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh")),
    )

    proof = _read(reader, as_of=as_of)

    assert proof is not None
    assert proof.source_observed_at is None
    assert proof.interval_end_at == cn_market_session_close_utc(date(2026, 10, 27))
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 27), as_of, _POLICY_KEY)]


def test_reader_does_not_fall_back_when_latest_closed_session_price_is_missing() -> None:
    """After today's close, an absent today's bar blocks without requesting yesterday."""

    as_of = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
    reader, _, _, _, prices = _reader(
        as_of=as_of,
        policy_reader=_PolicyReader((_binding(as_of), _binding(as_of))),
        classification_reader=_ClassificationReader(_classification(as_of)),
        calendar_reader=_CalendarReader(_calendar(as_of)),
        price_source_reader=_PriceSourceReader(
            PublishedPriceSourceResult(None, "price_source_fact_missing_or_ambiguous")
        ),
    )

    assert _read(reader, as_of=as_of) is None
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 28), as_of, _POLICY_KEY)]


@pytest.mark.parametrize(
    "changes",
    (
        {"trade_date": date(2026, 10, 26)},
        {"publication_key": "another-reference"},
        {"source": "another-provider"},
        {"adjustment": PriceAdjustment.FORWARD},
        {"publication_as_of": _AS_OF + timedelta(seconds=1)},
        {"publication_published_at": _AS_OF + timedelta(seconds=1)},
        {"available_at": _AS_OF + timedelta(seconds=1)},
        {"source_published_at": _AS_OF + timedelta(seconds=1)},
        {"observed_at": cn_market_session_close_utc(date(2026, 10, 27)) + timedelta(seconds=1)},
    ),
)
def test_reader_blocks_price_evidence_with_mismatched_scope_or_future_clocks(
    changes: dict[str, object],
) -> None:
    """Price identity, no-adjustment semantics, and every known clock stay within the cutoff."""

    evidence = _source_evidence(**changes)
    reader, _, _, _, _ = _reader(
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "fresh"))
    )

    assert _read(reader) is None


def test_reader_blocks_expired_freshness_policy_deadline() -> None:
    """An explicit mark TTL must still be current at the exact apply-time cutoff."""

    stale_policy = _daily_policy(freshness_window_seconds=30)
    binding = _binding(policy=stale_policy)
    reader, _, _, _, _ = _reader(policy_reader=_PolicyReader((binding, binding)))

    assert _read(reader) is None


def test_reader_ttl_starts_at_interval_end_not_local_response_completion() -> None:
    """A recent fetch cannot refresh a daily mark whose interval-end TTL has expired."""

    binding = _binding(policy=_daily_policy(freshness_window_seconds=3600))
    reader, _, _, _, prices = _reader(policy_reader=_PolicyReader((binding, binding)))

    assert _read(reader) is None
    assert prices.calls == [(_ASSET_CODE, date(2026, 10, 27), _AS_OF, _POLICY_KEY)]


def test_reader_blocks_an_unavailable_price_publication() -> None:
    """A blocked exact-source result cannot be converted into a mark from local state."""

    reader, _, _, _, _ = _reader(
        price_source_reader=_PriceSourceReader(
            PublishedPriceSourceResult(None, "price_source_not_known")
        )
    )

    assert _read(reader) is None


def test_reader_blocks_unacceptable_price_freshness_status() -> None:
    """Only the current fresh or formally completed-session source states can support a mark."""

    evidence = _source_evidence()
    reader, _, _, _, _ = _reader(
        price_source_reader=_PriceSourceReader(PublishedPriceSourceResult(evidence, "", "stale"))
    )

    assert _read(reader) is None


def test_policy_binding_hash_is_recomputed_after_payload_mutation() -> None:
    """The proof seal is calculated from current typed policy and runtime evidence."""

    binding = _binding()
    before = binding.proof_content_hash
    changed_policy = _policy(version="v8")
    changed_binding = replace(binding, policy=changed_policy)

    assert changed_binding.proof_content_hash != before
