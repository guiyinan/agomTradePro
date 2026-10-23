"""Owner checks for read-only temporary-target previews."""

from __future__ import annotations

from typing import Protocol

from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporaryTargetValidationError,
)


class TemporaryTargetOwnerRepository(Protocol):
    """Read one owner-scoped account row for a temporary-target request."""

    def get_account_model_for_user(self, account_id: int, user_id: int) -> object | None:
        """Return the account row only when both identifiers match."""


def require_temporary_target_account_owner(*, account_id: int, user_id: int | None) -> None:
    """Require an exact owner, active row, and simulated account before preview reads."""

    if type(account_id) is not int or account_id <= 0:
        raise TemporaryTargetValidationError("TARGET_ACCOUNT_ID_INVALID", "账户编号无效。")
    if type(user_id) is not int or user_id <= 0:
        raise TemporaryTargetValidationError(
            "TARGET_OWNER_REQUIRED", "请从本人已启用的模拟账户生成本次预览。"
        )

    account_repository: TemporaryTargetOwnerRepository = get_simulated_account_repository()
    account = account_repository.get_account_model_for_user(account_id, user_id)
    if account is None:
        raise TemporaryTargetValidationError(
            "TARGET_ACCOUNT_NOT_OWNED", "仅可为本人已启用的模拟账户生成本次预览。"
        )
    account_row_id = getattr(account, "id", None)
    account_owner_id = getattr(account, "user_id", None)
    if (
        type(account_row_id) is not int
        or account_row_id != account_id
        or type(account_owner_id) is not int
        or account_owner_id != user_id
    ):
        raise TemporaryTargetValidationError(
            "TARGET_ACCOUNT_NOT_OWNED", "仅可为本人已启用的模拟账户生成本次预览。"
        )
    if getattr(account, "is_active", None) is not True:
        raise TemporaryTargetValidationError(
            "TARGET_ACCOUNT_INACTIVE", "账户未启用，不能生成本次临时目标预览。"
        )
    account_type = getattr(account, "account_type", None)
    if type(account_type) is not str or account_type != AccountType.SIMULATED.value:
        raise TemporaryTargetValidationError(
            "TARGET_ACCOUNT_NOT_SIMULATED", "临时目标只支持本人模拟账户。"
        )
