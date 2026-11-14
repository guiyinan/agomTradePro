"""Compose the ordinary owner's explicit simulated corporate-action workflow."""

from __future__ import annotations

import logging
from datetime import UTC, date
from typing import cast
from uuid import uuid4

from django.db import DEFAULT_DB_ALIAS, DatabaseError
from django.utils import timezone
from rest_framework.request import Request

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.domain.system_audit_event import JSONValue
from apps.audit.retained_system_audit_pair_composition import (
    RETAINED_SYSTEM_AUDIT_READ_FAILURES,
)
from apps.data_center.domain.security_disclosure_event import SzseDistributionTerms
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OWNER_CORPORATE_ACTION_OPERATIONS,
    OwnerCorporateActionOperation,
    OwnerCorporateActionPreparedIntent,
)
from apps.simulated_trading.application.corporate_action_owner_revision_preview import (
    OwnerCorporateActionRevisionPreview,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityWriteReceipt,
)
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
)
from apps.simulated_trading.corporate_action_account_refresh_composition import (
    refresh_owner_simulated_account_evidence,
)
from apps.simulated_trading.corporate_action_current_official_window_composition import (
    build_corporate_action_current_official_window_reader,
)
from apps.simulated_trading.corporate_action_original_body_composition import (
    DataCenterCorporateActionOriginalBodyVerifier,
)
from apps.simulated_trading.corporate_action_owner_account_composition import (
    OwnerCorporateActionAccount,
    read_owner_corporate_action_account,
    read_owner_corporate_action_confirmation_owner,
)
from apps.simulated_trading.corporate_action_owner_confirmation_window import (
    refresh_new_owner_posting_window,
)
from apps.simulated_trading.corporate_action_owner_event_composition import (
    prepare_owner_official_corporate_action,
)
from apps.simulated_trading.corporate_action_owner_execution_composition import (
    DeferredOwnerShareCapitalTaxQualification,
    execute_owner_corporate_action_intent,
)
from apps.simulated_trading.corporate_action_owner_revision_composition import (
    prepare_owner_official_corporate_action_revision,
)
from apps.simulated_trading.corporate_action_owner_tax_prepare_composition import (
    prepare_owner_corporate_action_tax_assessment,
)
from apps.simulated_trading.corporate_action_owner_workflow_readback import (
    empty_owner_workflow_payload,
    read_owner_workflow_payload,
    read_owner_workflow_source_payload,
    select_owner_workflow_event,
)
from apps.simulated_trading.corporate_action_window_audit_composition import (
    CorporateActionWindowAuditGate,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionStageRequest,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_identity_reader,
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.corporate_action_owner_intent_codec import (
    owner_corporate_action_session_binding,
    restore_owner_corporate_action_intent,
    seal_owner_corporate_action_intent,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    build_official_szse_distribution_refresher,
)
from core.exceptions import AgomTradeProException, AuthorizationError, BusinessLogicError

_logger = logging.getLogger(__name__)
_COMMITTED_READBACK_FAILURES: tuple[type[Exception], ...] = (
    AgomTradeProException,
    DatabaseError,
    OSError,
    ArithmeticError,
    ValueError,
    TypeError,
) + RETAINED_SYSTEM_AUDIT_READ_FAILURES
_ACTION_LABELS = {
    "cash_entitlement": "登记模拟现金权益",
    "cash_payment": "模拟分红到账",
    "share_entitlement": "登记送转权益",
    "share_delivery": "送转记入模拟持仓",
    "share_sellable_release": "释放模拟可用股份",
    "rights_not_exercised": "登记模拟未参与配股",
    "tax_assess": "评估模拟后扣税",
    "tax_recognize": "确认模拟应付税款",
    "tax_collect": "模拟扣缴税款",
}


def capability_for_owner_operation(action: str) -> Capability:
    """Map each exact supported operation to its independent existing permission."""
    if type(action) is not str or action not in OWNER_CORPORATE_ACTION_OPERATIONS:
        raise BusinessLogicError(
            "请选择明确的公司行动办理项目。", code="CORPORATE_ACTION_OWNER_OPERATION_INVALID"
        )
    if action.startswith("cash_"):
        return Capability.CASH_STAGE_WRITE
    if action.startswith("share_"):
        return Capability.SHARE_STAGE_WRITE
    if action == "rights_not_exercised":
        return Capability.RIGHTS_NOT_EXERCISED
    return Capability.TAX_ASSESS if action == "tax_assess" else Capability.TAX_WITHHOLD


def read_owner_preparation_window(
    reference: CorporateActionStageRequest,
    *,
    environment: str,
) -> CorporateActionCurrentOfficialWindowEvidence:
    """Verify real original bodies and the complete current window before previewing."""
    return CorporateActionWindowAuditGate(
        build_corporate_action_current_official_window_reader(
            runtime_environment=environment,
            original_body_verifier=DataCenterCorporateActionOriginalBodyVerifier(
                using=DEFAULT_DB_ALIAS
            ),
            using=DEFAULT_DB_ALIAS,
        )
    ).read_entry_evidence(reference)


def _blocked_payload(account_id: int, error: AgomTradeProException) -> dict[str, JSONValue]:
    payload = empty_owner_workflow_payload(account_id)
    payload["checked_at"] = timezone.now().isoformat()
    payload["blocking_reason"] = error.code
    if error.code in {
        "CORPORATE_ACTION_SELECTED_CAPABILITY_REQUIRED",
        "CORPORATE_ACTION_CONSENT_CHANGED",
    }:
        next_step = "请打开本账户的公司行为授权，明确勾选本次办理所需的分项能力，再重新准备。"
    elif error.code in {
        "CORPORATE_ACTION_ACCOUNT_REFRESH_REQUIRED",
        "CORPORATE_ACTION_PREPARATION_EXPIRED",
    }:
        next_step = "请先刷新本账户与官方资料，再核对授权并重新准备。"
    elif error.code == "CORPORATE_ACTION_TAX_ASSESS_FIRST":
        next_step = "请为同一事件和结算日期先评估模拟税额，再确认应付税款或办理扣缴。"
    elif error.code == "CORPORATE_ACTION_TAX_REASSESS_REQUIRED":
        next_step = "来源或税务事实已变化，请为同一结算日期重新评估模拟税额。"
    elif error.code in {
        "CORPORATE_ACTION_TAX_DATE_REQUIRED",
        "CORPORATE_ACTION_OWNER_SETTLEMENT_DATE_REQUIRED",
    }:
        next_step = "请选择本次需要核对的明确结算日期，再准备税务操作。"
    elif error.code == "CORPORATE_ACTION_CONFIRMATION_INVALID":
        next_step = "本次确认凭证无法核对，请重新读取本账户并准备；已办事项请先核对原始回执。"
    elif error.code == "CORPORATE_ACTION_OWNER_STAGE_ALREADY_RECORDED":
        next_step = "该阶段已有原始回执，请查看审计回执；重试请使用原确认，不要新建办理。"
    elif error.code in {
        "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED",
        "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRES_FULL_REPLAY",
    }:
        next_step = (
            "新披露需要核对整批已办事项，请明确选择按新披露整批更正，再逐项核对冲正和重建预览。"
        )
    elif error.code == "CORPORATE_ACTION_OWNER_TAX_REVISION_UNSUPPORTED":
        next_step = "该事件已有税务账本，当前不支持相关税务修订及退款；本次更正已阻断，请联系管理员核对原始回执。"
    elif error.code == "CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE":
        next_step = "审计服务的当前授权无法核对，请联系管理员恢复服务授权后重新准备。"
    else:
        next_step = "当前资料不能完整核对，请先刷新本账户与官方资料；仍被阻断时请联系管理员核对来源及模型配置。"
    payload["summary"] = "本次尚未办理。" + next_step
    return payload


def read_owner_corporate_action_workflow(
    request: Request, *, account_id: int
) -> dict[str, JSONValue]:
    """Read the actual owner's retained history without performing any capture or write."""
    try:
        account = read_owner_corporate_action_account(request, account_id=account_id)
        return read_owner_workflow_payload(account)
    except AuthorizationError:
        raise
    except AgomTradeProException as error:
        return _blocked_payload(account_id, error)


def read_owner_corporate_action_events(
    request: Request, *, account_id: int
) -> dict[str, JSONValue]:
    """Discover retained owner events independently of financial readback or qualification."""
    try:
        account = read_owner_corporate_action_account(request, account_id=account_id)
        return read_owner_workflow_source_payload(account)
    except AuthorizationError:
        raise
    except AgomTradeProException as error:
        return _blocked_payload(account_id, error)


def prepare_owner_corporate_action_workflow(
    request: Request,
    *,
    account_id: int,
    event_id: str,
    action: str,
    settlement_date: date | None = None,
    correction_mode: str = "ordinary",
) -> dict[str, JSONValue]:
    """Prepare complete server-selected facts after actual owner, capability and source checks."""
    capability = capability_for_owner_operation(action)
    # Ownership must precede even looking up a user-supplied event identity.
    try:
        if type(correction_mode) is not str or correction_mode not in {
            "ordinary",
            "correct_existing",
        }:
            raise BusinessLogicError(
                "请明确选择首次办理、继续下一阶段或整批更正。",
                code="CORPORATE_ACTION_OWNER_CORRECTION_MODE_INVALID",
            )
        account = read_owner_corporate_action_account(
            request, account_id=account_id, capability=capability, require_current_source=True
        )
        binding = owner_corporate_action_session_binding(request)
        environment = get_simulated_execution_runtime_environment()
        started = timezone.now()
        selected = select_owner_workflow_event(account, event_id=event_id, as_of=started)
        operation = cast(OwnerCorporateActionOperation, action)
        if correction_mode == "correct_existing":
            if settlement_date is not None:
                raise BusinessLogicError(
                    "整批更正使用已核对的披露日期，请勿另填税务结算日期。",
                    code="CORPORATE_ACTION_OWNER_REVISION_SETTLEMENT_DATE_UNSUPPORTED",
                )
            prepared = prepare_owner_official_corporate_action_revision(
                account_id=account_id,
                canonical_account_id=account.source.account_id,
                owner_user_id=account.owner_user_id,
                asset_code=selected.asset_code,
                event_id=event_id,
                action=operation,
                as_of=started,
                runtime_environment=environment,
                using=DEFAULT_DB_ALIAS,
            )
        else:
            prepared = prepare_owner_official_corporate_action(
                account_id=account_id,
                canonical_account_id=account.source.account_id,
                owner_user_id=account.owner_user_id,
                asset_code=selected.asset_code,
                event_id=event_id,
                action=operation,
                settlement_date=settlement_date,
                as_of=started,
                runtime_environment=environment,
                using=DEFAULT_DB_ALIAS,
            )
        revision_preview = prepared.revision_preview
        if correction_mode == "correct_existing":
            if type(revision_preview) is not OwnerCorporateActionRevisionPreview:
                raise BusinessLogicError(
                    "整批更正的逐项预览尚未完整核对，请重新准备。",
                    code="CORPORATE_ACTION_OWNER_REVISION_PREVIEW_INVALID",
                )
            revision_preview.__post_init__()
            if (
                revision_preview.prepared_batch.requests != prepared.requests
                or revision_preview.prepared_batch.gate_anchor != prepared.source_reference
            ):
                raise BusinessLogicError(
                    "整批更正的预览与本次事项不一致，请重新准备。",
                    code="CORPORATE_ACTION_OWNER_REVISION_PREVIEW_INVALID",
                )
        elif revision_preview is not None or any(
            row.entry_kind
            in {CorporateActionEntryKind.REVERSAL, CorporateActionEntryKind.SUCCESSOR}
            for row in prepared.requests
        ):
            raise BusinessLogicError(
                "新披露需要整批更正，请明确选择更正已办事项并重新核对。",
                code="CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED",
            )
        evidence = read_owner_preparation_window(prepared.source_reference, environment=environment)
        share_tax_proof = None
        if action in {"share_entitlement", "share_delivery", "share_sellable_release"}:
            share_tax_proof = DeferredOwnerShareCapitalTaxQualification(
                environment=environment, canonical_account_id=account.source.account_id
            ).read_current(prepared.source_reference, as_of=timezone.now())
        assessment = None
        corrects_assessment = False
        if action.startswith("tax_"):
            if prepared.tax_action is None or type(settlement_date) is not date:
                raise BusinessLogicError(
                    "税务办理需要明确的结算日期和完整来源。",
                    code="CORPORATE_ACTION_TAX_DATE_REQUIRED",
                )
            preview = prepare_owner_corporate_action_tax_assessment(
                action=prepared.tax_action,
                operation=operation,
                canonical_account_id=account.source.account_id,
                settlement_date=settlement_date,
                environment=environment,
            )
            assessment, corrects_assessment = (
                preview.assessment,
                preview.corrects_existing_assessment,
            )
        checked = timezone.now()
        deadline = account.preparation_valid_until
        if (
            account.grant is None
            or deadline is None
            or evidence.expires_at is None
            or evidence.checked_at is None
            or checked < started
            or checked < evidence.checked_at
            or checked >= min(deadline, evidence.expires_at)
        ):
            raise BusinessLogicError(
                "本次资料核对已到期，请刷新后重新准备。",
                code="CORPORATE_ACTION_PREPARATION_EXPIRED",
            )
        intent = OwnerCorporateActionPreparedIntent(
            action=operation,
            account_id=account_id,
            owner_user_id=account.owner_user_id,
            selector=account.grant.selector,
            source_reference=prepared.source_reference,
            requests=prepared.requests,
            assessment=assessment,
            operation_id=f"owner-action-{uuid4().hex}",
            prepared_at=checked,
            # A preview has checked its original window. New operations recheck
            # it under financial locks; exact retries retain the original facts.
            # Do not make an expired source window revoke historical readback.
            valid_until=account.grant.valid_until,
            share_tax_proof=share_tax_proof,
        )
        token = seal_owner_corporate_action_intent(intent, session_binding=binding)
        payload = empty_owner_workflow_payload(account_id)
        payload.update(
            {
                "outcome": "success",
                "summary": _preparation_summary(
                    intent,
                    corrects_assessment,
                    source_terms=getattr(prepared, "source_terms", None),
                    revision_preview=prepared.revision_preview,
                ),
                "blocking_reason": None,
                "checked_at": checked.isoformat(),
                "source_observed_at": prepared.source_reference.source_observed_at.isoformat(),
                "freshness_status": "current_window_checked",
                "reliability_status": "preview_only",
                "continuation": {
                    "action_key": "simulated-trading.corporate-action-workflow-confirm",
                    "input": {"account_id": str(account_id), "continuation_token": token},
                    "expires_at": intent.valid_until.astimezone(UTC).isoformat(),
                },
            }
        )
        return payload
    except AuthorizationError:
        raise
    except AgomTradeProException as error:
        return _blocked_payload(account_id, error)


def _preparation_summary(
    intent: OwnerCorporateActionPreparedIntent,
    corrects_assessment: bool,
    *,
    source_terms: SzseDistributionTerms | None = None,
    revision_preview: OwnerCorporateActionRevisionPreview | None = None,
) -> str:
    reference = intent.source_reference
    dates = (
        f"登记日 {reference.record_date.isoformat()}；除权息日 {reference.effective_date.isoformat()}；"
        f'到账日 {source_terms.payment_date.isoformat() if source_terms is not None and source_terms.payment_date is not None else (reference.payment_date.isoformat() if reference.payment_date is not None else "尚未确认")}。'
    )
    if source_terms is not None and source_terms.shares_per_ten is not None:
        dates += (
            f'送转入账日 {source_terms.share_delivery_date.isoformat() if source_terms.share_delivery_date is not None else "尚未确认"}；'
            f'首个可用股份日 {source_terms.share_sellable_date.isoformat() if source_terms.share_sellable_date is not None else "尚未确认"}。'
        )
    if revision_preview is not None:
        if (
            revision_preview.prepared_batch.requests != intent.requests
            or revision_preview.prepared_batch.gate_anchor != reference
        ):
            raise BusinessLogicError(
                "整批更正预览无法与原确认事项核对，请重新准备。",
                code="CORPORATE_ACTION_OWNER_REVISION_PREVIEW_INVALID",
            )
        changes: list[str] = []
        for row in revision_preview.rows:
            label = _ACTION_LABELS.get(row.stage.value, "未识别办理阶段")
            operation = (
                f"冲正原账项 {row.reverses_entry_id}"
                if row.entry_kind is CorporateActionEntryKind.REVERSAL
                else "按新披露重建"
            )
            delta = row.signed_delta
            changes.append(
                f"{operation}（{label}）：现金 {delta.cash:+f} 元、分红应收 {delta.cash_receivable:+f} 元、"
                f"持仓 {delta.shares:+f} 股、送转应收 {delta.share_receivable:+f} 股、"
                f"可用股份 {delta.available_shares:+f} 股"
            )
        return (
            f"仅模拟整批更正：{reference.asset_code}，{dates}"
            f"来源修订 {revision_preview.previous_source_revision_id} → {revision_preview.current_source_revision_id}。"
            + "；".join(changes)
            + "。本次将整批冲正并按新披露重建，全部成功才生效；请逐项核对后明确确认。"
        )
    if intent.assessment is not None:
        assessment = intent.assessment
        return (
            f"仅模拟核对：{reference.asset_code}，{dates}模拟税务结算日 {assessment.target_settlement_date.isoformat()}；本次评估税额 {assessment.calculation.withholding_amount} 元。"
            + ("本次将修订已有评估。" if corrects_assessment else "")
            + (
                "实际扣缴以未缴税额及可扣现金为限。"
                if intent.action == "tax_collect"
                else "本步骤不扣款。"
            )
            + f"办理项目：{_ACTION_LABELS[intent.action]}。请核对日期与金额后明确确认。"
        )
    amounts = "；".join(
        (
            f"阶段金额 {request.cash_amount} 元"
            if request.cash_amount is not None
            else (
                f"阶段股份 {request.share_amount} 股"
                if request.share_amount is not None
                else "未参与配股，不扣款、不增持"
            )
        )
        for request in intent.requests
    )
    return f"仅模拟办理：{reference.asset_code}，{dates}{_ACTION_LABELS[intent.action]}，{amounts}。请核对后明确确认。"


def _committed_summary(
    receipt: (
        tuple[CorporateActionPostingReceipt, ...]
        | TaxAssessmentWriteReceipt
        | TaxLiabilityWriteReceipt
    ),
) -> str:
    if isinstance(receipt, tuple):
        identities = ", ".join(str(row.entry_id) for row in receipt)
        return f"模拟办理已完成，原始账本回执：{identities}。重复确认只读回原始结果。"
    if isinstance(receipt, TaxAssessmentWriteReceipt):
        return (
            f"模拟税务评估已留存，原始评估回执：{receipt.assessment_revision_id}；本步骤没有扣款。"
        )
    return f"模拟税务办理已完成，原始操作回执：{receipt.operation_id}；现金变化 {receipt.cash_delta} 元。"


def _read_after_commit(
    account: OwnerCorporateActionAccount,
    *,
    summary: str,
    include_balances: bool = True,
) -> dict[str, JSONValue]:
    try:
        payload = (
            read_owner_workflow_payload(account)
            if include_balances
            else read_owner_workflow_source_payload(account)
        )
    except _COMMITTED_READBACK_FAILURES:
        # Financial UOW has returned successfully. Never turn a later display
        # failure into a claim of rollback or encourage a different new command.
        _logger.warning(
            "Committed owner corporate action awaits independent display readback",
            extra={"account_id": account.account_id},
        )
        payload = empty_owner_workflow_payload(account.account_id)
        payload["blocking_reason"] = "CORPORATE_ACTION_COMMITTED_READBACK_PENDING"
        payload["checked_at"] = timezone.now().isoformat()
        payload["summary"] = (
            summary + " 当前余额与详细审计读回暂不可用，请保留本回执并重新读取；不要重复新建办理。"
        )
    else:
        payload["summary"] = summary + (
            " 详细余额仍以完整核对状态为准。"
            if include_balances
            else " 余额与原始财务回执请通过读取账户回执单独核对。"
        )
    payload["outcome"] = "success"
    return payload


def _committed_owner_workflow_payload(*, account_id: int, summary: str) -> dict[str, JSONValue]:
    """Acknowledge committed originals; full balances and Audit history are an independent read."""
    payload = empty_owner_workflow_payload(account_id)
    payload.update(
        {
            "outcome": "success",
            "blocking_reason": "CORPORATE_ACTION_COMMITTED_READBACK_PENDING",
            "checked_at": timezone.now().isoformat(),
            "summary": summary + " 余额与详细审计回执请通过读取账户回执单独核对。",
        }
    )
    return payload


def _audit_authority_unavailable() -> BusinessLogicError:
    """Publish a stable owner-facing block without internal authority diagnostics."""
    return BusinessLogicError(
        "审计服务的当前授权无法核对，请待服务授权恢复后重新准备。",
        code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
    )


def confirm_owner_corporate_action_workflow(
    request: Request,
    *,
    account_id: int,
    continuation_token: str,
    confirmed: bool,
) -> dict[str, JSONValue]:
    """Execute only exact session-bound originals through mandatory audited financial locks."""
    if type(confirmed) is not bool:
        raise ValueError("confirmation must be a literal boolean")
    if confirmed is False:
        payload = empty_owner_workflow_payload(account_id)
        payload.update(
            {"outcome": "noop", "summary": "已取消，本次没有办理。", "blocking_reason": None}
        )
        return payload
    owner_user_id = read_owner_corporate_action_confirmation_owner(request, account_id=account_id)
    try:
        intent = restore_owner_corporate_action_intent(
            continuation_token,
            owner_user_id=owner_user_id,
            account_id=account_id,
            session_binding=owner_corporate_action_session_binding(request),
            as_of=timezone.now(),
        )
        environment = get_simulated_execution_runtime_environment()
        refresh_new_owner_posting_window(
            request,
            intent=intent,
            capability=capability_for_owner_operation(intent.action),
            environment=environment,
        )
        receipt = execute_owner_corporate_action_intent(intent, environment=environment)
    except AuthorizationError:
        raise
    except SystemAuditCompositionUnavailable:
        return _blocked_payload(account_id, _audit_authority_unavailable())
    except AgomTradeProException as error:
        return _blocked_payload(account_id, error)
    return _committed_owner_workflow_payload(
        account_id=account_id, summary=_committed_summary(receipt)
    )


def refresh_owner_corporate_action_workflow(
    request: Request,
    *,
    account_id: int,
    confirmed: bool,
) -> dict[str, JSONValue]:
    """Explicitly refresh ownership and actual official source captures, never financial entries."""
    if type(confirmed) is not bool:
        raise ValueError("refresh confirmation must be a literal boolean")
    if confirmed is False:
        payload = empty_owner_workflow_payload(account_id)
        payload.update(
            {"outcome": "noop", "summary": "已取消，本次没有刷新。", "blocking_reason": None}
        )
        return payload
    # The actual refresh service checks trading role, owner and locks before
    # appending Raw/Source/Account evidence. Source I/O begins after it commits.
    refreshed = refresh_owner_simulated_account_evidence(request, account_id=account_id)
    account = read_owner_corporate_action_account(request, account_id=account_id)
    try:
        environment = get_simulated_execution_runtime_environment()
        reader = build_current_reference_identity_reader(runtime_environment=environment)
        identities: list[PortfolioRiskAssetIdentity] = []
        for code in account.asset_codes:
            if not code.endswith(".SZ"):
                raise BusinessLogicError(
                    "本入口当前只支持已配置的深市官方窗口。",
                    code="CORPORATE_ACTION_SOURCE_SCOPE_UNSUPPORTED",
                )
            identity = reader.resolve_current_reference_identity(
                asset_code=code, as_of=timezone.now()
            )
            if identity is None:
                raise BusinessLogicError(
                    "证券身份尚未核对，请先完成资料配置。",
                    code="CORPORATE_ACTION_INSTRUMENT_UNAVAILABLE",
                )
            identities.append(PortfolioRiskAssetIdentity(code, identity.security_id))
        if identities:
            build_official_szse_distribution_refresher(runtime_environment=environment).refresh(
                asset_identities=tuple(identities),
                request_scope=RebalanceJourneyEventRequestScope(
                    account.owner_user_id, account_id, account.owner_user_id
                ),
                as_of=timezone.now(),
            )
    except (AgomTradeProException, SystemAuditCompositionUnavailable) as error:
        block = (
            error if isinstance(error, AgomTradeProException) else _audit_authority_unavailable()
        )
        payload = _blocked_payload(account_id, block)
        payload.update(
            {
                "outcome": "partial",
                "summary": "账户权属证据已刷新；官方事件资料尚未完整刷新，请核对阻断原因后重试。",
                "source_observed_at": refreshed.source_observed_at.isoformat(),
            }
        )
        return payload
    return _read_after_commit(
        account,
        summary="账户权属证据与所请求官方资料已刷新；本次没有新增财务分录。",
        include_balances=False,
    )
