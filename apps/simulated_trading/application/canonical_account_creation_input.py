"""Identity-free input for authenticated canonical account creation."""

from dataclasses import dataclass

from apps.account.domain.canonical_account_creation import CanonicalAccountCreationRequester
from apps.simulated_trading.application.canonical_account_creation_request import (
    CanonicalAccountCreationRequest,
)
from apps.simulated_trading.domain.entities import AccountType


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationInput:
    """Carry explicit user choices without accepting actor or user identity.

    The HTTP serializer resolves its existing defaults. Binding validates the
    complete request and preserves the existing account-type auto-trading rule.
    """

    request_key: str
    account_name: str
    account_type: AccountType
    initial_capital: float
    max_position_pct: float
    stop_loss_pct: float | None
    commission_rate: float
    slippage_rate: float

    def bind(self, requester: CanonicalAccountCreationRequester) -> CanonicalAccountCreationRequest:
        """Bind only the server's authenticated identity to the validated request."""

        if type(requester) is not CanonicalAccountCreationRequester:
            raise TypeError("requester must be an exact canonical creation requester")
        requester.__post_init__()
        return CanonicalAccountCreationRequest(
            actor_id=requester.actor_id,
            user_id=requester.user_id,
            request_key=self.request_key,
            account_name=self.account_name,
            account_type=self.account_type,
            initial_capital=self.initial_capital,
            auto_trading_enabled=self.account_type is AccountType.SIMULATED,
            max_position_pct=self.max_position_pct,
            stop_loss_pct=self.stop_loss_pct,
            commission_rate=self.commission_rate,
            slippage_rate=self.slippage_rate,
        )
