"""Exact live financial origin and narrow historical-operation replay contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading.application.corporate_action_tax_liability import (
    CurrentTaxLiabilityScopeVerifierPort,
    TaxLiabilityWriteLease,
    _aware,
    _blocked,
    _digest,
    _token,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityCashAction
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


@dataclass(frozen=True, slots=True)
class TaxLiabilityAuditOrigin:
    """Live verifier result; persisted copies describe history and grant no new authority."""

    lease: TaxLiabilityWriteLease
    environment: str
    account_source_id: str
    account_source_version: str
    account_source_sha256: str
    source_row_updated_at: datetime
    qualification: CurrentTaxAssessmentQualification
    write_mode: Literal["append", "exact_retry_only"]

    def __post_init__(self) -> None:
        """Bind actual qualification and source evidence to one financial owner scope."""
        if type(self.lease) is not TaxLiabilityWriteLease:
            raise _blocked("financial Audit origin has no exact current lease")
        self.lease.__post_init__()
        _token(self.environment, field_name="origin environment", limit=64)
        _token(self.account_source_id, field_name="origin account source id")
        _token(self.account_source_version, field_name="origin account source version", limit=128)
        _digest(self.account_source_sha256, field_name="origin account source hash")
        _aware(self.source_row_updated_at, field_name="origin source row clock")
        if type(self.qualification) is not CurrentTaxAssessmentQualification:
            raise _blocked("financial Audit origin has no exact qualification result")
        self.qualification.__post_init__()
        if (
            self.write_mode not in {"append", "exact_retry_only"}
            or self.qualification.account_id != self.lease.physical_account_id
            or self.qualification.owner_user_id != self.lease.owner_user_id
            or self.qualification.canonical_account_id != self.lease.canonical_account_id
            or self.qualification.environment != self.environment
            or self.qualification.assessment_semantic_sha256
            != self.lease.assessment_semantic_sha256
        ):
            raise _blocked("financial Audit origin differs from its exact owner qualification")
        if self.write_mode == "append" and (
            self.lease.valid_until.astimezone(UTC) > self.qualification.valid_until.astimezone(UTC)
        ):
            raise _blocked("new financial authority cannot outlive current tax qualification")

    @property
    def scope(self) -> AuditScopeRef:
        """Return the exact tenant/owner used by the actual current grant."""
        self.__post_init__()
        return AuditScopeRef(self.lease.audit_tenant_id, self.lease.audit_owner_id)

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        operation_id: str,
        cash_action: TaxLiabilityCashAction | None,
        using: str,
        as_of: datetime,
    ) -> None:
        """Require live append qualification or an explicitly read-only original retry."""
        self.__post_init__()
        self.lease.verify_for(
            assessment,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            cash_action=cash_action,
            using=using,
            as_of=as_of,
        )
        if self.source_row_updated_at.astimezone(UTC) > _aware(
            as_of, field_name="origin clock"
        ).astimezone(UTC):
            raise _blocked("financial source evidence was not known at the operation clock")
        if self.write_mode == "append":
            self.qualification.verify_for(
                assessment,
                canonical_account_id=self.lease.canonical_account_id,
                environment=self.environment,
                as_of=as_of,
            )


class AuditedTaxLiabilityScopeVerifierPort(CurrentTaxLiabilityScopeVerifierPort, Protocol):
    """Expose origin only during the exact verifier instance's active locked scope."""

    def get_locked_audit_origin(self) -> TaxLiabilityAuditOrigin:
        """Return an active origin; no historical Audit row can enter this context."""


@dataclass(frozen=True, slots=True)
class TaxLiabilityReplayRequest:
    """Exact operation intent for a narrowly verified old physical timestamp waiver."""

    assessment: CorporateActionTaxAssessment
    canonical_account_id: str
    operation_id: str
    cash_action: TaxLiabilityCashAction | None

    def __post_init__(self) -> None:
        """Reject incomplete replay identity before reading any stored financial proof."""
        if type(self.assessment) is not CorporateActionTaxAssessment:
            raise _blocked("an exact assessment is required for financial replay")
        self.assessment.verify_integrity()
        _token(self.canonical_account_id, field_name="replay canonical account")
        _token(self.operation_id, field_name="replay operation id")
        if self.cash_action is not None and type(self.cash_action) is not TaxLiabilityCashAction:
            raise _blocked("financial replay action is untyped")


class TaxLiabilityReplayTimestampVerifierPort(Protocol):
    """Prove an exact recorded operation without constructing new write authority."""

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
        """Return a proved original timestamp only after full journal/Audit/Outbox checks."""


__all__ = [
    "AuditedTaxLiabilityScopeVerifierPort",
    "TaxLiabilityAuditOrigin",
    "TaxLiabilityReplayRequest",
    "TaxLiabilityReplayTimestampVerifierPort",
]
