"""Read-only complete tax-exposure coverage for simulated cash admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal, Protocol

from apps.simulated_trading.domain.corporate_action_tax_liability import (
    _money,
    _positive_quantum,
    _require_quantized,
)
from core.exceptions import BusinessLogicError


class TaxCashCoverageStatus(StrEnum):
    """Whether every applicable modeled tax exposure has been independently covered."""

    COMPLETE = "complete"
    UNKNOWN = "unknown"


class TaxCashCoverageReason(StrEnum):
    """Stable missing-evidence reasons, without inferring debt from absent rows."""

    OFFICIAL_WINDOW_UNVERIFIED = "TAX_CASH_OFFICIAL_WINDOW_UNVERIFIED"
    HISTORY_UNVERIFIED = "TAX_CASH_HISTORY_UNVERIFIED"
    UNASSESSED_DISPOSITION = "TAX_CASH_UNASSESSED_DISPOSITION"
    ASSESSMENT_NOT_APPLIED = "TAX_CASH_ASSESSMENT_NOT_APPLIED"
    MODEL_UNVERIFIED = "TAX_CASH_MODEL_UNVERIFIED"
    UNCLOSED_MODELED_DATE = "TAX_CASH_UNCLOSED_MODELED_DATE"
    UNSUPPORTED_EVENT = "TAX_CASH_UNSUPPORTED_EVENT"
    SOURCE_CHANGED = "TAX_CASH_SOURCE_CHANGED"


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "账户模拟税款覆盖无法完整核对。", code="SIMULATED_TAX_CASH_COVERAGE_INVALID"
    )


def _clock(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _blocked()
    return value


def _token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 192
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise _blocked()
    return value


@dataclass(frozen=True, slots=True)
class TaxCashCoverageQuery:
    """Actual locked physical owner and separately resolved canonical account identity."""

    physical_account_id: int
    owner_user_id: int
    canonical_account_id: str
    environment: str

    def __post_init__(self) -> None:
        """Reject account aliases, coercion and incomplete owner/environment scope."""
        if (
            type(self.physical_account_id) is not int
            or self.physical_account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
        ):
            raise _blocked()
        _token(self.canonical_account_id)
        _token(self.environment)


@dataclass(frozen=True, slots=True)
class TaxCashCoverageSnapshot:
    """Accepted debt and any separately modeled reserve; neither is permission to trade.

    An empty accepted ledger proves no accepted debt only. Unknown exposure
    coverage keeps the admission amount unknown even when accepted debt is zero.
    """

    query: TaxCashCoverageQuery
    currency_quantum: Decimal
    accepted_unpaid_tax: Decimal | None
    modeled_unapplied_tax_reserve: Decimal | None
    coverage_status: TaxCashCoverageStatus
    reason_codes: tuple[TaxCashCoverageReason, ...]
    checked_at: datetime
    coverage_known_at: datetime | None = None
    valid_until: datetime | None = None
    coverage_sha256: str | None = None
    must_not_use_for_decision: Literal[True] = True

    def __post_init__(self) -> None:
        """Keep exact amounts, unknowns, proof identity and original finite clocks distinct."""
        if (
            type(self.query) is not TaxCashCoverageQuery
            or type(self.coverage_status) is not TaxCashCoverageStatus
            or type(self.reason_codes) is not tuple
            or len(set(self.reason_codes)) != len(self.reason_codes)
            or any(type(reason) is not TaxCashCoverageReason for reason in self.reason_codes)
            or self.must_not_use_for_decision is not True
        ):
            raise _blocked()
        self.query.__post_init__()
        quantum = _positive_quantum(self.currency_quantum)
        checked = _clock(self.checked_at)
        for name, amount in (
            ("accepted_unpaid_tax", self.accepted_unpaid_tax),
            ("modeled_unapplied_tax_reserve", self.modeled_unapplied_tax_reserve),
        ):
            if amount is not None:
                _require_quantized(_money(amount, name), quantum, name)
        if self.coverage_status is TaxCashCoverageStatus.COMPLETE:
            digest = self.coverage_sha256
            if (
                self.reason_codes
                or self.accepted_unpaid_tax is None
                or self.modeled_unapplied_tax_reserve is None
                or self.coverage_known_at is None
                or self.valid_until is None
                or type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or not _clock(self.coverage_known_at) <= checked < _clock(self.valid_until)
            ):
                raise _blocked()
        elif not self.reason_codes:
            raise _blocked()

    @property
    def tax_cash_unavailable(self) -> Decimal | None:
        """Return a complete debt/reserve admission amount; unknown exposure never becomes zero."""
        self.__post_init__()
        if self.coverage_status is not TaxCashCoverageStatus.COMPLETE:
            return None
        debt, reserve = self.accepted_unpaid_tax, self.modeled_unapplied_tax_reserve
        if debt is None or reserve is None:
            return None
        with localcontext() as context:
            context.prec = 96
            return debt + reserve

    def verify_for(self, query: TaxCashCoverageQuery, *, as_of: datetime) -> None:
        """Require the exact current owner and original finite complete-coverage lease."""
        self.__post_init__()
        if type(query) is not TaxCashCoverageQuery or query != self.query:
            raise _blocked()
        cutoff = _clock(as_of)
        if self.checked_at > cutoff:
            raise _blocked()
        if self.coverage_status is TaxCashCoverageStatus.COMPLETE and (
            self.valid_until is None or cutoff >= self.valid_until
        ):
            raise _blocked()


class CorporateActionTaxCashCoverageReader(Protocol):
    """Read under the caller-owned account transaction, without tax commands or new consent."""

    @property
    def database_alias(self) -> str:
        """Return the exact alias shared by physical ownership and financial reads."""
        ...

    def read_locked(
        self, *, physical_account_id: int, owner_user_id: int, using: str
    ) -> TaxCashCoverageSnapshot:
        """Resolve canonical scope independently and read at the adapter's real server clock."""
        ...

    def assert_still_current(
        self,
        snapshot: TaxCashCoverageSnapshot,
        *,
        using: str,
        expected_account_updated_at: datetime | None = None,
    ) -> None:
        """Recheck original source epochs and finite deadlines before the caller commits."""
        ...
