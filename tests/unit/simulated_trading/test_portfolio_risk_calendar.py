"""Focused contracts for current-exchange and published-calendar qualification."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
    PortfolioRiskCalendarReadRequest,
    PortfolioRiskCalendarReadResult,
    build_portfolio_risk_calendar_reader,
)
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
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

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
_REQUESTED_SESSION = date(2026, 11, 3)


def _hash(character: str) -> str:
    """Return one deterministic lowercase digest for a fixture field."""

    return character * 64


def _identity(
    *,
    asset_code: str,
    security_id: str,
    exchange: str,
    seed: int,
    as_of: datetime = _AS_OF,
    restricted: bool = False,
) -> ExecutionInstrumentIdentityEvidenceV2:
    """Create an exact current-reference receipt with genuine exchange scope."""

    profile_activated_at = as_of - timedelta(hours=2)
    selection = CurrentReferenceSelectionV1(
        purpose="normal_simulated_current_reference",
        profile_id=f"fixture-profile-{seed}",
        profile_key="config_center.market.simulated_current_reference_selection",
        environment="development",
        profile_version=1,
        profile_content_hash=_hash("a"),
        runtime_snapshot_id=f"fixture-runtime-snapshot-{seed}",
        runtime_snapshot_hash=_hash("b"),
        selector_content_hash=_hash("c"),
        profile_activated_at=profile_activated_at,
        runtime_snapshot_generated_at=as_of - timedelta(hours=1),
        selected_at=as_of,
        max_local_reference_age_seconds=3600,
    )
    response_completed_at = as_of - timedelta(minutes=10)
    snapshot_recorded_at = as_of - timedelta(minutes=5)
    mapping_recorded_at = as_of - timedelta(minutes=6)
    identity = ExecutionInstrumentIdentityEvidenceV1(
        security_id=security_id,
        asset_code=asset_code,
        source_code=f"source-{seed}",
        source_exchange=exchange,
        source_market="FIXTURE_MAIN",
        rule_market="FIXTURE_MAIN",
        board="FIXTURE_MAIN",
        snapshot_id=UUID(int=1000 + seed),
        snapshot_content_hash=f"sha256:{_hash('d')}",
        snapshot_record_digest=f"sha256:{_hash('e')}",
        first_seen_at=response_completed_at,
        snapshot_recorded_at=snapshot_recorded_at,
        mapping_record_id=UUID(int=2000 + seed),
        mapping_id=f"fixture-mapping-{seed}",
        mapping_version="v1",
        mapping_content_hash=f"sha256:{_hash('f')}",
        mapping_record_digest=f"sha256:{_hash('1')}",
        mapping_recorded_at=mapping_recorded_at,
        response_completed_at=response_completed_at,
        source_observed_at=as_of - timedelta(minutes=12),
        source_available_at=as_of - timedelta(minutes=11),
        identity_valid_from=max(
            profile_activated_at,
            snapshot_recorded_at,
            mapping_recorded_at,
        ),
        identity_valid_until=response_completed_at + timedelta(hours=1),
        must_not_use_for_decision=restricted,
        must_not_execute=restricted,
    )
    return ExecutionInstrumentIdentityEvidenceV2(
        source_evidence=identity,
        selection=selection,
        source_occurrence_id=UUID(int=3000 + seed),
        reference_response_completed_at=response_completed_at,
    )


def _calendar(
    *,
    exchange: str,
    seed: int,
    as_of: datetime = _AS_OF,
    closed_dates: frozenset[date] = frozenset(),
    valid_until: datetime | None = None,
) -> ExecutionCalendarEvidence:
    """Create retained daily facts and an exact publication-member receipt."""

    coverage_start = _REQUESTED_SESSION - timedelta(days=1)
    coverage_end = _REQUESTED_SESSION + timedelta(days=1)
    day_rows: list[ExchangeCalendarDay] = []
    prior_open = coverage_start - timedelta(days=1)
    for day_offset in range(3):
        calendar_date = coverage_start + timedelta(days=day_offset)
        is_open = calendar_date not in closed_dates
        day_rows.append(
            ExchangeCalendarDay(
                exchange=exchange,
                calendar_date=calendar_date,
                is_open=is_open,
                previous_open_date=prior_open,
            )
        )
        if is_open:
            prior_open = calendar_date

    snapshot_id = str(UUID(int=4000 + seed))
    provider_name = f"fixture-calendar-provider-{seed}"
    response_completed_at = as_of - timedelta(hours=3)
    raw_reference = RawCalendarReference(
        payload_id=str(UUID(int=5000 + seed)),
        payload_hash=f"sha256:{_hash('2')}",
        record_digest=f"sha256:{_hash('3')}",
        body_sha256=_hash("4"),
        retained_content_sha256=_hash("4"),
        request_scope_sha256=_hash("5"),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name=provider_name,
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id=snapshot_id,
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=tuple(day_rows),
        provider_name=provider_name,
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=as_of - timedelta(hours=2),
    )
    publication = CalendarPublicationReference(
        publication_id=f"fixture-publication-{seed}",
        member_id=snapshot_id,
        publication_hash=_hash("6"),
        fact_content_hash=snapshot.content_hash.removeprefix("sha256:"),
        policy_hash=_hash("7"),
        published_at=as_of - timedelta(hours=1),
        recorded_at=as_of - timedelta(minutes=50),
        reference_valid_from=as_of - timedelta(days=1),
        reference_valid_until=(
            valid_until if valid_until is not None else as_of + timedelta(days=1)
        ),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


class _IdentityReader:
    """Return exact fixture identities and preserve every requested lookup."""

    def __init__(
        self,
        identities: dict[tuple[str, str], ExecutionInstrumentIdentityEvidenceV2 | None],
    ) -> None:
        self.identities = identities
        self.calls: list[tuple[str, str, datetime]] = []

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Read an exact pair without deriving a source exchange from its code."""

        self.calls.append((asset_code, security_id, as_of))
        return self.identities.get((asset_code, security_id))


class _CalendarReader:
    """Return exact published calendars and retain their requested scope."""

    def __init__(self, calendars: dict[str, ExecutionCalendarEvidence | None]) -> None:
        self.calendars = calendars
        self.calls: list[tuple[str, datetime, date | None]] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Return one exact published exchange calendar at the requested cutoff."""

        self.calls.append((exchange, as_of, coverage_start))
        return self.calendars.get(exchange)


def _read(
    *,
    assets: tuple[PortfolioRiskAssetIdentity, ...],
    identities: dict[tuple[str, str], ExecutionInstrumentIdentityEvidenceV2 | None],
    calendars: dict[str, ExecutionCalendarEvidence | None],
    as_of: datetime = _AS_OF,
) -> tuple[PortfolioRiskCalendarReadResult, _IdentityReader, _CalendarReader]:
    """Run the public application reader with two injected read-only ports."""

    identity_reader = _IdentityReader(identities)
    calendar_reader = _CalendarReader(calendars)
    reader: PortfolioRiskCalendarReader = build_portfolio_risk_calendar_reader(
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
    )
    result = reader.read_calendar(
        PortfolioRiskCalendarReadRequest(
            requested_assets=assets,
            requested_session=_REQUESTED_SESSION,
            as_of=as_of,
        )
    )
    return result, identity_reader, calendar_reader


def test_calendar_reader_uses_exact_source_exchange_and_intersects_published_sessions() -> None:
    """Two source-mapped exchanges qualify only from their common explicit dates."""

    assets = (
        PortfolioRiskAssetIdentity(asset_code="600036", security_id="SSE:600036"),
        PortfolioRiskAssetIdentity(asset_code="000001", security_id="SZSE:000001"),
    )
    sse = _identity(
        asset_code="600036",
        security_id="SSE:600036",
        exchange="SSE",
        seed=1,
    )
    szse = _identity(
        asset_code="000001",
        security_id="SZSE:000001",
        exchange="SZSE",
        seed=2,
    )
    sse_calendar = _calendar(exchange="SSE", seed=1)
    szse_calendar = _calendar(exchange="SZSE", seed=2)

    result, identity_reader, calendar_reader = _read(
        assets=assets,
        identities={
            ("600036", "SSE:600036"): sse,
            ("000001", "SZSE:000001"): szse,
        },
        calendars={"SSE": sse_calendar, "SZSE": szse_calendar},
    )

    assert result.requested_session_qualified is True
    assert result.reason_codes == ()
    assert result.open_sessions == tuple(
        _REQUESTED_SESSION + timedelta(days=offset) for offset in (-1, 0, 1)
    )
    assert result.valid_until == min(
        sse.source_evidence.identity_valid_until,
        szse.source_evidence.identity_valid_until,
        sse_calendar.publication.reference_valid_until,
        szse_calendar.publication.reference_valid_until,
    )
    assert result.evidence_hash is not None and len(result.evidence_hash) == 64
    assert result.canonical_evidence_json is not None
    assert '"raw_reference"' in result.canonical_evidence_json
    assert '"publication_id":"fixture-publication-1"' in result.canonical_evidence_json
    assert {call[1] for call in identity_reader.calls} == {"SSE:600036", "SZSE:000001"}
    assert {call[0] for call in calendar_reader.calls} == {"SSE", "SZSE"}
    assert all(call[2] == _REQUESTED_SESSION for call in calendar_reader.calls)


def test_calendar_session_closed_on_one_exchange_is_not_qualified() -> None:
    """An open date in one calendar cannot override a closed fact in another."""

    assets = (
        PortfolioRiskAssetIdentity(asset_code="600036", security_id="SSE:600036"),
        PortfolioRiskAssetIdentity(asset_code="000001", security_id="SZSE:000001"),
    )
    identities = {
        ("600036", "SSE:600036"): _identity(
            asset_code="600036", security_id="SSE:600036", exchange="SSE", seed=3
        ),
        ("000001", "SZSE:000001"): _identity(
            asset_code="000001", security_id="SZSE:000001", exchange="SZSE", seed=4
        ),
    }
    result, _, _ = _read(
        assets=assets,
        identities=identities,
        calendars={
            "SSE": _calendar(exchange="SSE", seed=3),
            "SZSE": _calendar(
                exchange="SZSE",
                seed=4,
                closed_dates=frozenset({_REQUESTED_SESSION}),
            ),
        },
    )

    assert result.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_SESSION_NOT_OPEN_ON_ALL_EXCHANGES" in result.reason_codes
    assert result.open_sessions == (
        _REQUESTED_SESSION - timedelta(days=1),
        _REQUESTED_SESSION + timedelta(days=1),
    )


def test_calendar_unknown_identity_or_unknown_security_never_guesses_exchange() -> None:
    """Unmapped holdings remain blocked and do not trigger ticker-based calendar reads."""

    missing_asset = PortfolioRiskAssetIdentity(
        asset_code="600036",
        security_id="SSE:600036",
    )
    missing, identity_reader, calendar_reader = _read(
        assets=(missing_asset,),
        identities={("600036", "SSE:600036"): None},
        calendars={"SSE": _calendar(exchange="SSE", seed=5)},
    )
    assert missing.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_IDENTITY_MISSING" in missing.reason_codes
    assert identity_reader.calls == [("600036", "SSE:600036", _AS_OF)]
    assert calendar_reader.calls == []

    unknown_security = PortfolioRiskAssetIdentity(asset_code="600036", security_id=None)
    unknown, identity_reader, calendar_reader = _read(
        assets=(unknown_security,),
        identities={},
        calendars={"SSE": _calendar(exchange="SSE", seed=6)},
    )
    assert unknown.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_SECURITY_ID_UNKNOWN" in unknown.reason_codes
    assert identity_reader.calls == []
    assert calendar_reader.calls == []


def test_prohibited_identity_and_expired_publication_block_with_stable_reasons() -> None:
    """Source restrictions and calendar validity are independently enforced."""

    asset = PortfolioRiskAssetIdentity(asset_code="600036", security_id="SSE:600036")
    restricted = _identity(
        asset_code="600036",
        security_id="SSE:600036",
        exchange="SSE",
        seed=7,
        restricted=True,
    )
    prohibited, _, calendar_reader = _read(
        assets=(asset,),
        identities={("600036", "SSE:600036"): restricted},
        calendars={"SSE": _calendar(exchange="SSE", seed=7)},
    )
    assert prohibited.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_IDENTITY_PROHIBITED" in prohibited.reason_codes
    assert calendar_reader.calls == []
    assert prohibited.canonical_evidence_json is not None
    assert '"must_not_execute":true' in prohibited.canonical_evidence_json

    active_identity = _identity(
        asset_code="600036",
        security_id="SSE:600036",
        exchange="SSE",
        seed=8,
    )
    expired_calendar = _calendar(
        exchange="SSE",
        seed=8,
        valid_until=_AS_OF,
    )
    expired, _, _ = _read(
        assets=(asset,),
        identities={("600036", "SSE:600036"): active_identity},
        calendars={"SSE": expired_calendar},
    )
    assert expired.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_PUBLICATION_EXPIRED" in expired.reason_codes
    assert expired.open_sessions is None
    assert expired.canonical_evidence_json is not None
    assert '"publication_id":"fixture-publication-8"' in expired.canonical_evidence_json


def test_missing_or_wrong_exchange_calendar_keeps_exact_block_reason() -> None:
    """A missing publication or a different exchange's snapshot cannot qualify."""

    asset = PortfolioRiskAssetIdentity(asset_code="600036", security_id="SSE:600036")
    identity = _identity(
        asset_code="600036",
        security_id="SSE:600036",
        exchange="SSE",
        seed=10,
    )
    identity_inputs = {(asset.asset_code, asset.security_id): identity}

    missing, _, _ = _read(
        assets=(asset,),
        identities=identity_inputs,
        calendars={"SSE": None},
    )
    assert missing.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_PUBLICATION_MISSING" in missing.reason_codes
    assert missing.open_sessions is None

    mismatched, _, _ = _read(
        assets=(asset,),
        identities=identity_inputs,
        calendars={"SSE": _calendar(exchange="SZSE", seed=10)},
    )
    assert mismatched.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_EXCHANGE_MISMATCH" in mismatched.reason_codes
    assert mismatched.open_sessions is None
    assert mismatched.canonical_evidence_json is not None
    assert '"requested_exchange":"SSE"' in mismatched.canonical_evidence_json
    assert '"exchange":"SZSE"' in mismatched.canonical_evidence_json


def test_calendar_identity_must_be_selected_at_exact_requested_cutoff() -> None:
    """A still-valid identity selected earlier cannot silently stand in for this read."""

    asset = PortfolioRiskAssetIdentity(asset_code="600036", security_id="SSE:600036")
    earlier = _AS_OF - timedelta(seconds=1)
    identity = _identity(
        asset_code="600036",
        security_id="SSE:600036",
        exchange="SSE",
        seed=9,
        as_of=earlier,
    )
    result, _, calendar_reader = _read(
        assets=(asset,),
        identities={("600036", "SSE:600036"): identity},
        calendars={"SSE": _calendar(exchange="SSE", seed=9)},
    )

    assert result.requested_session_qualified is False
    assert "PORTFOLIO_RISK_CALENDAR_IDENTITY_CUTOFF_MISMATCH" in result.reason_codes
    assert calendar_reader.calls == []
