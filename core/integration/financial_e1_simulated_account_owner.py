"""Cross-App bridge for the actual simulated-account ownership identity.

This bridge reads the simulated_trading application's typed binding query. It
does not inspect the legacy ``account.Portfolio`` namespace or treat matching
integer primary keys across tables as the same account.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.simulated_trading.application.query_services import (
    AccountBindingIdentity,
    get_account_binding_identity,
)
from apps.simulated_trading.domain.entities import AccountType


@dataclass(frozen=True, slots=True)
class FinancialE1SimulatedAccountBindingObservation:
    """Expose exact simulated-account owner, type, and active state."""

    account_id: int
    owner_user_id: int
    is_simulated: bool
    is_active: bool

    def __post_init__(self) -> None:
        """Reject incomplete or substituted owner-binding query results."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.is_simulated) is not bool
            or type(self.is_active) is not bool
        ):
            raise ValueError("simulated-account binding observation is invalid")


def resolve_financial_e1_simulated_account_binding(
    *, user_id: int, account_id: int
) -> FinancialE1SimulatedAccountBindingObservation | None:
    """Read one exact owner-scoped simulated account through its public query."""

    if type(user_id) is not int or user_id <= 0:
        raise ValueError("E1 owner user id must be a positive persisted identifier")
    if type(account_id) is not int or account_id <= 0:
        raise ValueError("E1 simulated account id must be a positive persisted identifier")
    binding: AccountBindingIdentity | None = get_account_binding_identity(
        owner_user_id=user_id,
        account_id=account_id,
    )
    if binding is None:
        return None
    if (
        type(binding) is not dict
        or set(binding) != {"owner_user_id", "account_id", "account_type", "is_active"}
        or type(binding["owner_user_id"]) is not int
        or type(binding["account_id"]) is not int
        or type(binding["account_type"]) is not str
        or type(binding["is_active"]) is not bool
    ):
        raise ValueError("simulated-trading binding query returned an invalid identity")
    account_type = binding["account_type"]
    if account_type not in {member.value for member in AccountType}:
        raise ValueError("simulated-trading binding query returned an unknown account type")
    return FinancialE1SimulatedAccountBindingObservation(
        account_id=binding["account_id"],
        owner_user_id=binding["owner_user_id"],
        is_simulated=account_type == AccountType.SIMULATED.value,
        is_active=binding["is_active"],
    )


__all__ = [
    "FinancialE1SimulatedAccountBindingObservation",
    "resolve_financial_e1_simulated_account_binding",
]
