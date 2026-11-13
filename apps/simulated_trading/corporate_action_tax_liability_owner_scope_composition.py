"""Current ordinary-owner TAX_WITHHOLD scope for atomic simulated tax journals."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.account.simulated_corporate_action_current_grant_composition import (
    locked_current_simulated_corporate_action_write_grant,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    locked_simulated_action_trading_eligibility,
)
from apps.audit.corporate_action_tax_assessment_composition import TaxAssessmentAuditCoordinatorPort
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityWriteLease,
    _blocked,
    _scope_for_assessment,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    TaxLiabilityAuditOrigin,
    TaxLiabilityReplayRequest,
)
from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
    CurrentTaxAssessmentQualificationPort,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    DjangoRetainedTaxAssessmentAuditVerifier,
)
from apps.simulated_trading.corporate_action_tax_owner_scope_composition import (
    _require_audit_lease,
    _require_outer_read_committed,
    _server_now,
    _utc,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
    TaxLiabilityOperationIdentity,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_readback import (
    DjangoTaxLiabilityReadback,
    VerifiedTaxLiabilityOperation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_payment_basis_reader import (
    read_locked_simulated_dividend_payment_basis,
)


@dataclass(frozen=True, slots=True)
class _ActiveOrigin:
    """Private exact-verifier marker; retained material cannot activate this context."""

    verifier: object
    origin: TaxLiabilityAuditOrigin


_ACTIVE: ContextVar[_ActiveOrigin | None] = ContextVar(
    "simulated_tax_liability_owner_origin", default=None
)


class _ExactFinancialReplay:
    """Require complete original chain evidence before a narrow source timestamp waiver."""

    def __init__(self, *, using: str, audit: TaxAssessmentAuditCoordinatorPort) -> None:
        self._using = using
        self._readback = DjangoTaxLiabilityReadback(
            using=using,
            audit=audit,
            assessment_audit=DjangoRetainedTaxAssessmentAuditVerifier(audit=audit),
        )

    def find(self, request: TaxLiabilityReplayRequest) -> VerifiedTaxLiabilityOperation | None:
        """Find exact intent only after verifying all original journal/Audit/Outbox entries."""
        request.__post_init__()
        assessment = request.assessment
        chain = self._readback.read_chain(
            scope=_scope_for_assessment(assessment),
            canonical_account_namespace="account",
            canonical_account_id=request.canonical_account_id,
            currency=SimulatedDividendTaxCurrency.CNY,
            as_of=_server_now(),
        )
        entries = [
            entry for entry in chain if entry.material.identity.operation_id == request.operation_id
        ]
        if not entries:
            return None
        entry = entries[0]
        identity = TaxLiabilityOperationIdentity(
            request.operation_id,
            _scope_for_assessment(assessment),
            "account",
            request.canonical_account_id,
            SimulatedDividendTaxCurrency.CNY,
            assessment.assessment_revision_id,
            assessment.supersedes_assessment_revision_id,
            assessment.semantic_sha256,
            entry.material.identity.stored_assessment_manifest_sha256,
            request.cash_action,
        )
        if identity != entry.material.identity:
            raise _blocked("Financial operation ID is already bound to different original intent")
        return entry

    def verify_exact_replay_timestamp(
        self,
        *,
        request: TaxLiabilityReplayRequest,
        source: SimulatedAccountRowSourceV2,
        physical_updated_at: datetime,
        physical_cash: Decimal,
        cash_known: bool,
        using: str,
    ) -> datetime | None:
        """Prove the exact operation's own balance/time and original source identity."""
        if using != self._using or cash_known is not True:
            return None
        entry = self.find(request)
        if entry is None:
            return None
        material = entry.material
        origin = material.origin
        if (
            origin.account_source_id != source.source_id
            or origin.account_source_version != source.source_version
            or origin.account_source_sha256 != source.content_hash
            or origin.source_row_updated_at != source.row_updated_at
            or source.underlying_unified_account_id != request.assessment.account_id
            or source.row_user_id != request.assessment.owner_user_id
            or material.physical_updated_after != physical_updated_at
            or material.cash_after != physical_cash
        ):
            return None
        return material.physical_updated_before


def _verify_grant(
    *,
    scope: LockedSimulatedCorporateActionWriteScope,
    grant: SimulatedCorporateActionWriteGrant,
    selector: SimulatedCorporateActionWriteGrantSelector,
    assessment: CorporateActionTaxAssessment,
    as_of: datetime,
    expected_grant_schema: str,
) -> None:
    """Require selected-version withholding policy, terms, owner, and signed grant."""
    if expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        expected_permission = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
    elif expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA:
        expected_permission = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
    else:
        raise _blocked("Financial tax scope requires an explicit V2 or V3 grant schema")
    scope.__post_init__()
    grant.__post_init__()
    binding = selector.binding
    if (
        scope.physical_account_id != assessment.account_id
        or scope.binding != binding
        or binding.account_namespace != "simulated"
        or binding.owner_user_id != assessment.owner_user_id
        or scope.grant_schema != expected_grant_schema
        or scope.capabilities is None
        or Capability.TAX_WITHHOLD not in scope.capabilities
        or grant.selector != selector
        or grant.binding != binding
        or grant.schema != expected_grant_schema
        or grant.permission != expected_permission
        or grant.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        or grant.capabilities is None
        or not all(cap in scope.capabilities for cap in grant.capabilities)
        or not grant.supports_capability(Capability.TAX_WITHHOLD)
        or grant.terms_version != scope.terms_version
        or grant.terms_sha256 != scope.terms_sha256
        or not grant.is_active_at(as_of)
        or grant.valid_until > scope.valid_until
    ):
        raise _blocked("Exact current V2 withholding consent, owner and grant are required")


class DjangoTaxLiabilityOwnerScopeVerifier:
    """Hold actual owner/source/policy/grant/Audit fences around one financial operation."""

    def __init__(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        scope_locker: DjangoSimulatedCorporateActionWriteScopeLocker,
        qualification_provider: CurrentTaxAssessmentQualificationPort,
        audit: TaxAssessmentAuditCoordinatorPort,
        using: str,
        environment: str,
        expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    ) -> None:
        """Require an explicit schema selection, owner authority, and tax qualification."""
        if expected_grant_schema not in (
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        ):
            raise _blocked("Financial tax scope requires an explicit V2 or V3 grant schema")
        if (
            type(selector) is not SimulatedCorporateActionWriteGrantSelector
            or type(scope_locker) is not DjangoSimulatedCorporateActionWriteScopeLocker
        ):
            raise _blocked("Financial tax scope requires actual Account selector and locker")
        selector.__post_init__()
        if (
            not isinstance(qualification_provider, CurrentTaxAssessmentQualificationPort)
            or scope_locker.database_alias != using
            or audit.database_alias != using
            or scope_locker.runtime_environment != environment
        ):
            raise _blocked("Financial tax qualification, authority and Audit configuration differ")
        self._selector, self._locker, self._qualification = (
            selector,
            scope_locker,
            qualification_provider,
        )
        self._using, self._environment = using, environment
        self._expected_grant_schema = expected_grant_schema
        self._replay = _ExactFinancialReplay(using=using, audit=audit)

    @property
    def database_alias(self) -> str:
        """Return the single current-authority and financial-write database alias."""
        return self._using

    def get_locked_audit_origin(self) -> TaxLiabilityAuditOrigin:
        """Return only this verifier's active live origin inside the outer UOW."""
        active = _ACTIVE.get()
        if active is None or active.verifier is not self:
            raise _blocked("Financial Audit origin is outside its exact owner scope")
        _require_outer_read_committed(using=self._using)
        active.origin.__post_init__()
        return active.origin

    def _read_payment_basis(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        lease: TaxLiabilityWriteLease,
        as_of: datetime,
    ) -> SimulatedDividendPaymentBasis:
        """Bind new collection to its exact audited simulated payment under owner locks."""
        return read_locked_simulated_dividend_payment_basis(
            assessment,
            using=self._using,
            canonical_account_namespace=self._selector.binding.account_namespace,
            canonical_account_id=lease.canonical_account_id,
            audit_scope=AuditScopeRef(lease.audit_tenant_id, lease.audit_owner_id),
            as_of=as_of,
        )

    @contextmanager
    def locked_current_scope(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        operation_id: str,
        cash_action: TaxLiabilityCashAction | None,
    ) -> Iterator[TaxLiabilityWriteLease]:
        """Recheck actual current authority and finite eligibility before transaction commit."""
        _require_outer_read_committed(using=using)
        if (
            using != self._using
            or type(assessment) is not CorporateActionTaxAssessment
            or type(actor_user_id) is not int
            or actor_user_id <= 0
            or actor_user_id != assessment.owner_user_id
            or self._selector.binding.owner_user_id != actor_user_id
            or _ACTIVE.get() is not None
        ):
            raise _blocked("Exact nonnested authenticated financial owner scope is required")
        assessment.verify_integrity()
        request = TaxLiabilityReplayRequest(
            assessment, self._selector.binding.account_id, operation_id, cash_action
        )
        with locked_simulated_action_trading_eligibility(user_id=actor_user_id, using=using):
            with self._locker.lock_owned_scope(
                physical_account_id=assessment.account_id,
                owner_user_id=actor_user_id,
                expected_binding=self._selector.binding,
                expected_grant_schema=self._expected_grant_schema,
                tax_replay_request=request,
            ) as locked_scope:
                with locked_current_simulated_corporate_action_write_grant(
                    selector=self._selector,
                    using=using,
                    required_capability=Capability.TAX_WITHHOLD,
                ) as grant:
                    entry_at = _server_now()
                    _verify_grant(
                        scope=locked_scope,
                        grant=grant,
                        selector=self._selector,
                        assessment=assessment,
                        as_of=entry_at,
                        expected_grant_schema=self._expected_grant_schema,
                    )
                    self._locker.assert_tax_source_timestamp_current_or_proven(
                        request=request, verifier=self._replay
                    )
                    source = self._locker.get_locked_tax_source(request=request)
                    original = self._replay.find(request)
                    qualification = (
                        original.material.origin.qualification
                        if original is not None
                        else self._qualification.read_current(
                            assessment,
                            canonical_account_id=self._selector.binding.account_id,
                            environment=self._environment,
                            using=using,
                            as_of=entry_at,
                        )
                    )
                    if type(qualification) is not CurrentTaxAssessmentQualification:
                        raise _blocked("Current financial tax qualification is untyped")
                    if original is None:
                        qualification.verify_for(
                            assessment,
                            canonical_account_id=self._selector.binding.account_id,
                            environment=self._environment,
                            as_of=entry_at,
                        )
                    audit_at = _server_now()
                    if audit_at < entry_at:
                        raise _blocked(
                            "Server clock moved backwards during financial qualification"
                        )
                    audit_lease = _require_audit_lease(
                        environment=self._environment, using=using, as_of=audit_at
                    )
                    deadlines = [
                        locked_scope.valid_until,
                        grant.valid_until,
                        _utc(audit_lease.valid_until, field_name="Audit deadline"),
                    ]
                    if original is None:
                        deadlines.append(qualification.valid_until)
                    if (
                        grant.capabilities is None
                        or grant.terms_version is None
                        or grant.terms_sha256 is None
                    ):
                        raise _blocked(
                            "Explicit current withholding capabilities and terms are required"
                        )
                    lease = TaxLiabilityWriteLease(
                        database_alias=using,
                        actor_user_id=actor_user_id,
                        owner_user_id=actor_user_id,
                        physical_account_id=assessment.account_id,
                        scope=_scope_for_assessment(assessment),
                        canonical_account_namespace="account",
                        canonical_account_id=self._selector.binding.account_id,
                        currency=SimulatedDividendTaxCurrency.CNY,
                        currency_quantum=assessment.policy.currency_quantum,
                        assessment_revision_id=assessment.assessment_revision_id,
                        assessment_semantic_sha256=assessment.semantic_sha256,
                        operation_id=operation_id,
                        cash_action=cash_action,
                        permission=Capability.TAX_WITHHOLD.value,
                        grant_schema=grant.schema,
                        capabilities=grant.capabilities,
                        terms_version=grant.terms_version,
                        terms_sha256=grant.terms_sha256,
                        service_actor_id=grant.service_actor_id,
                        authority_grant_id=grant.grant_id,
                        authority_grant_version=grant.grant_version,
                        authority_grant_content_sha256=grant.content_hash,
                        audit_tenant_id=self._selector.binding.tenant_id,
                        audit_owner_id=self._selector.binding.owner_id,
                        valid_until=min(deadlines),
                    )
                    origin = TaxLiabilityAuditOrigin(
                        lease,
                        self._environment,
                        source.source_id,
                        source.source_version,
                        source.content_hash,
                        source.row_updated_at,
                        qualification,
                        "exact_retry_only" if original is not None else "append",
                        payment_basis=(
                            original.material.origin.payment_basis
                            if original is not None
                            else (
                                self._read_payment_basis(assessment, lease=lease, as_of=audit_at)
                                if cash_action is TaxLiabilityCashAction.COLLECT_AVAILABLE
                                else None
                            )
                        ),
                    )
                    origin.verify_for(
                        assessment,
                        actor_user_id=actor_user_id,
                        operation_id=operation_id,
                        cash_action=cash_action,
                        using=using,
                        as_of=audit_at,
                    )
                    token = _ACTIVE.set(_ActiveOrigin(self, origin))
                    try:
                        yield lease
                        final_at = _server_now()
                        if final_at < audit_at:
                            raise _blocked("Server clock moved backwards before financial commit")
                        if original is None:
                            final_qualification = self._qualification.read_current(
                                assessment,
                                canonical_account_id=self._selector.binding.account_id,
                                environment=self._environment,
                                using=using,
                                as_of=final_at,
                            )
                            if final_qualification != qualification:
                                raise _blocked(
                                    "Current financial tax qualification changed before commit"
                                )
                            if (
                                cash_action is TaxLiabilityCashAction.COLLECT_AVAILABLE
                                and self._read_payment_basis(
                                    assessment, lease=lease, as_of=final_at
                                )
                                != origin.payment_basis
                            ):
                                raise _blocked(
                                    "Audited simulated payment basis changed before tax commit"
                                )
                        elif self._replay.find(request) != original:
                            raise _blocked(
                                "Original financial replay evidence changed before commit"
                            )
                        final_audit = _require_audit_lease(
                            environment=self._environment, using=using, as_of=_server_now()
                        )
                        final_now = _server_now()
                        if (
                            final_now < final_at
                            or _utc(final_audit.valid_until, field_name="Audit deadline")
                            <= final_now
                        ):
                            raise _blocked("Financial Audit readiness expired before commit")
                        origin.verify_for(
                            assessment,
                            actor_user_id=actor_user_id,
                            operation_id=operation_id,
                            cash_action=cash_action,
                            using=using,
                            as_of=final_now,
                        )
                    finally:
                        _ACTIVE.reset(token)
        lease.assert_live(as_of=_server_now())


__all__ = ["DjangoTaxLiabilityOwnerScopeVerifier"]
