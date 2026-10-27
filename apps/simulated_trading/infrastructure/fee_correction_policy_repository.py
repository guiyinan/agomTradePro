"""Django persistence for owner-managed simulated fee evidence policy."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction_policy import (
    FeeCorrectionPolicyCommand,
    FeeCorrectionPolicyRepositoryProtocol,
    FeeCorrectionPolicyState,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


class DjangoFeeCorrectionPolicyRepository(FeeCorrectionPolicyRepositoryProtocol):
    """Lock account, active owner, and policy in the evidence repository's order."""

    def get(
        self,
        account_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Read a policy without creating a row when the owner has no policy yet."""

        principal_user_id = _authenticated_principal_user_id(principal)
        if type(account_id) is not int or account_id <= 0 or principal_user_id is None:
            raise _authority_unavailable()
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = self._lock_owned_account(account_id, principal_user_id)
            policy = (
                FeeCorrectionEvidencePolicyModel.objects.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account.pk)
                .first()
            )
            if policy is None:
                return FeeCorrectionPolicyState(
                    account_id=account.pk,
                    version=0,
                    enabled=False,
                    allow_operator_attested_upload=False,
                    ledger_currency="",
                    valid_from=None,
                    valid_until=None,
                    updated_by_id=None,
                )
            return _policy_state(policy)

    def save(
        self,
        command: FeeCorrectionPolicyCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionPolicyState:
        """Create or update a policy only at its expected owner-scoped version."""

        if type(command) is not FeeCorrectionPolicyCommand:
            raise FeeCorrectionBlockedError(
                "费用证据策略命令无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
            )
        command.__post_init__()
        principal_user_id = _authenticated_principal_user_id(principal)
        if principal_user_id is None:
            raise _authority_unavailable()

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = self._lock_owned_account(command.account_id, principal_user_id)
            policy = (
                FeeCorrectionEvidencePolicyModel.objects.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account.pk)
                .first()
            )
            if policy is None:
                if command.expected_version != 0:
                    raise _policy_conflict()
                policy = FeeCorrectionEvidencePolicyModel(
                    account=account,
                    enabled=command.enabled,
                    allow_operator_attested_upload=command.allow_operator_attested_upload,
                    ledger_currency=command.ledger_currency,
                    version=1,
                    valid_from=command.valid_from,
                    valid_until=command.valid_until,
                    updated_by_id=principal_user_id,
                )
            else:
                if command.expected_version != policy.version:
                    raise _policy_conflict()
                policy.enabled = command.enabled
                policy.allow_operator_attested_upload = command.allow_operator_attested_upload
                policy.ledger_currency = command.ledger_currency
                policy.valid_from = command.valid_from
                policy.valid_until = command.valid_until
                policy.updated_by_id = principal_user_id
            policy.save(using=DEFAULT_DB_ALIAS)
            return _policy_state(policy)

    @staticmethod
    def _lock_owned_account(account_id: int, principal_user_id: int) -> SimulatedAccountModel:
        """Lock and verify account then actor before callers lock the policy row."""

        account = (
            SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=account_id)
            .first()
        )
        if (
            account is None
            or account.account_type != "simulated"
            or account.is_active is not True
            or type(account.user_id) is not int
            or account.user_id != principal_user_id
        ):
            raise _authority_unavailable()

        user_model = get_user_model()
        actor = (
            user_model._base_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=principal_user_id)
            .first()
        )
        if actor is None or getattr(actor, "is_active", None) is not True:
            raise _authority_unavailable()
        return account


def _authenticated_principal_user_id(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
) -> int | None:
    """Narrow the request principal without accepting a numeric body actor."""

    user_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


def _policy_state(policy: FeeCorrectionEvidencePolicyModel) -> FeeCorrectionPolicyState:
    """Copy persisted values into the immutable Application response type."""

    account_id = policy.account_id
    if type(account_id) is not int:
        raise FeeCorrectionBlockedError(
            "费用证据策略账户状态无效", code="FEE_CORRECTION_POLICY_INPUT_INVALID"
        )
    return FeeCorrectionPolicyState(
        account_id=account_id,
        version=policy.version,
        enabled=policy.enabled,
        allow_operator_attested_upload=policy.allow_operator_attested_upload,
        ledger_currency=policy.ledger_currency,
        valid_from=policy.valid_from,
        valid_until=policy.valid_until,
        updated_by_id=policy.updated_by_id,
    )


def _authority_unavailable() -> FeeCorrectionBlockedError:
    """Return the non-disclosing denial used for owner, account, and actor failures."""

    return FeeCorrectionBlockedError(
        "费用证据策略仅由当前有效的模拟账户所有者管理",
        code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
    )


def _policy_conflict() -> FeeCorrectionBlockedError:
    """Return a stable conflict for create/update compare-and-swap failures."""

    return FeeCorrectionBlockedError(
        "费用证据策略版本已变化，请读取当前版本后重试",
        code="FEE_CORRECTION_POLICY_CONFLICT",
    )


__all__ = ["DjangoFeeCorrectionPolicyRepository"]
