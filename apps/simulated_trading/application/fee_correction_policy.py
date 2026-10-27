"""Owner-managed qualification policy for simulated fee evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)


def _currency_code_is_valid(value: str) -> bool:
    """Return whether a non-empty currency token follows the stored policy contract."""

    return len(value) == 3 and all("A" <= character <= "Z" for character in value)


def _validate_policy_values(
    *,
    enabled: bool,
    allow_operator_attested_upload: bool,
    ledger_currency: str,
    valid_from: datetime | None,
    valid_until: datetime | None,
    attestation_acknowledged: bool | None,
) -> None:
    """Validate the policy without choosing currency or time defaults."""

    if (
        type(enabled) is not bool
        or type(allow_operator_attested_upload) is not bool
        or type(ledger_currency) is not str
        or type(attestation_acknowledged) not in (bool, type(None))
    ):
        raise FeeCorrectionBlockedError(
            "费用证据策略输入类型无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
        )
    if ledger_currency and not _currency_code_is_valid(ledger_currency):
        raise FeeCorrectionBlockedError(
            "费用证据策略币种必须是三位大写代码",
            code="FEE_CORRECTION_POLICY_INPUT_INVALID",
        )
    if (enabled or allow_operator_attested_upload) and not _currency_code_is_valid(ledger_currency):
        raise FeeCorrectionBlockedError(
            "启用费用证据策略时必须明确指定三位大写账本币种",
            code="FEE_CORRECTION_POLICY_INPUT_INVALID",
        )
    if allow_operator_attested_upload and attestation_acknowledged is not True:
        raise FeeCorrectionBlockedError(
            "启用操作者声明材料必须明确确认其非发行方认证属性",
            code="FEE_CORRECTION_POLICY_INPUT_INVALID",
        )
    for value in (valid_from, valid_until):
        if value is not None and (
            type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
        ):
            raise FeeCorrectionBlockedError(
                "费用证据策略时间必须是带时区时间",
                code="FEE_CORRECTION_POLICY_INPUT_INVALID",
            )
    if valid_from is not None and valid_until is not None and valid_from >= valid_until:
        raise FeeCorrectionBlockedError(
            "费用证据策略有效期必须是非空区间",
            code="FEE_CORRECTION_POLICY_INPUT_INVALID",
        )


@dataclass(frozen=True, slots=True)
class FeeCorrectionPolicyCommand:
    """One owner-confirmed desired state with an optimistic version precondition."""

    account_id: int
    expected_version: int
    enabled: bool
    allow_operator_attested_upload: bool
    ledger_currency: str
    valid_from: datetime | None
    valid_until: datetime | None
    attestation_acknowledged: bool

    def __post_init__(self) -> None:
        """Reject malformed identities, version preconditions, and policy values."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise FeeCorrectionBlockedError(
                "费用证据账户编号无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        if type(self.expected_version) is not int or self.expected_version < 0:
            raise FeeCorrectionBlockedError(
                "费用证据策略预期版本无效",
                code="FEE_CORRECTION_POLICY_INPUT_INVALID",
            )
        if type(self.attestation_acknowledged) is not bool:
            raise FeeCorrectionBlockedError(
                "费用材料声明确认标记无效",
                code="FEE_CORRECTION_POLICY_INPUT_INVALID",
            )
        _validate_policy_values(
            enabled=self.enabled,
            allow_operator_attested_upload=self.allow_operator_attested_upload,
            ledger_currency=self.ledger_currency,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            attestation_acknowledged=self.attestation_acknowledged,
        )


@dataclass(frozen=True, slots=True)
class FeeCorrectionPolicyState:
    """Persisted policy state or a version-zero disabled state when no row exists."""

    account_id: int
    version: int
    enabled: bool
    allow_operator_attested_upload: bool
    ledger_currency: str
    valid_from: datetime | None
    valid_until: datetime | None
    updated_by_id: int | None

    def __post_init__(self) -> None:
        """Validate the state returned from storage without adding business defaults."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise FeeCorrectionBlockedError(
                "费用证据策略账户状态无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        if type(self.version) is not int or self.version < 0:
            raise FeeCorrectionBlockedError(
                "费用证据策略状态版本无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        if self.updated_by_id is not None and (
            type(self.updated_by_id) is not int or self.updated_by_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "费用证据策略更新者无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        _validate_policy_values(
            enabled=self.enabled,
            allow_operator_attested_upload=self.allow_operator_attested_upload,
            ledger_currency=self.ledger_currency,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            attestation_acknowledged=(True if self.allow_operator_attested_upload else None),
        )
        if self.version == 0 and (
            self.enabled
            or self.allow_operator_attested_upload
            or self.ledger_currency
            or self.valid_from is not None
            or self.valid_until is not None
            or self.updated_by_id is not None
        ):
            raise FeeCorrectionBlockedError(
                "缺失费用证据策略必须返回版本零的禁用状态",
                code="FEE_CORRECTION_POLICY_INPUT_INVALID",
            )


class FeeCorrectionPolicyRepositoryProtocol(Protocol):
    """Read and update one current owner-scoped fee evidence policy."""

    def get(
        self,
        account_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Read the owner's policy, returning disabled version zero when absent."""
        ...

    def save(
        self,
        command: FeeCorrectionPolicyCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Create or compare-and-swap the owner's explicitly confirmed policy."""
        ...


class FeeCorrectionPolicyUseCase:
    """Validate an authenticated owner request before policy persistence."""

    def __init__(self, repository: FeeCorrectionPolicyRepositoryProtocol) -> None:
        """Store the persistence boundary used for owner-scoped policy state."""

        self._repository = repository

    def get(
        self,
        account_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Return one owner's current qualification policy or its disabled default."""

        self._validate_account_id(account_id)
        self._validate_principal(principal)
        return self._repository.get(account_id, principal=principal)

    def save(
        self,
        command: FeeCorrectionPolicyCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Persist an explicit policy update using the owner's authenticated identity."""

        if type(command) is not FeeCorrectionPolicyCommand:
            raise FeeCorrectionBlockedError(
                "费用证据策略命令无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        command.__post_init__()
        self._validate_principal(principal)
        return self._repository.save(command, principal=principal)

    @staticmethod
    def _validate_account_id(account_id: int) -> None:
        """Reject bools and non-positive IDs before crossing the repository boundary."""

        if type(account_id) is not int or account_id <= 0:
            raise FeeCorrectionBlockedError(
                "费用证据账户编号无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )

    @staticmethod
    def _validate_principal(
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> None:
        """Require a real authenticated principal instead of a body-supplied user ID."""

        user_id = getattr(principal, "pk", None)
        if (
            getattr(principal, "is_authenticated", None) is not True
            or type(user_id) is not int
            or user_id <= 0
        ):
            raise FeeCorrectionBlockedError(
                "管理费用证据策略需要有效的已认证账户所有者",
                code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
            )


__all__ = [
    "FeeCorrectionPolicyCommand",
    "FeeCorrectionPolicyRepositoryProtocol",
    "FeeCorrectionPolicyState",
    "FeeCorrectionPolicyUseCase",
]
