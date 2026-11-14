"""Compose ordinary-owner commands with mandatory audited financial boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.data_center.security_disclosure_body_composition import (
    security_disclosure_window_pdf_store_root,
)
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionPreparedIntent,
)
from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    CorporateActionOwnershipProofVerifier,
    CorporateActionPostingReceipt,
    CorporateActionPostingRepositoryProtocol,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
    CurrentTaxAssessmentQualificationPort,
)
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    build_audited_tax_assessment_use_case,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    build_audited_tax_liability_use_case,
)
from apps.simulated_trading.corporate_action_current_official_window_composition import (
    build_corporate_action_current_official_window_reader,
)
from apps.simulated_trading.corporate_action_original_body_composition import (
    DataCenterCorporateActionOriginalBodyVerifier,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.corporate_action_owner_runtime_composition import (
    read_owner_corporate_action_workflow_runtime,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.corporate_action_share_tax_model_composition import (
    DjangoCurrentShareCapitalTaxQualificationReader,
)
from apps.simulated_trading.corporate_action_tax_liability_owner_scope_composition import (
    DjangoTaxLiabilityOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    DjangoTaxAssessmentOwnerScopeVerifier,
)
from apps.simulated_trading.corporate_action_tax_qualification_composition import (
    DjangoCurrentSimulatedTaxQualificationProvider,
)
from apps.simulated_trading.corporate_action_window_audit_composition import (
    CorporateActionWindowAuditGate,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionKind,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_window_codec import (
    encode_corporate_action_tax_window_proof,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
)
from apps.simulated_trading.official_rights_action_composition import (
    VerifiedSzseRightsSourceQualifier,
)
from apps.simulated_trading.transition_plan_disclosure_runtime_policy import (
    ConfiguredTransitionPlanDisclosureRuntimePolicyReader,
)
from core.exceptions import BusinessLogicError


def read_current_owner_action_pdf_root(
    *, account_id: int, owner_user_id: int, environment: str, as_of: datetime
) -> Path:
    """Resolve only the server-configured canonical capture directory at a real cutoff."""
    calendar = build_corporate_action_ownership_history_repository(
        runtime_environment=environment, using=DEFAULT_DB_ALIAS
    ).read_verified_zero_origin_calendar(
        account_id=account_id, owner_user_id=owner_user_id, exchange="SZSE", as_of=as_of
    )
    policy = ConfiguredTransitionPlanDisclosureRuntimePolicyReader(
        runtime_environment=environment
    ).read_policy(
        decision_on=calendar.decision_on,
        earliest_required_on=calendar.origin_on,
        as_of=as_of,
    )
    if policy is None or calendar.as_of != as_of:
        raise BusinessLogicError(
            "请先配置并核对当前官方公告窗口。",
            code="CORPORATE_ACTION_OFFICIAL_WINDOW_POLICY_UNAVAILABLE",
        )
    return security_disclosure_window_pdf_store_root(policy.body_store_root)


class _CurrentSourceQualifier:
    """Resolve source settings only for a new operation, after exact replay detection."""

    def __init__(self, *, environment: str) -> None:
        self._environment = environment

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Reopen actual original bytes through the correct action-specific verifier."""
        root = read_current_owner_action_pdf_root(
            account_id=request.account_id,
            owner_user_id=request.owner_user_id,
            environment=self._environment,
            as_of=timezone.now(),
        )
        if request.action_kind is CorporateActionKind.RIGHTS_ISSUE:
            return VerifiedSzseRightsSourceQualifier(
                body_store_root=root,
                runtime_environment=self._environment,
                using=DEFAULT_DB_ALIAS,
            ).verify_source(request)
        return VerifiedSzseActionSourceQualifier(
            body_store_root=root, using=DEFAULT_DB_ALIAS
        ).verify_source(request)


class DeferredOwnerTaxQualification(CurrentTaxAssessmentQualificationPort):
    """Defer optional routing reads until a new operation actually needs current facts."""

    def __init__(
        self, *, environment: str, source_reference: CorporateActionStageRequest | None = None
    ) -> None:
        """Bind a server-selected runtime environment without reading current sources."""
        self._environment = environment
        self._source_reference = source_reference
        self._window_gate: CorporateActionWindowAuditGate | None = None
        self._window_evidence: CorporateActionCurrentOfficialWindowEvidence | None = None

    def build_provider(
        self, *, account_id: int, owner_user_id: int, as_of: datetime
    ) -> DjangoCurrentSimulatedTaxQualificationProvider:
        """Build the real provider from complete explicit service configuration."""
        runtime = read_owner_corporate_action_workflow_runtime(
            environment=self._environment, as_of=as_of
        )
        root = read_current_owner_action_pdf_root(
            account_id=account_id,
            owner_user_id=owner_user_id,
            environment=self._environment,
            as_of=as_of,
        )
        return DjangoCurrentSimulatedTaxQualificationProvider(
            runtime_environment=self._environment,
            calendar_dataset_key=runtime.calendar_dataset_key,
            statutory_provider_id=runtime.statutory_provider_id,
            statutory_body_store_root=runtime.statutory_body_store_root,
            action_body_store_root=root,
            deployment_region=runtime.deployment_region,
            using=DEFAULT_DB_ALIAS,
        )

    def read_current(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
        using: str,
        as_of: datetime,
    ) -> CurrentTaxAssessmentQualification:
        """Rebuild real current facts inside the established tax authority transaction."""
        if environment != self._environment or using != DEFAULT_DB_ALIAS:
            raise BusinessLogicError(
                "税务核对范围已变化。", code="TAX_QUALIFICATION_SCOPE_MISMATCH"
            )
        qualification = self.build_provider(
            account_id=assessment.account_id,
            owner_user_id=assessment.owner_user_id,
            as_of=as_of,
        ).read_current(
            assessment,
            canonical_account_id=canonical_account_id,
            environment=environment,
            using=using,
            as_of=as_of,
        )
        source_reference = self._source_reference
        if source_reference is None:
            raise BusinessLogicError(
                "缺少本次税务来源核对。", code="TAX_CURRENT_OFFICIAL_WINDOW_INVALID"
            )
        if self._window_gate is None:
            self._window_gate = CorporateActionWindowAuditGate(
                build_corporate_action_current_official_window_reader(
                    runtime_environment=environment,
                    original_body_verifier=DataCenterCorporateActionOriginalBodyVerifier(
                        using=using
                    ),
                    using=using,
                )
            )
        if self._window_evidence is None:
            self._window_evidence = self._window_gate.read_entry_evidence(source_reference)
        else:
            self._window_gate.assert_unchanged(source_reference, self._window_evidence)
        evidence = self._window_evidence
        proof = CorporateActionTaxWindowProof(
            assessment.semantic_sha256, canonical_account_id, source_reference, evidence
        )
        proof.verify_for_assessment(
            assessment, canonical_account_id=canonical_account_id, environment=environment
        )
        if evidence.expires_at is None:
            raise BusinessLogicError(
                "当前官方窗口期限无法核对。", code="TAX_CURRENT_OFFICIAL_WINDOW_INVALID"
            )
        material = {
            "base_qualification_sha256": qualification.qualification_sha256,
            "official_window": encode_corporate_action_tax_window_proof(proof),
        }
        return replace(
            qualification,
            qualification_sha256=hashlib.sha256(
                json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            valid_until=min(qualification.valid_until, evidence.expires_at),
            official_window_proof=proof,
        )


class DeferredOwnerShareCapitalTaxQualification:
    """Resolve actual current model routing only after financial replay detection."""

    def __init__(
        self,
        *,
        environment: str,
        canonical_account_id: str,
        prepared: ShareCapitalTaxQualificationProof | None = None,
    ) -> None:
        """Retain server-selected owner scope and optional original preview comparison."""
        self._environment = environment
        self._canonical_account_id = canonical_account_id
        self._prepared = prepared

    def read_current(
        self, request: CorporateActionStageRequest, *, as_of: datetime
    ) -> ShareCapitalTaxQualificationProof:
        """Read full configured model, actual instrument and retained original source pair."""
        runtime = read_owner_corporate_action_workflow_runtime(
            environment=self._environment, as_of=as_of
        )
        root = read_current_owner_action_pdf_root(
            account_id=request.account_id,
            owner_user_id=request.owner_user_id,
            environment=self._environment,
            as_of=as_of,
        )
        reader = DjangoCurrentShareCapitalTaxQualificationReader(
            environment=self._environment,
            statutory_provider_id=runtime.statutory_provider_id,
            statutory_body_store_root=runtime.statutory_body_store_root,
            action_body_store_root=root,
            deployment_region=runtime.deployment_region,
        )
        proof = reader.read_current(
            request, canonical_account_id=self._canonical_account_id, as_of=as_of
        )
        if self._prepared is not None and proof.selection_sha256 != self._prepared.selection_sha256:
            raise BusinessLogicError(
                "送转模拟模型已变化，请重新准备。", code="SHARE_CAPITAL_TAX_PREVIEW_CHANGED"
            )
        return proof


class _PostingAdapter(CorporateActionPostingRepositoryProtocol):
    """Expose only the audited repository to the generic stage Application boundary."""

    def __init__(self, repository: AuditedCorporateActionPostingRepositoryPort) -> None:
        self._repository = repository

    def post_revision(
        self, requests: tuple[CorporateActionStageRequest, ...]
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        """Commit all requested stages through one mandatory Audit/Outbox unit."""
        return self._repository.post_revision_with_audit(requests)


def execute_owner_corporate_action_intent(
    intent: OwnerCorporateActionPreparedIntent, *, environment: str
) -> (
    tuple[CorporateActionPostingReceipt, ...] | TaxAssessmentWriteReceipt | TaxLiabilityWriteReceipt
):
    """Dispatch exact server-prepared facts with explicit V3 locks and current verification."""
    intent.__post_init__()
    if (
        intent.source_reference.action_kind is CorporateActionKind.SHARE_DISTRIBUTION
        and intent.share_tax_proof is None
    ):
        raise BusinessLogicError(
            "送转办理缺少完整模拟模型核对。", code="SHARE_CAPITAL_TAX_PREVIEW_REQUIRED"
        )
    using = DEFAULT_DB_ALIAS
    locker = DjangoSimulatedCorporateActionWriteScopeLocker(
        database_alias=using, runtime_environment=environment
    )
    provider = DeferredOwnerTaxQualification(
        environment=environment, source_reference=intent.source_reference
    )
    if intent.action == "tax_assess":
        assert intent.assessment is not None
        verifier = DjangoTaxAssessmentOwnerScopeVerifier(
            selector=intent.selector,
            scope_locker=locker,
            qualification_provider=provider,
            using=using,
            environment=environment,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        )
        return build_audited_tax_assessment_use_case(scope_verifier=verifier, using=using).execute(
            intent.assessment, actor_user_id=intent.owner_user_id
        )
    if intent.action in {"tax_recognize", "tax_collect"}:
        assert intent.assessment is not None
        audit = build_tax_assessment_audit_coordinator(using=using)
        liability_verifier = DjangoTaxLiabilityOwnerScopeVerifier(
            selector=intent.selector,
            scope_locker=locker,
            qualification_provider=provider,
            audit=audit,
            using=using,
            environment=environment,
            expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        )
        return build_audited_tax_liability_use_case(
            scope_verifier=liability_verifier, using=using, audit=audit
        ).execute(
            intent.assessment,
            actor_user_id=intent.owner_user_id,
            operation_id=intent.operation_id,
            cash_action=(
                TaxLiabilityCashAction.COLLECT_AVAILABLE if intent.action == "tax_collect" else None
            ),
        )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=intent.selector,
        scope_locker=locker,
        using=using,
        environment=environment,
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    window = CorporateActionWindowAuditGate(
        build_corporate_action_current_official_window_reader(
            runtime_environment=environment,
            original_body_verifier=DataCenterCorporateActionOriginalBodyVerifier(using=using),
            using=using,
        ),
        share_tax_reader=DeferredOwnerShareCapitalTaxQualification(
            environment=environment,
            canonical_account_id=intent.selector.binding.account_id,
            prepared=intent.share_tax_proof,
        ),
    )
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment=environment, owner_grant_gate=gate, window_gate=window
    ).build_posting_repository(
        source_qualifier=_CurrentSourceQualifier(environment=environment),
        ownership_verifier=CorporateActionOwnershipProofVerifier(
            build_corporate_action_ownership_history_repository(
                runtime_environment=environment, using=using
            )
        ),
        tax_basis_verifier=None,
        using=using,
    )
    return PostCorporateActionStageUseCase(_PostingAdapter(repository)).execute(intent.requests)
