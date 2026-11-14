"""Capture a genuinely new official observation before a new owner's posting UOW."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone
from rest_framework.request import Request

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionPreparedIntent,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.corporate_action_owner_account_composition import (
    read_owner_corporate_action_account,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_identity_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    build_official_szse_distribution_refresher,
)
from core.exceptions import BusinessLogicError


def has_retained_owner_posting(intent: OwnerCorporateActionPreparedIntent) -> bool:
    """Skip source I/O when any original stage needs the financial UOW's replay checks.

    Presence gives no replay or financial authority. Partial, changed or corrupt
    originals still fail the mandatory exact ledger/Audit/Outbox validation.
    """
    if intent.action == "tax_assess":
        assert intent.assessment is not None
        return (
            CorporateActionTaxAssessmentHeaderModel._base_manager.using(DEFAULT_DB_ALIAS)
            .filter(
                account_id=intent.account_id,
                owner_user_id=intent.owner_user_id,
                idempotency_key=intent.assessment.calculation.idempotency_key,
            )
            .exists()
        )
    if intent.action in {"tax_recognize", "tax_collect"}:
        return (
            CorporateActionTaxLiabilityOperationModel._base_manager.using(DEFAULT_DB_ALIAS)
            .filter(
                account_id=intent.account_id,
                owner_user_id=intent.owner_user_id,
                operation_id=intent.operation_id,
            )
            .exists()
        )
    return (
        CorporateActionPostingModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(
            account_id=intent.account_id,
            account__user_id=intent.owner_user_id,
            stage_key__in=tuple(row.stage_key for row in intent.requests),
        )
        .exists()
    )


def refresh_new_owner_posting_window(
    request: Request,
    *,
    intent: OwnerCorporateActionPreparedIntent,
    capability: SimulatedCorporateActionWriteCapability,
    environment: str,
) -> None:
    """Requery complete official sources before new postings without renewing any grant.

    Source capture precedes the independent financial transaction. It uses the
    current owner's exact original consent and server-selected security only.
    The executor must still verify every original body, current window, owner,
    role, grant and commit deadline under its own locks. A new tax operation uses
    its own current window; its assessment and original Audit proof stay sealed.
    """
    intent.__post_init__()
    if has_retained_owner_posting(intent):
        return
    account = read_owner_corporate_action_account(
        request, account_id=intent.account_id, capability=capability, require_current_source=True
    )
    if (
        account.owner_user_id != intent.owner_user_id
        or account.grant is None
        or account.grant.selector != intent.selector
        or intent.source_reference.asset_code not in account.asset_codes
    ):
        raise BusinessLogicError(
            "本次原始同意或账户证券范围已变化，请重新核对。",
            code="CORPORATE_ACTION_CONSENT_CHANGED",
        )
    identity = build_current_reference_identity_reader(
        runtime_environment=environment
    ).resolve_current_reference_identity(
        asset_code=intent.source_reference.asset_code, as_of=timezone.now()
    )
    if identity is None or identity.security_id != intent.source_reference.security_id:
        raise BusinessLogicError(
            "当前证券身份无法与原准备结果核对。",
            code="CORPORATE_ACTION_INSTRUMENT_UNAVAILABLE",
        )
    build_official_szse_distribution_refresher(runtime_environment=environment).refresh(
        asset_identities=(
            PortfolioRiskAssetIdentity(intent.source_reference.asset_code, identity.security_id),
        ),
        request_scope=RebalanceJourneyEventRequestScope(
            intent.owner_user_id, intent.account_id, intent.owner_user_id
        ),
        as_of=timezone.now(),
    )
