"""Pure domain entities for centralized risk control."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


PARAMETER_FIELDS: tuple[str, ...] = (
    "max_total_position_pct",
    "max_single_position_pct",
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_stop_loss_pct",
    "take_profit_pct",
    "min_cash_pct",
    "force_stop_loss",
    "hard_exclusions",
)

FLOOR_LIMIT_FIELDS: tuple[str, ...] = (
    "max_total_position_pct",
    "max_single_position_pct",
    "max_daily_loss_pct",
    "max_drawdown_pct",
    "max_stop_loss_pct",
)


@dataclass(frozen=True)
class RiskParameters:
    max_total_position_pct: float | None = None
    max_single_position_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    min_cash_pct: float | None = None
    force_stop_loss: bool | None = None
    hard_exclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_total_position_pct": self.max_total_position_pct,
            "max_single_position_pct": self.max_single_position_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_stop_loss_pct": self.max_stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "min_cash_pct": self.min_cash_pct,
            "force_stop_loss": self.force_stop_loss,
            "hard_exclusions": list(self.hard_exclusions),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> RiskParameters:
        if not data:
            return cls()
        hard_exclusions = data.get("hard_exclusions") or ()
        return cls(
            max_total_position_pct=data.get("max_total_position_pct"),
            max_single_position_pct=data.get("max_single_position_pct"),
            max_daily_loss_pct=data.get("max_daily_loss_pct"),
            max_drawdown_pct=data.get("max_drawdown_pct"),
            max_stop_loss_pct=data.get("max_stop_loss_pct"),
            take_profit_pct=data.get("take_profit_pct"),
            min_cash_pct=data.get("min_cash_pct"),
            force_stop_loss=data.get("force_stop_loss"),
            hard_exclusions=tuple(str(item) for item in hard_exclusions),
        )


@dataclass(frozen=True)
class GlobalRiskFloor:
    parameters: RiskParameters
    is_active: bool = True


@dataclass(frozen=True)
class RiskTemplate:
    key: str
    name: str
    risk_profile: RiskProfile
    parameters: RiskParameters
    is_active: bool = True


@dataclass(frozen=True)
class AccountRiskPolicy:
    account_id: int
    template_key: str | None = None
    risk_profile: RiskProfile | None = None
    overrides: RiskParameters = field(default_factory=RiskParameters)
    is_active: bool = True


@dataclass(frozen=True)
class RiskException:
    field_name: str
    allowed_value: Any
    reason: str
    created_by: str
    expires_at: datetime
    account_id: int | None = None
    is_active: bool = True

    def is_valid_at(self, timestamp: datetime | None = None) -> bool:
        checked_at = timestamp or datetime.now(UTC)
        return self.is_active and self.expires_at > checked_at


@dataclass(frozen=True)
class ResolvedRiskPolicy:
    account_id: int
    parameters: RiskParameters
    template_key: str | None
    risk_profile: RiskProfile
    sources: dict[str, str]
    floor_applied: list[dict[str, Any]]
    exceptions_applied: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "template_key": self.template_key,
            "risk_profile": self.risk_profile.value,
            "parameters": self.parameters.to_dict(),
            "sources": self.sources,
            "floor_applied": self.floor_applied,
            "exceptions_applied": self.exceptions_applied,
            "warnings": self.warnings,
        }
