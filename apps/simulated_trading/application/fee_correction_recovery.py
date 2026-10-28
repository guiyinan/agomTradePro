"""Owner-scoped discovery contracts for pending fee-correction evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)

FeeCorrectionRecoveryState = Literal["completed", "unresolved", "fenced", "unknown"]


@dataclass(frozen=True, slots=True)
class FeeCorrectionRecoveryCommand:
    """One authenticated, bounded page of material recovery state for a Trade."""

    account_id: int
    trade_id: int
    limit: int = 20
    cursor: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed scope and paging input before repository access."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用更正恢复查询账户或交易编号无效",
                code="FEE_CORRECTION_INPUT_INVALID",
            )
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise FeeCorrectionBlockedError(
                "费用更正恢复查询分页大小无效",
                code="FEE_CORRECTION_INPUT_INVALID",
            )
        if self.cursor is not None:
            if type(self.cursor) is not str or len(self.cursor) != 36:
                raise FeeCorrectionBlockedError(
                    "费用更正恢复查询游标无效",
                    code="FEE_CORRECTION_INPUT_INVALID",
                )
            try:
                parsed_cursor = UUID(self.cursor)
            except ValueError as error:
                raise FeeCorrectionBlockedError(
                    "费用更正恢复查询游标无效",
                    code="FEE_CORRECTION_INPUT_INVALID",
                ) from error
            if str(parsed_cursor) != self.cursor:
                raise FeeCorrectionBlockedError(
                    "费用更正恢复查询游标无效",
                    code="FEE_CORRECTION_INPUT_INVALID",
                )


@dataclass(frozen=True, slots=True)
class FeeCorrectionRecoveryItem:
    """Safe public identity and classification for one immutable material binding."""

    source_locator: str
    content_sha256: str
    payload_sha256: str
    stored_at: datetime
    expected_revision: int
    expected_predecessor_id: int | None
    binding_policy_version: int
    current_policy_version: int | None
    state: FeeCorrectionRecoveryState
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class FeeCorrectionRecoveryPage:
    """One stable page of owner-scoped material states without ledger keys."""

    account_id: int
    trade_id: int
    items: tuple[FeeCorrectionRecoveryItem, ...]
    has_more: bool
    next_cursor: str | None


class FeeCorrectionRecoveryRepositoryProtocol(Protocol):
    """Read exact material bindings, event state, and the current policy together."""

    def discover(
        self,
        command: FeeCorrectionRecoveryCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionRecoveryPage:
        """Return one bounded page after locking the current owner scope."""
        ...


class FeeCorrectionRecoveryUseCase:
    """Validate an authenticated recovery read before persistence access."""

    def __init__(self, repository: FeeCorrectionRecoveryRepositoryProtocol) -> None:
        """Use the supplied owner-scoped read repository."""

        self._repository = repository

    def execute(
        self,
        command: FeeCorrectionRecoveryCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionRecoveryPage:
        """Return bounded discovery without exposing the original ledger key."""

        if type(command) is not FeeCorrectionRecoveryCommand:
            raise FeeCorrectionBlockedError(
                "费用更正恢复查询命令无效",
                code="FEE_CORRECTION_INPUT_INVALID",
            )
        command.__post_init__()
        principal_id = getattr(principal, "pk", None)
        if (
            getattr(principal, "is_authenticated", None) is not True
            or type(principal_id) is not int
            or principal_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用更正恢复查询需要当前账户所有者登录",
                code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
            )
        return self._repository.discover(command, principal=principal)


__all__ = [
    "FeeCorrectionRecoveryCommand",
    "FeeCorrectionRecoveryItem",
    "FeeCorrectionRecoveryPage",
    "FeeCorrectionRecoveryRepositoryProtocol",
    "FeeCorrectionRecoveryState",
    "FeeCorrectionRecoveryUseCase",
]
