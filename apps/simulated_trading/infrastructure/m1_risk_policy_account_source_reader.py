"""Infrastructure reader for current owner and legacy account-risk fields."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.db import DEFAULT_DB_ALIAS

from apps.risk_center.domain.m1_rebalance_risk_policy import RiskSourceLimitField
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAccountSource,
    M1RiskPolicyAccountSourceReader,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


class DjangoM1RiskPolicyAccountSourceReader(M1RiskPolicyAccountSourceReader):
    """Read live account source values without using inspection snapshots."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Bind the account database alias used by this application deployment."""

        self._using = using

    def read_owner_source(self, *, account_id: int) -> M1RiskPolicyAccountSource | None:
        """Return exact account owner/status and current limits or None if absent."""

        if type(account_id) is not int or account_id <= 0:
            return None
        row = (
            SimulatedAccountModel.objects.using(self._using)
            .filter(pk=account_id)
            .values(
                "id",
                "user_id",
                "account_type",
                "is_active",
                "max_position_pct",
                "max_total_position_pct",
                "stop_loss_pct",
            )
            .first()
        )
        if row is None:
            return None
        return _account_source_from_row(row)


def _account_source_from_row(row: Mapping[str, object]) -> M1RiskPolicyAccountSource | None:
    """Normalize the exact ORM values without collapsing corruption into NULL."""

    raw_owner_id = row.get("user_id")
    owner_id = raw_owner_id if type(raw_owner_id) is int and raw_owner_id > 0 else None
    account_type = row.get("account_type")
    is_active = row.get("is_active")
    if type(account_type) is not str or type(is_active) is not bool:
        return None
    single_pct, single_invalid = _parse_percentage(row.get("max_position_pct"), nullable=False)
    total_pct, total_invalid = _parse_percentage(row.get("max_total_position_pct"), nullable=False)
    stop_loss_pct, stop_loss_invalid = _parse_percentage(row.get("stop_loss_pct"), nullable=True)
    invalid_fields: list[RiskSourceLimitField] = []
    if single_invalid:
        invalid_fields.append("max_single_position_pct")
    if total_invalid:
        invalid_fields.append("max_total_position_pct")
    if stop_loss_invalid:
        invalid_fields.append("stop_loss_pct")
    return M1RiskPolicyAccountSource(
        account_id=_positive_int(row.get("id"), "id"),
        owner_user_id=owner_id,
        account_type=account_type,
        is_active=is_active,
        max_single_position_pct=single_pct,
        max_total_position_pct=total_pct,
        stop_loss_pct=stop_loss_pct,
        invalid_limit_fields=tuple(invalid_fields),
    )


def _positive_int(value: object, field_name: str) -> int:
    """Require an exact integer for a persisted primary key."""

    if type(value) is not int or value <= 0:
        raise ValueError(f"account source {field_name} is invalid")
    return value


def _parse_percentage(value: object, *, nullable: bool) -> tuple[Decimal | None, bool]:
    """Return a bounded Decimal and corruption flag without hiding invalid non-NULLs.

    ``None`` is valid only for the explicitly nullable legacy stop-loss column.
    Invalid values never become an indistinguishable unconfigured source.
    """

    if value is None:
        return None, not nullable
    if type(value) not in (int, float, Decimal):
        return None, True
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, True
    if not result.is_finite() or result < Decimal("0") or result > Decimal("100"):
        return None, True
    return result, False


__all__: tuple[str, ...] = ("DjangoM1RiskPolicyAccountSourceReader",)
