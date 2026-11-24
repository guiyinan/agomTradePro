"""Owner-source boundaries for Portfolio benchmark day closes and independent approvals."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from rest_framework.request import Request

from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable


@dataclass(frozen=True, slots=True)
class DayOwner:
    scope: BenchmarkScope
    physical_id: int
    identity_hash: str
    policy_hash: str
    valid_until: datetime
    source_id: str
    source_version: str
    policy_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class BenchmarkGovernanceActor:
    """Current verified staff identity and strategy-write role for one account."""

    user_id: int
    role: str


@dataclass(frozen=True, slots=True)
class DayReconciliation:
    account_ref_hash: str
    captured_at: datetime
    completed_at: datetime
    max_snapshot_age_seconds: int
    total_asset: Decimal
    cash_available: Decimal
    cash_frozen: Decimal
    position_market_value: Decimal
    currency: str
    positions: dict[str, tuple[Decimal, Decimal, Decimal]]
    content_hash: str
    signed_receipt: str


@dataclass(frozen=True, slots=True)
class ClosingFixing:
    observed_at: datetime
    published_at: datetime
    price: Decimal
    publication_hash: str
    member_hash: str = ""
    asset_class: str = ""
    venue: str = ""


class BenchmarkDaySources(Protocol):
    def signer(
        self, *, request: Request, using: str, before_commit: Callable[[], None]
    ) -> AbstractContextManager[int]: ...
    def approval_reviewer(self, *, request: Request, using: str) -> AbstractContextManager[int]:
        """Hold the authenticated reviewer identity and credentials through the read."""
        ...

    def governance_actor(
        self, *, user_id: int, owner_user_id: int, using: str
    ) -> BenchmarkGovernanceActor | None:
        """Recheck and hold the named signer's current staff and account authority."""
        ...

    def owner(
        self, *, namespace: str, account_id: str, user_id: int, using: str
    ) -> DayOwner | None: ...
    def reconciliation(
        self, *, snapshot_id: int, owner: DayOwner, using: str
    ) -> DayReconciliation | None: ...
    def historical_member(
        self, *, asset: str, day: date, at: datetime, issued_at: datetime, using: str
    ) -> str | None: ...
    def fixing(
        self, *, asset: str, day: date, at: datetime, using: str
    ) -> ClosingFixing | None: ...


_factory: Callable[[], BenchmarkDaySources] | None = None


def register_benchmark_day_sources(factory: Callable[[], BenchmarkDaySources]) -> None:
    """Install the core composition's owner readers at application startup."""
    global _factory
    if _factory is not None and factory is not _factory:
        raise RuntimeError("benchmark day sources already installed")
    _factory = factory


def benchmark_day_sources() -> BenchmarkDaySources:
    """Return the server-selected owner readers."""
    if _factory is None:
        raise BenchmarkDayUnavailable("benchmark owner readers are unavailable")
    return _factory()
