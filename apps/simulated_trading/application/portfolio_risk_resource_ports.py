"""Typed application boundary for exact simulated account risk inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from apps.risk_center.application.portfolio_risk_snapshot import AccountSnapshot
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits as NativeAccountRiskLimits,
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskAccountScope:
    """Read and write authority for one simulated account owner scope."""

    owner_user_id: int
    can_read: bool
    can_write: bool

    def __post_init__(self) -> None:
        """Keep write access within an established readable owner scope."""

        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if type(self.can_read) is not bool or type(self.can_write) is not bool:
            raise TypeError("account scope permissions must be explicit booleans")
        if self.can_write and not self.can_read:
            raise ValueError("a writable account scope must also be readable")


@dataclass(frozen=True, slots=True)
class PortfolioRiskIdentityIssue:
    """One asset whose simulated ledger security identity is absent or conflicting."""

    asset_code: str
    kind: Literal["missing", "conflict"]

    def __post_init__(self) -> None:
        """Require an exact asset token and a recognized identity issue."""

        if type(self.asset_code) is not str or not self.asset_code.strip():
            raise ValueError("asset_code must be a nonempty string")
        if self.kind not in {"missing", "conflict"}:
            raise ValueError("identity issue kind must be missing or conflict")


@dataclass(frozen=True, slots=True)
class AccountSnapshotReadResult:
    """Exact account snapshot or a scoped fail-closed read outcome."""

    snapshot: AccountSnapshot | None
    scope: PortfolioRiskAccountScope | None
    native_account_limits: NativeAccountRiskLimits | None
    reason_codes: tuple[str, ...]
    identity_issues: tuple[PortfolioRiskIdentityIssue, ...]
    money_unit_basis: Literal["native_simulated_ledger_config", "unknown"]

    def __post_init__(self) -> None:
        """Prevent unauthorized snapshots and retain unknown configuration state."""

        if self.snapshot is not None and type(self.snapshot) is not AccountSnapshot:
            raise TypeError("snapshot must be an AccountSnapshot or None")
        if self.native_account_limits is not None and type(self.native_account_limits) is not (
            NativeAccountRiskLimits
        ):
            raise TypeError("native_account_limits must be typed or None")
        if self.scope is not None and type(self.scope) is not PortfolioRiskAccountScope:
            raise TypeError("scope must be a PortfolioRiskAccountScope or None")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must contain nonempty strings")
        if type(self.identity_issues) is not tuple or any(
            type(issue) is not PortfolioRiskIdentityIssue for issue in self.identity_issues
        ):
            raise TypeError("identity_issues must contain typed identity issues")
        if self.money_unit_basis not in {"native_simulated_ledger_config", "unknown"}:
            raise ValueError("money_unit_basis is unsupported")
        if self.scope is None and (
            self.snapshot is not None
            or self.native_account_limits is not None
            or self.reason_codes
            or self.identity_issues
        ):
            raise ValueError("an unavailable account scope cannot expose account data")
        if self.scope is not None:
            if not self.scope.can_read:
                raise ValueError("a returned account scope must allow reading")
            if self.snapshot is not None and (
                self.snapshot.owner_user_id != self.scope.owner_user_id
            ):
                raise ValueError("snapshot owner must match the authorized scope")
            if (self.snapshot is None) != (self.native_account_limits is None):
                raise ValueError("native limits must accompany only a complete account snapshot")
            if self.snapshot is None and not self.reason_codes:
                raise ValueError("an unavailable scoped snapshot requires a reason")
        if self.snapshot is not None:
            if self.snapshot.money_unit is None and self.money_unit_basis != "unknown":
                raise ValueError("unknown money unit must retain an unknown basis")
            if self.snapshot.money_unit is not None and self.money_unit_basis != (
                "native_simulated_ledger_config"
            ):
                raise ValueError("configured money unit requires its explicit basis")


class PortfolioRiskResourceSnapshotReaderProtocol(Protocol):
    """Read a locked simulated account snapshot for an authorized user."""

    def read_account_scope(
        self,
        *,
        user_id: int,
        account_id: int,
    ) -> PortfolioRiskAccountScope | None:
        """Return owner/delegated read scope without reading financial resources."""

    def read_account_snapshot(
        self,
        *,
        user_id: int,
        account_id: int,
        execution_session: date,
        money_unit: str | None,
    ) -> AccountSnapshotReadResult:
        """Return exact owner/delegated-read scope and account resources."""


__all__ = [
    "AccountSnapshotReadResult",
    "NativeAccountRiskLimits",
    "PortfolioRiskAccountScope",
    "PortfolioRiskIdentityIssue",
    "PortfolioRiskResourceSnapshotReaderProtocol",
]
