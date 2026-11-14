"""Fail-closed ports and use case for immutable tax assessment recording.

This module defines no authorization defaults and no ORM access. A production
composition must provide locked current-source/policy/date/owner checks and an
atomic same-alias assessment plus Audit/Outbox writer.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError

_TAX_ASSESSMENT_PERMISSION = "simulated.corporate_action_tax.assess"


def _token(value: object, *, field_name: str, limit: int = 192) -> str:
    """Require a bounded stable token for Application scope values."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        raise BusinessLogicError(f"{field_name} is invalid", code="TAX_ASSESSMENT_SCOPE_BLOCKED")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BusinessLogicError(
            f"{field_name} is invalid UTF-8", code="TAX_ASSESSMENT_SCOPE_BLOCKED"
        ) from error
    return value


def _require_aware(value: datetime, *, field_name: str) -> None:
    """Require an aware and UTC-representable Application instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BusinessLogicError(
            f"{field_name} must be timezone-aware", code="TAX_ASSESSMENT_BLOCKED"
        )
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise BusinessLogicError(
            f"{field_name} is outside the representable UTC range",
            code="TAX_ASSESSMENT_BLOCKED",
        ) from error


class TaxAssessmentAppendDisposition(StrEnum):
    """The atomic repository's append or exact-original-facts retry result."""

    STORED = "stored"
    EXACT_RETRY = "exact_retry"


@dataclass(frozen=True, slots=True)
class TaxAssessmentWriteReceipt:
    """Nonfinancial result of storing or exactly retrying an assessment revision."""

    disposition: TaxAssessmentAppendDisposition
    assessment_revision_id: str
    semantic_sha256: str
    observation_manifest_sha256: str

    def __post_init__(self) -> None:
        """Validate the stored identity and both independently retained payload seals."""

        if type(self.disposition) is not TaxAssessmentAppendDisposition:
            raise BusinessLogicError("assessment append result is invalid")
        _token(self.assessment_revision_id, field_name="assessment_revision_id")
        for digest in (self.semantic_sha256, self.observation_manifest_sha256):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise BusinessLogicError("assessment receipt digest is invalid")


@dataclass(frozen=True, slots=True)
class TaxAssessmentExactReplayEvidence:
    """Complete original retained identity used only to classify a read-only retry."""

    assessment_revision_id: str
    idempotency_key: str
    semantic_sha256: str
    observation_manifest_sha256: str
    recorded_at: datetime
    audit_scope: AuditScopeRef
    audit_event_id: str
    audit_content_sha256: str
    outbox_id: str
    outbox_payload_sha256: str
    official_window_proof: CorporateActionTaxWindowProof | None = None

    def __post_init__(self) -> None:
        """Validate stable references without treating this history as authority."""

        _token(self.assessment_revision_id, field_name="assessment_revision_id")
        _token(self.idempotency_key, field_name="idempotency_key", limit=64)
        _token(self.audit_event_id, field_name="audit_event_id")
        _token(self.outbox_id, field_name="outbox_id", limit=64)
        _require_aware(self.recorded_at, field_name="original assessment recorded_at")
        if type(self.audit_scope) is not AuditScopeRef:
            raise BusinessLogicError("assessment replay Audit scope is untyped")
        self.audit_scope.__post_init__()
        for digest in (
            self.semantic_sha256,
            self.observation_manifest_sha256,
            self.audit_content_sha256,
            self.outbox_payload_sha256,
        ):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise BusinessLogicError("assessment replay contains an invalid digest")
        if self.audit_content_sha256 != self.outbox_payload_sha256:
            raise BusinessLogicError("assessment replay Audit and Outbox hashes differ")
        if self.official_window_proof is not None:
            if type(self.official_window_proof) is not CorporateActionTaxWindowProof:
                raise BusinessLogicError("assessment replay window proof is untyped")
            self.official_window_proof.__post_init__()
            self.official_window_proof.assert_recorded_at(self.recorded_at)

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        audit_scope: AuditScopeRef,
        canonical_account_id: str,
        environment: str,
        as_of: datetime,
    ) -> None:
        """Bind verified original material to this exact owner request and current scope."""

        self.__post_init__()
        _require_aware(as_of, field_name="assessment replay clock")
        if type(assessment) is not CorporateActionTaxAssessment:
            raise BusinessLogicError("a typed assessment is required for exact replay")
        assessment.verify_integrity()
        if (
            self.idempotency_key != assessment.calculation.idempotency_key
            or self.semantic_sha256 != assessment.semantic_sha256
            or self.audit_scope != audit_scope
            or self.recorded_at.astimezone(UTC) > as_of.astimezone(UTC)
        ):
            raise BusinessLogicError(
                "retained assessment differs from the exact replay request",
                code="TAX_ASSESSMENT_REPLAY_MISMATCH",
            )
        proof = self.official_window_proof
        if proof is not None:
            proof.verify_for_assessment(
                assessment,
                canonical_account_id=canonical_account_id,
                environment=environment,
            )


@dataclass(frozen=True, slots=True)
class TaxAssessmentWriteLease:
    """Exact owner, source, policy, date-rule, and explicit tax-capability scope.

    The trusted verifier yields this only while all relevant current rows are
    locked. A cash-only grant or staff audit-read context is not this permission.
    """

    database_alias: str
    actor_user_id: int
    owner_user_id: int
    account_id: int
    asset_code: str
    security_id: str
    corporate_action_id: str
    action_source_namespace: str
    action_source_record_id: str
    action_source_event_id: str
    action_source_revision_id: str
    action_source_revision_sha256: str
    action_source_payload_sha256: str
    settlement_source_revision_id: str
    settlement_source_revision_sha256: str
    record_date: date
    target_settlement_date: date
    settlement_date_rule_id: str
    settlement_date_rule_sha256: str
    settlement_calendar_id: str
    settlement_calendar_sha256: str
    policy_id: str
    policy_version: str
    policy_sha256: str
    statutory_revision_set_sha256: str
    authority_grant_id: str
    authority_grant_version: str
    permission: str
    valid_until: datetime

    def __post_init__(self) -> None:
        """Require a finite, exact, owner-bound tax-specific lease."""

        _token(self.database_alias, field_name="database_alias", limit=64)
        if (
            type(self.actor_user_id) is not int
            or type(self.owner_user_id) is not int
            or self.actor_user_id <= 0
            or self.owner_user_id <= 0
            or self.actor_user_id != self.owner_user_id
            or type(self.account_id) is not int
            or self.account_id <= 0
        ):
            raise BusinessLogicError("tax assessment authority scope is invalid")
        for name, value in (
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("corporate_action_id", self.corporate_action_id),
            ("action_source_namespace", self.action_source_namespace),
            ("action_source_record_id", self.action_source_record_id),
            ("action_source_event_id", self.action_source_event_id),
            ("action_source_revision_id", self.action_source_revision_id),
            ("settlement_source_revision_id", self.settlement_source_revision_id),
            ("settlement_date_rule_id", self.settlement_date_rule_id),
            ("settlement_calendar_id", self.settlement_calendar_id),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("authority_grant_id", self.authority_grant_id),
            ("authority_grant_version", self.authority_grant_version),
        ):
            _token(value, field_name=name)
        for digest in (
            self.action_source_revision_sha256,
            self.action_source_payload_sha256,
            self.settlement_source_revision_sha256,
            self.settlement_date_rule_sha256,
            self.settlement_calendar_sha256,
            self.policy_sha256,
            self.statutory_revision_set_sha256,
        ):
            if (
                type(digest) is not str
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise BusinessLogicError("tax assessment authority contains an invalid digest")
        _token(self.authority_grant_version, field_name="authority_grant_version", limit=128)
        if self.permission != _TAX_ASSESSMENT_PERMISSION:
            raise BusinessLogicError("explicit tax-assessment permission is required")
        if type(self.record_date) is not date or type(self.target_settlement_date) is not date:
            raise BusinessLogicError("authority lease requires exact calendar dates")
        _require_aware(self.valid_until, field_name="authority valid_until")

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        as_of: datetime,
    ) -> None:
        """Fail unless this live lease exactly matches the assessment and owner."""

        _require_aware(as_of, field_name="server assessment clock")
        if type(assessment) is not CorporateActionTaxAssessment:
            raise BusinessLogicError("a typed tax assessment is required")
        assessment.verify_integrity()
        action = assessment.action
        history = assessment.history
        policy = assessment.policy
        source_bundle = assessment.statutory_source_bundle
        if (
            using != self.database_alias
            or actor_user_id != self.actor_user_id
            or actor_user_id != assessment.owner_user_id
            or self.owner_user_id != assessment.owner_user_id
            or self.account_id != assessment.account_id
            or self.asset_code != assessment.asset_code
            or self.security_id != assessment.security_id
            or self.corporate_action_id != action.corporate_action_id
            or self.action_source_namespace != action.source_namespace
            or self.action_source_record_id != action.source_record_id
            or self.action_source_event_id != action.source_event_id
            or self.action_source_revision_id != action.source_revision_id
            or self.action_source_revision_sha256 != action.source_revision_sha256
            or self.action_source_payload_sha256 != action.source_payload_sha256
            or self.settlement_source_revision_id != history.source_revision_id
            or self.settlement_source_revision_sha256 != history.source_revision_sha256
            or self.record_date != history.record_date
            or self.target_settlement_date != assessment.target_settlement_date
            or self.settlement_date_rule_id != history.settlement_date_rule_id
            or self.settlement_date_rule_sha256 != history.settlement_date_rule_sha256
            or self.settlement_calendar_id != history.settlement_calendar_id
            or self.settlement_calendar_sha256 != history.settlement_calendar_sha256
            or self.policy_id != policy.policy_id
            or self.policy_version != policy.version
            or self.policy_sha256 != policy.policy_sha256
            or self.statutory_revision_set_sha256 != source_bundle.source_revision_set_sha256
        ):
            raise BusinessLogicError(
                "locked current tax-assessment scope differs from the complete assessment",
                code="TAX_ASSESSMENT_SCOPE_BLOCKED",
            )
        if as_of >= self.valid_until:
            raise BusinessLogicError(
                "tax-assessment authority lease is expired",
                code="TAX_ASSESSMENT_AUTHORITY_EXPIRED",
            )

    def assert_live(self, *, as_of: datetime) -> None:
        """Cheaply recheck the finite lease deadline after expensive verification."""

        _require_aware(as_of, field_name="server assessment clock")
        if as_of >= self.valid_until:
            raise BusinessLogicError(
                "tax-assessment authority lease is expired",
                code="TAX_ASSESSMENT_AUTHORITY_EXPIRED",
            )


class TaxAssessmentClockPort(Protocol):
    """Supply the server clock used for half-open authority expiry checks."""

    def now(self) -> datetime:
        """Return one timezone-aware server instant."""


class CurrentTaxAssessmentScopeVerifierPort(Protocol):
    """Lock and reverify current source, policy, date, physical owner, and tax grant."""

    @property
    def database_alias(self) -> str:
        """Return the alias on which the verifier holds its source and authority locks."""

    def locked_current_scope(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
    ) -> AbstractContextManager[TaxAssessmentWriteLease]:
        """Hold exact current-scope locks and recheck the tax-specific lease on exit.

        Implementations must require explicit current tax-assessment permission
        and owner consent. They must not infer it from cash permission or a staff
        Audit reader. This context is nested inside the outer atomic unit of work.
        """


@runtime_checkable
class TaxAssessmentExactReplayProbePort(Protocol):
    """Read and fully verify one exact current assessment head inside its owner UOW."""

    def find_exact_replay(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        audit_scope: AuditScopeRef,
        as_of: datetime,
    ) -> TaxAssessmentExactReplayEvidence | None:
        """Return complete original Header/Audit/Outbox evidence, or no exact head."""


@runtime_checkable
class ReplayAwareTaxAssessmentScopeVerifierPort(CurrentTaxAssessmentScopeVerifierPort, Protocol):
    """Opt into retained-original checks without changing legacy scope signatures."""

    def locked_current_scope_with_replay(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        replay_probe: TaxAssessmentExactReplayProbePort,
    ) -> AbstractContextManager[TaxAssessmentWriteLease]:
        """Hold current authority and classify only a fully verified original retry."""
        ...


class TaxAssessmentAtomicWriterPort(Protocol):
    """Append immutable assessment rows and their Audit event/Outbox record."""

    def append_with_audit_outbox(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
    ) -> TaxAssessmentWriteReceipt:
        """Append header, allocations, Audit event, and Outbox using the open UOW.

        Return the persisted receipt. For an exact retry, return the original
        stored revision ID and observation manifest while requiring matching
        semantic facts and complete original header, allocation, Audit, and
        Outbox facts. The writer must keep all rows atomic on the UOW's alias.
        """


class TaxAssessmentAtomicUnitOfWorkPort(Protocol):
    """Open one alias-bound atomic unit for assessment, Audit, and Outbox writes."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the atomic writer."""

    def atomic(self, *, using: str) -> AbstractContextManager[TaxAssessmentAtomicWriterPort]:
        """Open the transaction which surrounds locked verification and all appends."""


class CorporateActionTaxAssessmentUseCase:
    """Record one recalculated tax assessment without creating financial postings."""

    def __init__(
        self,
        *,
        scope_verifier: CurrentTaxAssessmentScopeVerifierPort,
        unit_of_work: TaxAssessmentAtomicUnitOfWorkPort,
        clock: TaxAssessmentClockPort,
        using: str,
    ) -> None:
        """Require explicit verifier, atomic Audit/Outbox writer, clock, and alias."""

        self._scope_verifier = scope_verifier
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._using = _token(using, field_name="database_alias", limit=64)

    def execute(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
    ) -> TaxAssessmentWriteReceipt:
        """Verify current owner scope and atomically retain a complete assessment."""

        if type(assessment) is not CorporateActionTaxAssessment:
            raise BusinessLogicError("a typed tax assessment is required")
        if type(actor_user_id) is not int or actor_user_id <= 0:
            raise BusinessLogicError("an authenticated owner identity is required")
        try:
            assessment.verify_integrity()
        except DeferredDividendTaxValidationError as error:
            raise BusinessLogicError(
                "tax assessment failed Domain integrity verification",
                code="TAX_ASSESSMENT_EVIDENCE_INVALID",
            ) from error
        if actor_user_id != assessment.owner_user_id:
            raise BusinessLogicError(
                "only the exact assessment owner may request this operation",
                code="TAX_ASSESSMENT_OWNER_REQUIRED",
            )
        if (
            self._scope_verifier.database_alias != self._using
            or self._unit_of_work.database_alias != self._using
        ):
            raise BusinessLogicError(
                "tax assessment, scope locks, Audit, and Outbox must share one alias",
                code="TAX_ASSESSMENT_ALIAS_MISMATCH",
            )

        with self._unit_of_work.atomic(using=self._using) as writer:
            if isinstance(
                self._scope_verifier, ReplayAwareTaxAssessmentScopeVerifierPort
            ) and isinstance(writer, TaxAssessmentExactReplayProbePort):
                scope = self._scope_verifier.locked_current_scope_with_replay(
                    assessment,
                    actor_user_id=actor_user_id,
                    using=self._using,
                    replay_probe=writer,
                )
            else:
                scope = self._scope_verifier.locked_current_scope(
                    assessment, actor_user_id=actor_user_id, using=self._using
                )
            with scope as lease:
                if type(lease) is not TaxAssessmentWriteLease:
                    raise BusinessLogicError("locked tax authority lease is untyped")
                lease.verify_for(
                    assessment,
                    actor_user_id=actor_user_id,
                    using=self._using,
                    as_of=self._clock.now(),
                )
                receipt = writer.append_with_audit_outbox(
                    assessment,
                    actor_user_id=actor_user_id,
                )
                if type(receipt) is not TaxAssessmentWriteReceipt:
                    raise BusinessLogicError("atomic writer returned an invalid receipt")
                receipt.__post_init__()
                if receipt.semantic_sha256 != assessment.semantic_sha256:
                    raise BusinessLogicError("atomic writer receipt semantic digest differs")
                if receipt.disposition is TaxAssessmentAppendDisposition.STORED and (
                    receipt.assessment_revision_id != assessment.assessment_revision_id
                    or receipt.observation_manifest_sha256 != assessment.observation_manifest_sha256
                ):
                    raise BusinessLogicError("stored receipt differs from the submitted assessment")
            # The verifier context must recheck mutable source/policy/authority while
            # this outer transaction is still open; this final clock check catches expiry.
            lease.verify_for(
                assessment,
                actor_user_id=actor_user_id,
                using=self._using,
                as_of=self._clock.now(),
            )
            lease.assert_live(as_of=self._clock.now())

        return receipt


__all__ = [
    "CorporateActionTaxAssessmentUseCase",
    "CurrentTaxAssessmentScopeVerifierPort",
    "ReplayAwareTaxAssessmentScopeVerifierPort",
    "TaxAssessmentExactReplayEvidence",
    "TaxAssessmentExactReplayProbePort",
    "TaxAssessmentAppendDisposition",
    "TaxAssessmentAtomicUnitOfWorkPort",
    "TaxAssessmentAtomicWriterPort",
    "TaxAssessmentClockPort",
    "TaxAssessmentWriteLease",
    "TaxAssessmentWriteReceipt",
]
