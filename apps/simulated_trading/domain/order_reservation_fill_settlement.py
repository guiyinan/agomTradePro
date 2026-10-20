"""Bind a simulated order fill to exact published execution-calendar facts.

This Domain proof only establishes date-level settlement arithmetic from typed,
published calendar evidence. It does not establish that a fill occurred, qualify
its source, or write a Trade, receipt, account, position, or reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
    _hash_payload,
    _require_aware,
    _require_token,
)

_SETTLEMENT_PROOF_SCHEMA = "simulated-order-fill-settlement-proof.v1"
_TRADE_KEY_SCHEMA = "simulated-order-fill-trade-key.v1"
_FILL_NAMESPACE_MAX_LENGTH = 128
_FILL_EVENT_ID_MAX_LENGTH = 128


def _utc_microsecond_text(value: datetime, field_name: str) -> str:
    """Serialize one exact aware datetime in canonical UTC microsecond form."""

    _require_aware(value, field_name)
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(
            f"{field_name} cannot be represented in canonical UTC"
        ) from error


def _snapshot_payload(snapshot: ExchangeCalendarSnapshot) -> dict[str, object]:
    """Keep every snapshot field while canonicalizing each stored source clock."""

    payload = snapshot.to_payload()
    raw_reference = snapshot.raw_reference.to_payload()
    raw_reference["response_completed_at"] = _utc_microsecond_text(
        snapshot.raw_reference.response_completed_at,
        "response_completed_at",
    )
    payload["raw_reference"] = raw_reference
    payload["first_seen_at"] = _utc_microsecond_text(snapshot.first_seen_at, "first_seen_at")
    payload["recorded_at"] = _utc_microsecond_text(snapshot.recorded_at, "recorded_at")
    payload["source_published_at"] = (
        _utc_microsecond_text(snapshot.source_published_at, "source_published_at")
        if snapshot.source_published_at is not None
        else None
    )
    return payload


def _calendar_evidence_payload(evidence: ExecutionCalendarEvidence) -> dict[str, object]:
    """Serialize the complete snapshot and publication without replacing source clocks."""

    evidence.__post_init__()
    publication_payload: dict[str, object] | None = None
    if evidence.publication is not None:
        publication = evidence.publication
        publication_payload = publication.to_payload()
        publication_payload["published_at"] = _utc_microsecond_text(
            publication.published_at,
            "published_at",
        )
        publication_payload["recorded_at"] = _utc_microsecond_text(
            publication.recorded_at,
            "recorded_at",
        )
        publication_payload["reference_valid_from"] = _utc_microsecond_text(
            publication.reference_valid_from,
            "reference_valid_from",
        )
        publication_payload["reference_valid_until"] = _utc_microsecond_text(
            publication.reference_valid_until,
            "reference_valid_until",
        )
    return {
        "evidence_hash": evidence.evidence_hash,
        "snapshot": _snapshot_payload(evidence.snapshot),
        "publication": publication_payload,
    }


@dataclass(frozen=True, slots=True)
class OrderFillSettlementProof:
    """Immutable per-fill exchange session and settlement-release proof.

    The reader cutoff is a knowledge/read clock. Calendar source-observation,
    raw-response, persistence, and publication clocks remain inside the complete
    evidence snapshot and are never substituted with the read cutoff.
    """

    calendar_evidence: ExecutionCalendarEvidence
    calendar_read_cutoff: datetime
    fill_occurred_at: datetime
    settlement_exchange: str
    fill_market_session: date
    settlement_lag_sessions: int
    expected_release_session: date

    def __post_init__(self) -> None:
        """Revalidate typed evidence at both knowledge and fill instants."""

        self.validate()

    def validate(self) -> None:
        """Check evidence visibility, exact session, and explicit lag arithmetic."""

        if type(self.calendar_evidence) is not ExecutionCalendarEvidence:
            raise CalendarEvidenceValidationError(
                "calendar_evidence must be an exact ExecutionCalendarEvidence"
            )
        self.calendar_evidence.__post_init__()
        if type(self.calendar_read_cutoff) is not datetime:
            raise SimulatedSettlementContractError("calendar_read_cutoff must be an exact datetime")
        if type(self.fill_occurred_at) is not datetime:
            raise SimulatedSettlementContractError("fill_occurred_at must be an exact datetime")
        _require_aware(self.calendar_read_cutoff, "calendar_read_cutoff")
        _require_aware(self.fill_occurred_at, "fill_occurred_at")
        if type(self.settlement_exchange) is not str:
            raise CalendarEvidenceValidationError("settlement_exchange must be an exact string")
        _require_token(self.settlement_exchange, "settlement_exchange")
        if type(self.fill_market_session) is not date:
            raise CalendarEvidenceValidationError("fill_market_session must be an exact date")
        if type(self.expected_release_session) is not date:
            raise CalendarEvidenceValidationError("expected_release_session must be an exact date")
        if type(self.settlement_lag_sessions) is not int or self.settlement_lag_sessions < 0:
            raise CalendarEvidenceValidationError(
                "settlement_lag_sessions must be an exact nonnegative integer"
            )
        try:
            if self.fill_occurred_at > self.calendar_read_cutoff:
                raise CalendarEvidenceValidationError(
                    "fill_occurred_at cannot follow calendar_read_cutoff"
                )
        except (OverflowError, TypeError, ValueError) as error:
            if isinstance(error, CalendarEvidenceValidationError):
                raise
            raise CalendarEvidenceValidationError(
                "fill and calendar read clocks cannot be compared"
            ) from error

        evidence = self.calendar_evidence
        if evidence.snapshot.exchange != self.settlement_exchange:
            raise CalendarEvidenceValidationError(
                "settlement exchange differs from the published calendar scope"
            )
        evidence.validate_for(self.calendar_read_cutoff)
        session = evidence.current_open_session(self.fill_occurred_at)
        if session != self.fill_market_session:
            raise CalendarEvidenceValidationError(
                "claimed fill session differs from the event-time calendar session"
            )
        expected_release = evidence.release_session(
            session,
            self.settlement_lag_sessions,
        )
        if expected_release != self.expected_release_session:
            raise CalendarEvidenceValidationError(
                "claimed release session differs from the explicit settlement lag"
            )

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical proof payload used for persistent sealing."""

        self.validate()
        return {
            "schema": _SETTLEMENT_PROOF_SCHEMA,
            "calendar_evidence": _calendar_evidence_payload(self.calendar_evidence),
            "calendar_read_cutoff": _utc_microsecond_text(
                self.calendar_read_cutoff,
                "calendar_read_cutoff",
            ),
            "fill_occurred_at": _utc_microsecond_text(
                self.fill_occurred_at,
                "fill_occurred_at",
            ),
            "settlement_exchange": self.settlement_exchange,
            "fill_market_session": self.fill_market_session.isoformat(),
            "settlement_lag_sessions": self.settlement_lag_sessions,
            "expected_release_session": self.expected_release_session.isoformat(),
        }

    @property
    def proof_hash(self) -> str:
        """Return a digest binding all claims and complete source-calendar evidence."""

        return _hash_payload(self.to_payload())


def build_order_fill_settlement_proof(
    *,
    calendar_evidence: ExecutionCalendarEvidence,
    calendar_read_cutoff: datetime,
    fill_occurred_at: datetime,
    settlement_exchange: str,
    settlement_lag_sessions: int,
) -> OrderFillSettlementProof:
    """Derive fill/release session claims from the published calendar evidence."""

    if type(calendar_evidence) is not ExecutionCalendarEvidence:
        raise CalendarEvidenceValidationError(
            "calendar_evidence must be an exact ExecutionCalendarEvidence"
        )
    if type(calendar_read_cutoff) is not datetime or type(fill_occurred_at) is not datetime:
        raise SimulatedSettlementContractError("calendar proof clocks must be exact datetimes")
    if type(settlement_lag_sessions) is not int or settlement_lag_sessions < 0:
        raise CalendarEvidenceValidationError(
            "settlement_lag_sessions must be an exact nonnegative integer"
        )
    _require_aware(calendar_read_cutoff, "calendar_read_cutoff")
    _require_aware(fill_occurred_at, "fill_occurred_at")
    calendar_evidence.validate_for(calendar_read_cutoff)
    fill_session = calendar_evidence.current_open_session(fill_occurred_at)
    release_session = calendar_evidence.release_session(
        fill_session,
        settlement_lag_sessions,
    )
    return OrderFillSettlementProof(
        calendar_evidence=calendar_evidence,
        calendar_read_cutoff=calendar_read_cutoff,
        fill_occurred_at=fill_occurred_at,
        settlement_exchange=settlement_exchange,
        fill_market_session=fill_session,
        settlement_lag_sessions=settlement_lag_sessions,
        expected_release_session=release_session,
    )


def simulated_order_fill_trade_key(
    *,
    reservation_id: int,
    source_namespace: str,
    fill_event_id: str,
) -> str:
    """Build one stable legacy Trade key from the per-fill durable event locator.

    Source schema versions, payload digests, fill sequence, calendar evidence,
    and receipt hashes are deliberately excluded from this idempotency identity.
    """

    if type(reservation_id) is not int or reservation_id <= 0:
        raise SimulatedSettlementContractError("reservation_id must be a positive exact integer")
    _require_token(
        source_namespace,
        "source_namespace",
        max_length=_FILL_NAMESPACE_MAX_LENGTH,
    )
    _require_token(fill_event_id, "fill_event_id", max_length=_FILL_EVENT_ID_MAX_LENGTH)
    locator_hash = _hash_payload(
        {
            "schema": _TRADE_KEY_SCHEMA,
            "reservation_id": reservation_id,
            "source_namespace": source_namespace,
            "fill_event_id": fill_event_id,
        }
    )
    return f"simfill:{locator_hash}"


__all__: tuple[str, ...] = (
    "OrderFillSettlementProof",
    "build_order_fill_settlement_proof",
    "simulated_order_fill_trade_key",
)
