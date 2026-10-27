"""Read-only, owner-scoped current head for simulated fee corrections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
)
from apps.simulated_trading.domain.entities import SimulatedTrade


@dataclass(frozen=True, slots=True)
class FeeCorrectionHead:
    """Validated current trade view and predecessor needed for the next correction."""

    account_id: int
    trade_id: int
    revision: int
    expected_predecessor_id: int | None
    as_of: datetime
    trade: SimulatedTrade
    request_receipt: FeeCorrectionReceipt | None = None

    def __post_init__(self) -> None:
        """Keep head identity, revision, visible projection, and readback aligned."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
            or type(self.revision) is not int
            or self.revision < 0
            or (
                self.expected_predecessor_id is not None
                and (
                    type(self.expected_predecessor_id) is not int
                    or self.expected_predecessor_id <= 0
                )
            )
            or type(self.as_of) is not datetime
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
            or type(self.trade) is not SimulatedTrade
            or self.trade.account_id != self.account_id
            or self.trade.trade_id != self.trade_id
            or self.trade.fee_correction_revision != (self.revision or None)
            or (self.revision == 0 and self.expected_predecessor_id is not None)
            or (self.revision > 0 and self.expected_predecessor_id is None)
        ):
            raise FeeCorrectionBlockedError(
                "费用更正 head 身份或版本无效",
                code="FEE_CORRECTION_HISTORY_INVALID",
            )
        if self.request_receipt is not None and (
            type(self.request_receipt) is not FeeCorrectionReceipt
            or self.request_receipt.account_id != self.account_id
            or self.request_receipt.trade_id != self.trade_id
            or self.request_receipt.revision > self.revision
            or self.request_receipt.replayed is not True
        ):
            raise FeeCorrectionBlockedError(
                "费用更正请求回执与当前账户或交易不匹配",
                code="FEE_CORRECTION_IDEMPOTENCY_CONFLICT",
            )


class FeeCorrectionHeadRepositoryProtocol(Protocol):
    """Read a validated owner-scoped correction head and optional exact receipt."""

    def get_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        request_key: str | None = None,
    ) -> FeeCorrectionHead:
        """Return current validated fee projection and optional idempotency readback."""
        ...


class FeeCorrectionHeadUseCase:
    """Validate the read request before delegating to the owner-scoped repository."""

    def __init__(self, repository: FeeCorrectionHeadRepositoryProtocol) -> None:
        """Use the supplied read-only persistence boundary."""

        self._repository = repository

    def get_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        request_key: str | None = None,
    ) -> FeeCorrectionHead:
        """Return a correction head for the authenticated account owner."""

        principal_id = _authenticated_principal_user_id(principal)
        if (
            type(account_id) is not int
            or account_id <= 0
            or type(trade_id) is not int
            or trade_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用更正 head 账户或交易编号无效",
                code="FEE_CORRECTION_INPUT_INVALID",
            )
        if principal_id is None:
            raise _authority_unavailable()
        _validate_request_key(request_key)
        return self._repository.get_head(
            account_id,
            trade_id,
            principal=principal,
            request_key=request_key,
        )


def _authenticated_principal_user_id(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
) -> int | None:
    """Narrow the Interface principal without accepting an actor ID from the request."""

    user_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


def _validate_request_key(request_key: str | None) -> None:
    """Require an optional idempotency key to follow the correction write contract."""

    if request_key is None:
        return
    if (
        type(request_key) is not str
        or not request_key
        or request_key.strip() != request_key
        or len(request_key) > 128
        or any(character.isspace() for character in request_key)
    ):
        raise FeeCorrectionBlockedError(
            "费用更正幂等键无效",
            code="FEE_CORRECTION_INPUT_INVALID",
        )


def _authority_unavailable() -> FeeCorrectionBlockedError:
    """Return the non-disclosing denial used for invalid read principals."""

    return FeeCorrectionBlockedError(
        "费用更正历史仅对当前有效的模拟账户所有者开放",
        code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
    )


__all__ = [
    "FeeCorrectionHead",
    "FeeCorrectionHeadRepositoryProtocol",
    "FeeCorrectionHeadUseCase",
]
