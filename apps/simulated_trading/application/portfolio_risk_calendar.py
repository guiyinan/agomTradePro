"""Exact exchange-calendar lookup for simulated portfolio-risk contexts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
    portfolio_risk_content_hash,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    ExecutionInstrumentIdentityUnavailable,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskCalendarReadRequest:
    """The exact asset identities, requested session, and server cutoff."""

    requested_assets: tuple[PortfolioRiskAssetIdentity, ...]
    requested_session: date
    as_of: datetime

    def __post_init__(self) -> None:
        """Reject incomplete identities and any naive or datetime-as-date input."""

        if type(self.requested_assets) is not tuple or any(
            type(item) is not PortfolioRiskAssetIdentity for item in self.requested_assets
        ):
            raise TypeError("requested_assets must be a tuple of PortfolioRiskAssetIdentity")
        for item in self.requested_assets:
            item.__post_init__()
        if type(self.requested_session) is not date:
            raise TypeError("requested_session must be an exact date")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class PortfolioRiskCalendarReadResult:
    """One calendar qualification and the exact retained facts used to derive it."""

    requested_session_qualified: bool
    open_sessions: tuple[date, ...] | None
    reason_codes: tuple[str, ...]
    canonical_evidence_json: str | None
    evidence_hash: str | None
    valid_until: datetime | None

    def __post_init__(self) -> None:
        """Require exact session facts and keep partial reads explicitly unqualified."""

        if type(self.requested_session_qualified) is not bool:
            raise TypeError("requested_session_qualified must be a boolean")
        if self.open_sessions is not None:
            if type(self.open_sessions) is not tuple or any(
                type(session) is not date for session in self.open_sessions
            ):
                raise TypeError("open_sessions must be a tuple of dates or None")
            if tuple(sorted(set(self.open_sessions))) != self.open_sessions:
                raise ValueError("open_sessions must be unique and ordered")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain stable nonempty strings")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")
        if self.requested_session_qualified and (
            self.reason_codes
            or not self.open_sessions
            or self.canonical_evidence_json is None
            or self.evidence_hash is None
            or self.valid_until is None
        ):
            raise ValueError("a qualified session requires complete evidence and expiry")
        if (self.canonical_evidence_json is None) != (self.evidence_hash is None):
            raise ValueError("canonical evidence JSON and hash must be supplied together")
        if self.canonical_evidence_json is not None:
            if type(self.canonical_evidence_json) is not str or not self.canonical_evidence_json:
                raise ValueError("canonical_evidence_json must be a nonempty string")
            if type(self.evidence_hash) is not str or (
                len(self.evidence_hash) != 64
                or any(character not in "0123456789abcdef" for character in self.evidence_hash)
            ):
                raise ValueError("evidence_hash must be lowercase SHA-256 hex")
            actual_hash = hashlib.sha256(self.canonical_evidence_json.encode("utf-8")).hexdigest()
            if actual_hash != self.evidence_hash:
                raise ValueError("evidence_hash must match canonical_evidence_json")
        if self.valid_until is not None:
            _require_aware(self.valid_until, "valid_until")


class PortfolioRiskCurrentIdentityReader(Protocol):
    """Read exact current-reference identity evidence from its owning Application."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Return one current selected identity without inferring its exchange."""
        ...


class PortfolioRiskPublishedCalendarReader(Protocol):
    """Read the exact formally published calendar from its owning Application."""

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Return source-retained calendar facts for the exact exchange and cutoff."""
        ...


class PortfolioRiskCalendarReader(Protocol):
    """Public port for reading portfolio-risk session qualification and evidence."""

    def read_calendar(
        self, request: PortfolioRiskCalendarReadRequest
    ) -> PortfolioRiskCalendarReadResult:
        """Return current exact-exchange calendar facts for one risk context."""
        ...


class _ConfiguredPortfolioRiskCalendarReader:
    """Compose already configured identity and published-calendar application ports."""

    def __init__(
        self,
        *,
        identity_reader: PortfolioRiskCurrentIdentityReader,
        calendar_reader: PortfolioRiskPublishedCalendarReader,
    ) -> None:
        """Retain the two public readers without creating any infrastructure access."""

        self._identity_reader = identity_reader
        self._calendar_reader = calendar_reader

    def read_calendar(
        self, request: PortfolioRiskCalendarReadRequest
    ) -> PortfolioRiskCalendarReadResult:
        """Resolve exact exchanges, then read and intersect their published sessions."""

        if type(request) is not PortfolioRiskCalendarReadRequest:
            raise TypeError("request must be PortfolioRiskCalendarReadRequest")
        as_of = request.as_of.astimezone(UTC)
        reasons: list[str] = []
        identity_payloads: list[dict[str, object]] = []
        qualified_identity_pairs: set[tuple[str, str]] = set()
        identity_deadlines: list[datetime] = []
        exchange_by_asset: dict[tuple[str, str], str] = {}
        pairs_by_code: dict[str, set[str]] = {}
        if not request.requested_assets:
            reasons.append("PORTFOLIO_RISK_CALENDAR_ASSET_SCOPE_EMPTY")
        for asset in request.requested_assets:
            if asset.security_id is None:
                reasons.append("PORTFOLIO_RISK_CALENDAR_SECURITY_ID_UNKNOWN")
                continue
            pairs_by_code.setdefault(asset.asset_code, set()).add(asset.security_id)
        conflicting_codes = {
            asset_code
            for asset_code, security_ids in pairs_by_code.items()
            if len(security_ids) != 1
        }
        if conflicting_codes:
            reasons.append("PORTFOLIO_RISK_CALENDAR_ASSET_IDENTITY_CONFLICT")

        for asset in sorted(
            request.requested_assets,
            key=lambda item: (item.asset_code, item.security_id or ""),
        ):
            security_id = asset.security_id
            if security_id is None or asset.asset_code in conflicting_codes:
                continue
            try:
                identity = self._identity_reader.get_execution_instrument_identity(
                    asset_code=asset.asset_code,
                    security_id=security_id,
                    as_of=as_of,
                )
            except ExecutionInstrumentIdentityUnavailable as error:
                reasons.append(error.code)
                continue
            except SimulatedTradeExecutionBlocked as error:
                reasons.append(error.code)
                continue
            if identity is None:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_MISSING")
                continue
            if type(identity) is not ExecutionInstrumentIdentityEvidenceV2:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_CONTRACT_INVALID")
                continue
            try:
                identity.__post_init__()
                identity.source_evidence.__post_init__()
                identity.selection.__post_init__()
                identity_payload = identity.to_payload()
            except IdentityEvidenceValidationError as error:
                reasons.append(error.code)
                continue
            except (AttributeError, ArithmeticError, TypeError, ValueError):
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_CONTRACT_INVALID")
                continue
            identity_payloads.append(identity_payload)
            source = identity.source_evidence
            if identity.asset_code != asset.asset_code or identity.security_id != security_id:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_SCOPE_MISMATCH")
                continue
            if identity.selection.selected_at != as_of:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_CUTOFF_MISMATCH")
                continue
            if source.must_not_use_for_decision or source.must_not_execute:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_PROHIBITED")
                continue
            if source.identity_valid_from > as_of:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_NOT_YET_VALID")
                continue
            if as_of >= source.identity_valid_until:
                reasons.append("PORTFOLIO_RISK_CALENDAR_IDENTITY_EXPIRED")
                continue
            try:
                source.validate_at(as_of=as_of)
            except IdentityEvidenceValidationError as error:
                reasons.append(error.code)
                continue
            exchange_by_asset[(asset.asset_code, security_id)] = identity.source_exchange
            qualified_identity_pairs.add((asset.asset_code, security_id))
            identity_deadlines.append(source.identity_valid_until.astimezone(UTC))

        exchanges = tuple(sorted(set(exchange_by_asset.values())))
        calendar_payloads: list[dict[str, object]] = []
        calendar_deadlines: list[datetime] = []
        calendar_snapshots: list[ExecutionCalendarEvidence] = []
        for exchange in exchanges:
            try:
                calendar = self._calendar_reader.get_effective_execution_calendar(
                    exchange=exchange,
                    as_of=as_of,
                    coverage_start=request.requested_session,
                )
            except ExecutionCalendarUnavailable as error:
                reasons.append(error.code)
                continue
            except SimulatedTradeExecutionBlocked as error:
                reasons.append(error.code)
                continue
            if calendar is None:
                reasons.append("PORTFOLIO_RISK_CALENDAR_PUBLICATION_MISSING")
                continue
            if type(calendar) is not ExecutionCalendarEvidence:
                reasons.append("PORTFOLIO_RISK_CALENDAR_CONTRACT_INVALID")
                continue
            try:
                calendar.__post_init__()
                publication = calendar.publication
                snapshot = calendar.snapshot
                calendar_payload: dict[str, object] = {
                    "requested_exchange": exchange,
                    "evidence_hash": calendar.evidence_hash,
                    "snapshot": snapshot.to_payload(),
                    "publication": (publication.to_payload() if publication is not None else None),
                }
            except CalendarEvidenceValidationError:
                reasons.append("PORTFOLIO_RISK_CALENDAR_EVIDENCE_INVALID")
                continue
            except (AttributeError, ArithmeticError, TypeError, ValueError):
                reasons.append("PORTFOLIO_RISK_CALENDAR_EVIDENCE_INVALID")
                continue
            calendar_payloads.append(calendar_payload)
            if publication is None:
                reasons.append("PORTFOLIO_RISK_CALENDAR_PUBLICATION_MISSING")
                continue
            if snapshot.exchange != exchange:
                reasons.append("PORTFOLIO_RISK_CALENDAR_EXCHANGE_MISMATCH")
                continue
            if not snapshot.coverage_start <= request.requested_session <= snapshot.coverage_end:
                reasons.append("PORTFOLIO_RISK_CALENDAR_SESSION_OUTSIDE_COVERAGE")
                continue
            if publication.reference_valid_from > as_of:
                reasons.append("PORTFOLIO_RISK_CALENDAR_PUBLICATION_NOT_YET_VALID")
                continue
            if as_of >= publication.reference_valid_until:
                reasons.append("PORTFOLIO_RISK_CALENDAR_PUBLICATION_EXPIRED")
                continue
            known_times = (
                snapshot.first_seen_at,
                snapshot.recorded_at,
                snapshot.source_published_at,
                publication.published_at,
                publication.recorded_at,
            )
            if any(value is not None and value > as_of for value in known_times):
                reasons.append("PORTFOLIO_RISK_CALENDAR_EVIDENCE_AFTER_CUTOFF")
                continue
            try:
                calendar.validate_for(as_of)
            except CalendarEvidenceValidationError:
                reasons.append("PORTFOLIO_RISK_CALENDAR_EVIDENCE_NOT_KNOWN_AT_CUTOFF")
                continue
            calendar_snapshots.append(calendar)
            calendar_deadlines.append(publication.reference_valid_until.astimezone(UTC))

        open_sessions: tuple[date, ...] | None = None
        if not reasons and len(calendar_snapshots) == len(exchanges):
            open_sessions, compatibility_reason = _common_open_sessions(
                calendars=tuple(calendar_snapshots),
                requested_session=request.requested_session,
            )
            if compatibility_reason is not None:
                reasons.append(compatibility_reason)
        if open_sessions is not None and request.requested_session not in open_sessions:
            reasons.append("PORTFOLIO_RISK_CALENDAR_SESSION_NOT_OPEN_ON_ALL_EXCHANGES")

        proof_complete = (
            bool(request.requested_assets)
            and not any(
                reason != "PORTFOLIO_RISK_CALENDAR_SESSION_NOT_OPEN_ON_ALL_EXCHANGES"
                for reason in reasons
            )
            and len(identity_payloads) == len(request.requested_assets)
            and len(qualified_identity_pairs) == len(request.requested_assets)
            and len(calendar_snapshots) == len(exchanges)
        )
        valid_until = (
            min((*identity_deadlines, *calendar_deadlines))
            if proof_complete and identity_deadlines and calendar_deadlines
            else None
        )
        payload: dict[str, object] = {
            "schema": "portfolio-risk-calendar-evidence.v1",
            "requested_assets": [
                {"asset_code": item.asset_code, "security_id": item.security_id}
                for item in sorted(
                    request.requested_assets,
                    key=lambda item: (item.asset_code, item.security_id or ""),
                )
            ],
            "requested_session": request.requested_session.isoformat(),
            "as_of": as_of.isoformat(),
            "identity_evidence": identity_payloads,
            "calendar_evidence": calendar_payloads,
            "reason_codes": list(dict.fromkeys(reasons)),
        }
        try:
            canonical_json = canonical_portfolio_risk_json(payload)
            evidence_hash = portfolio_risk_content_hash(payload)
        except (TypeError, ValueError):
            reasons.append("PORTFOLIO_RISK_CALENDAR_EVIDENCE_CANONICALIZATION_FAILED")
            canonical_json = None
            evidence_hash = None
            valid_until = None
        final_reasons = tuple(dict.fromkeys(reasons))
        qualified = (
            proof_complete
            and not final_reasons
            and open_sessions is not None
            and request.requested_session in open_sessions
            and canonical_json is not None
            and evidence_hash is not None
            and valid_until is not None
        )
        return PortfolioRiskCalendarReadResult(
            requested_session_qualified=qualified,
            open_sessions=open_sessions,
            reason_codes=final_reasons,
            canonical_evidence_json=canonical_json,
            evidence_hash=evidence_hash,
            valid_until=valid_until,
        )


def build_portfolio_risk_calendar_reader(
    *,
    identity_reader: PortfolioRiskCurrentIdentityReader,
    calendar_reader: PortfolioRiskPublishedCalendarReader,
) -> PortfolioRiskCalendarReader:
    """Build the application reader from explicit current-identity/calendar ports."""

    if identity_reader is None or calendar_reader is None:
        raise ValueError("identity_reader and calendar_reader are required")
    return _ConfiguredPortfolioRiskCalendarReader(
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
    )


def _common_open_sessions(
    *,
    calendars: tuple[ExecutionCalendarEvidence, ...],
    requested_session: date,
) -> tuple[tuple[date, ...] | None, str | None]:
    """Intersect explicit dates from compatible published exchange calendars."""

    if not calendars:
        return None, "PORTFOLIO_RISK_CALENDAR_PUBLICATION_MISSING"
    common_start = max(calendar.snapshot.coverage_start for calendar in calendars)
    common_end = min(calendar.snapshot.coverage_end for calendar in calendars)
    if common_start > common_end:
        return None, "PORTFOLIO_RISK_CALENDAR_COVERAGE_NOT_COMPATIBLE"
    if not common_start <= requested_session <= common_end:
        return None, "PORTFOLIO_RISK_CALENDAR_SESSION_OUTSIDE_COMMON_COVERAGE"
    day_maps = tuple(
        {day.calendar_date: day.is_open for day in calendar.snapshot.days} for calendar in calendars
    )
    sessions: list[date] = []
    current = common_start
    while current <= common_end:
        if all(day_map.get(current) is True for day_map in day_maps):
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions), None


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


__all__ = [
    "PortfolioRiskCalendarReadRequest",
    "PortfolioRiskCalendarReadResult",
    "PortfolioRiskCalendarReader",
    "PortfolioRiskCurrentIdentityReader",
    "PortfolioRiskPublishedCalendarReader",
    "build_portfolio_risk_calendar_reader",
]
