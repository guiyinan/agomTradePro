"""Account-locked discovery of immutable fee-correction material bindings."""

from __future__ import annotations

from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction_recovery import (
    FeeCorrectionRecoveryCommand,
    FeeCorrectionRecoveryItem,
    FeeCorrectionRecoveryPage,
    FeeCorrectionRecoveryRepositoryProtocol,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_head_repository import (
    DjangoFeeCorrectionHeadRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedTradeModel,
)

from .fee_correction_evidence_repository import DjangoFeeCorrectionEvidenceRepository
from .fee_correction_recovery_support import classify_fee_correction_binding


class DjangoFeeCorrectionRecoveryRepository(FeeCorrectionRecoveryRepositoryProtocol):
    """Read bounded material pages inside the current account and policy lock scope."""

    def __init__(
        self,
        *,
        evidence_repository: DjangoFeeCorrectionEvidenceRepository | None = None,
    ) -> None:
        """Reuse the source verifier used by capture, preview, and persisted history."""

        self._evidence_repository = (
            evidence_repository
            if evidence_repository is not None
            else DjangoFeeCorrectionEvidenceRepository()
        )
        self._head_repository = DjangoFeeCorrectionHeadRepository()

    def discover(
        self,
        command: FeeCorrectionRecoveryCommand,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionRecoveryPage:
        """Classify one locator-ordered page without returning original ledger keys."""

        if type(command) is not FeeCorrectionRecoveryCommand:
            raise FeeCorrectionBlockedError(
                "费用更正恢复查询命令无效", code="FEE_CORRECTION_INPUT_INVALID"
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

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = DjangoFeeCorrectionHeadRepository._lock_owned_account(
                command.account_id,
                principal_id,
            )
            if (
                not SimulatedTradeModel._base_manager.using(DEFAULT_DB_ALIAS)
                .filter(
                    pk=command.trade_id,
                    account_id=account.pk,
                    status="executed",
                )
                .exists()
            ):
                raise FeeCorrectionBlockedError(
                    "目标模拟成交不存在或尚未执行",
                    code="FEE_CORRECTION_TRADE_NOT_FOUND",
                )
            policy = (
                FeeCorrectionEvidencePolicyModel._base_manager.using(DEFAULT_DB_ALIAS)
                .select_for_update()
                .filter(account_id=account.pk)
                .first()
            )
            bindings = FeeCorrectionEvidenceBindingModel._base_manager.using(
                DEFAULT_DB_ALIAS
            ).filter(account_id=account.pk, trade_id=command.trade_id)
            if command.cursor is not None:
                bindings = bindings.filter(public_id__gt=UUID(command.cursor))
            page_rows = list(
                bindings.select_related("artifact", "policy").order_by("public_id")[
                    : command.limit + 1
                ]
            )
            has_more = len(page_rows) > command.limit
            visible = page_rows[: command.limit]
            items: list[FeeCorrectionRecoveryItem] = []
            for binding in visible:
                classification = classify_fee_correction_binding(
                    binding,
                    account=account,
                    current_policy=policy,
                    principal=principal,
                    evidence_repository=self._evidence_repository,
                    history_reader=self._head_repository,
                )
                items.append(
                    FeeCorrectionRecoveryItem(
                        source_locator=str(binding.public_id),
                        content_sha256=binding.content_sha256,
                        payload_sha256=binding.payload_sha256,
                        stored_at=binding.artifact.uploaded_at,
                        expected_revision=binding.expected_revision,
                        expected_predecessor_id=binding.expected_predecessor_id,
                        binding_policy_version=binding.policy_version,
                        current_policy_version=(
                            policy.version
                            if policy is not None and type(policy.version) is int
                            else None
                        ),
                        state=classification.state,
                        reason_code=classification.reason_code,
                    )
                )
            next_cursor = str(visible[-1].public_id) if has_more and visible else None
            return FeeCorrectionRecoveryPage(
                account_id=account.pk,
                trade_id=command.trade_id,
                items=tuple(items),
                has_more=has_more,
                next_cursor=next_cursor,
            )


__all__ = ["DjangoFeeCorrectionRecoveryRepository"]
