"""Bind one V4 pending-fill release to its exact Trade and calendar proof.

The proof records release-time calendar evidence and is distinct from the
immutable original fill receipt. It does not authenticate the provider or
replace repository owner, receipt-chain, and transaction checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    _calendar_evidence_payload,
    _utc_microsecond_text,
)

_RELEASE_PROOF_SCHEMA = "simulated-order-fill-settlement-release-proof.v1"


@dataclass(frozen=True, slots=True)
class OrderFillSettlementReleaseProof:
    """Immutable release-time evidence bound to one original V4 fill receipt."""

    trade_id: int
    reservation_id: int
    account_id: int
    user_id: int
    receipt_hash: str
    security_id: str
    settlement_exchange: str
    fill_market_session: date
    settlement_lag_sessions: int
    released_at: datetime
    release_session: date
    calendar_evidence: ExecutionCalendarEvidence

    def __post_init__(self) -> None:
        """Validate all identities, source clocks, and release-session claims."""

        self.validate()

    def validate(self) -> None:
        """Require exact original-fill identity and sufficient current open sessions."""

        identifiers = (
            ("trade_id", self.trade_id),
            ("reservation_id", self.reservation_id),
            ("account_id", self.account_id),
            ("user_id", self.user_id),
        )
        for field_name, value in identifiers:
            if type(value) is not int or value <= 0:
                raise SimulatedSettlementContractError(
                    f"{field_name} must be a positive exact integer"
                )
        _require_hash(self.receipt_hash, "receipt_hash")
        _require_token(self.security_id, "security_id")
        _require_token(self.settlement_exchange, "settlement_exchange")
        if type(self.fill_market_session) is not date:
            raise CalendarEvidenceValidationError("fill_market_session must be an exact date")
        if type(self.release_session) is not date:
            raise CalendarEvidenceValidationError("release_session must be an exact date")
        if type(self.settlement_lag_sessions) is not int or self.settlement_lag_sessions < 0:
            raise CalendarEvidenceValidationError(
                "settlement_lag_sessions must be an exact nonnegative integer"
            )
        if type(self.released_at) is not datetime:
            raise CalendarEvidenceValidationError("released_at must be an exact datetime")
        _require_aware(self.released_at, "released_at")
        if type(self.calendar_evidence) is not ExecutionCalendarEvidence:
            raise CalendarEvidenceValidationError(
                "calendar_evidence must be an exact ExecutionCalendarEvidence"
            )

        evidence = self.calendar_evidence
        evidence.__post_init__()
        if evidence.snapshot.exchange != self.settlement_exchange:
            raise CalendarEvidenceValidationError(
                "settlement exchange differs from the release calendar scope"
            )
        evidence.validate_for(self.released_at)
        actual_release_session = evidence.current_open_session(self.released_at)
        if actual_release_session != self.release_session:
            raise CalendarEvidenceValidationError(
                "claimed release session differs from the release-time calendar session"
            )
        elapsed_sessions = evidence.elapsed_open_sessions(
            self.fill_market_session,
            self.release_session,
        )
        if elapsed_sessions < self.settlement_lag_sessions:
            raise CalendarEvidenceValidationError(
                "release session has not reached the stored settlement lag"
            )

    def to_payload(self) -> dict[str, object]:
        """Return release identity and the complete persisted calendar evidence."""

        self.validate()
        return {
            "schema": _RELEASE_PROOF_SCHEMA,
            "trade_id": self.trade_id,
            "reservation_id": self.reservation_id,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "receipt_hash": self.receipt_hash,
            "security_id": self.security_id,
            "settlement_exchange": self.settlement_exchange,
            "fill_market_session": self.fill_market_session.isoformat(),
            "settlement_lag_sessions": self.settlement_lag_sessions,
            "released_at": _utc_microsecond_text(self.released_at, "released_at"),
            "release_session": self.release_session.isoformat(),
            "calendar_evidence": _calendar_evidence_payload(self.calendar_evidence),
        }

    @property
    def proof_hash(self) -> str:
        """Return a digest over the release claims and full calendar snapshot."""

        return _hash_payload(self.to_payload())


__all__: tuple[str, ...] = ("OrderFillSettlementReleaseProof",)
