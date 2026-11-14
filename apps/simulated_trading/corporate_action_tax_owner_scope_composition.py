"""Bind tax-assessment verification to current Account and Audit scopes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import DatabaseError, connections
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
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
from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
from apps.audit.system_audit_runtime_readiness_composition import (
    read_system_audit_runtime_readiness,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentExactReplayEvidence,
    TaxAssessmentExactReplayProbePort,
    TaxAssessmentWriteLease,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
    CurrentTaxAssessmentQualificationPort,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    AuditedTaxAssessmentScopeVerifierPort,
    TaxAssessmentAuditOrigin,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError


def _blocked(message: str, *, code: str = "TAX_ASSESSMENT_SCOPE_BLOCKED") -> BusinessLogicError:
    """Create a stable owner-scope blocker without echoing sensitive values."""

    return BusinessLogicError(message, code=code)


def _utc(value: object, *, field_name: str) -> datetime:
    """Require one exact timezone-aware server or lease instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _blocked(f"{field_name} must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise _blocked(f"{field_name} cannot be represented in UTC") from error


def _server_now() -> datetime:
    """Read one aware server instant in canonical UTC form."""

    return _utc(timezone.now(), field_name="server clock")


def _permission_for_schema(expected_grant_schema: str) -> str:
    """Return only the exact V2 or V3 capability-bundle marker."""

    if expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        return SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
    if expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA:
        return SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
    raise _blocked("tax assessment requires an explicit V2 or V3 grant schema")


def _require_outer_read_committed(*, using: str) -> None:
    """Require the caller's outer PostgreSQL READ COMMITTED transaction."""

    if type(using) is not str or not using or using != using.strip():
        raise _blocked("tax scope requires an explicit database alias")
    try:
        connection = connections[using]
        if (
            connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or connection.get_autocommit()
        ):
            raise _blocked("tax scope requires the outer PostgreSQL transaction")
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise _blocked("tax scope requires READ COMMITTED isolation")
    except (DatabaseError, ConnectionDoesNotExist) as error:
        raise _blocked("tax scope transaction is unavailable") from error


def _require_audit_lease(
    *, environment: str, using: str, as_of: datetime
) -> SystemAuditAuthorityLease:
    """Require current global transactional Audit/Outbox readiness."""

    readiness = read_system_audit_runtime_readiness(environment=environment, using=using)
    if type(readiness) is not SystemAuditAuthorityLease:
        raise _blocked("global Audit readiness is untyped")
    readiness.__post_init__()
    deadline = readiness.valid_until
    if (
        readiness.mode != "required"
        or readiness.outbox_enabled is not True
        or readiness.reason_code is not None
        or deadline is None
        or _utc(deadline, field_name="Audit valid_until") <= as_of
    ):
        raise _blocked("required Audit/Outbox readiness is unavailable")
    return readiness


def _require_exact_scope_and_grant(
    *,
    assessment: CorporateActionTaxAssessment,
    actor_user_id: int,
    selector: SimulatedCorporateActionWriteGrantSelector,
    locked_scope: LockedSimulatedCorporateActionWriteScope,
    grant: SimulatedCorporateActionWriteGrant,
    expected_grant_schema: str,
    as_of: datetime,
) -> None:
    """Match the selected version's policy, permission, owner, and grant facts."""

    expected_permission = _permission_for_schema(expected_grant_schema)
    if type(locked_scope) is not LockedSimulatedCorporateActionWriteScope:
        raise _blocked("locked physical and policy scope is untyped")
    locked_scope.__post_init__()
    if type(grant) is not SimulatedCorporateActionWriteGrant:
        raise _blocked("current tax grant is untyped")
    grant.__post_init__()
    if _utc(grant.valid_until, field_name="grant valid_until") > _utc(
        locked_scope.valid_until, field_name="locked scope valid_until"
    ):
        raise _blocked("current Account grant outlives its exact source and policy scope")
    binding = selector.binding
    if (
        locked_scope.physical_account_id != assessment.account_id
        or locked_scope.binding != binding
        or binding.account_namespace != "simulated"
        or binding.owner_user_id != assessment.owner_user_id
        or actor_user_id != assessment.owner_user_id
        or locked_scope.grant_schema != expected_grant_schema
        or locked_scope.capabilities is None
        or SimulatedCorporateActionWriteCapability.TAX_ASSESS not in locked_scope.capabilities
        or grant.selector != selector
        or grant.binding != binding
        or grant.schema != expected_grant_schema
        or grant.permission != expected_permission
        or grant.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        or grant.capabilities is None
        or not all(capability in locked_scope.capabilities for capability in grant.capabilities)
        or grant.terms_version != locked_scope.terms_version
        or grant.terms_sha256 != locked_scope.terms_sha256
        or not grant.supports_capability(SimulatedCorporateActionWriteCapability.TAX_ASSESS)
        or not grant.is_active_at(as_of)
    ):
        raise _blocked("current Account grant does not match the exact tax-assessment scope")


def _make_write_lease(
    *,
    assessment: CorporateActionTaxAssessment,
    actor_user_id: int,
    using: str,
    grant: SimulatedCorporateActionWriteGrant,
    valid_until: datetime,
    as_of: datetime,
) -> TaxAssessmentWriteLease:
    """Bind every immutable assessment fact and real grant identity to the lease."""

    action = assessment.action
    history = assessment.history
    policy = assessment.policy
    lease = TaxAssessmentWriteLease(
        database_alias=using,
        actor_user_id=actor_user_id,
        owner_user_id=assessment.owner_user_id,
        account_id=assessment.account_id,
        asset_code=assessment.asset_code,
        security_id=assessment.security_id,
        corporate_action_id=action.corporate_action_id,
        action_source_namespace=action.source_namespace,
        action_source_record_id=action.source_record_id,
        action_source_event_id=action.source_event_id,
        action_source_revision_id=action.source_revision_id,
        action_source_revision_sha256=action.source_revision_sha256,
        action_source_payload_sha256=action.source_payload_sha256,
        settlement_source_revision_id=history.source_revision_id,
        settlement_source_revision_sha256=history.source_revision_sha256,
        record_date=history.record_date,
        target_settlement_date=assessment.target_settlement_date,
        settlement_date_rule_id=history.settlement_date_rule_id,
        settlement_date_rule_sha256=history.settlement_date_rule_sha256,
        settlement_calendar_id=history.settlement_calendar_id,
        settlement_calendar_sha256=history.settlement_calendar_sha256,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_sha256=policy.policy_sha256,
        statutory_revision_set_sha256=assessment.statutory_source_bundle.source_revision_set_sha256,
        authority_grant_id=grant.grant_id,
        authority_grant_version=grant.grant_version,
        permission=SimulatedCorporateActionWriteCapability.TAX_ASSESS.value,
        valid_until=valid_until,
    )
    lease.__post_init__()
    lease.verify_for(assessment, actor_user_id=actor_user_id, using=using, as_of=as_of)
    return lease


@dataclass(frozen=True, slots=True)
class _ActiveAuditOrigin:
    """Private context marker for one verifier instance and exact Audit origin."""

    verifier: object
    origin: TaxAssessmentAuditOrigin


_ACTIVE_AUDIT_ORIGIN: ContextVar[_ActiveAuditOrigin | None] = ContextVar(
    "simulated_tax_assessment_owner_audit_origin", default=None
)


class DjangoTaxAssessmentOwnerScopeVerifier(AuditedTaxAssessmentScopeVerifierPort):
    """Lock current Account owner/grant facts around an injected tax qualifier.

    This adapter adds no qualification itself. It requires the supplied current
    provider to recheck official source, instrument, policy, date and complete
    history facts on the same alias. A CASH grant or Audit reader cannot enter.
    """

    def __init__(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        scope_locker: DjangoSimulatedCorporateActionWriteScopeLocker,
        qualification_provider: CurrentTaxAssessmentQualificationPort,
        using: str,
        environment: str,
        expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    ) -> None:
        """Require server-selected grant schema, concrete Account locker and provider."""

        _permission_for_schema(expected_grant_schema)
        if type(selector) is not SimulatedCorporateActionWriteGrantSelector:
            raise _blocked("a server-selected current grant selector is required")
        selector.__post_init__()
        if type(scope_locker) is not DjangoSimulatedCorporateActionWriteScopeLocker:
            raise _blocked("the concrete Account physical/policy scope locker is required")
        if (
            type(using) is not str
            or not using
            or using != using.strip()
            or scope_locker.database_alias != using
        ):
            raise _blocked("Account scope and assessment must share one database alias")
        if (
            type(environment) is not str
            or not environment
            or environment != environment.strip()
            or scope_locker.runtime_environment != environment
        ):
            raise _blocked("Account scope and Audit must share one runtime environment")
        if not isinstance(qualification_provider, CurrentTaxAssessmentQualificationPort):
            raise _blocked("an explicit current tax-qualification provider is required")
        self._selector = selector
        self._scope_locker = scope_locker
        self._qualification_provider = qualification_provider
        self._using = using
        self._environment = environment
        self._expected_grant_schema = expected_grant_schema

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the assessment and Audit UOW."""

        return self._using

    def get_locked_audit_origin(self) -> TaxAssessmentAuditOrigin:
        """Return this exact origin only during this instance's active locked scope."""

        active = _ACTIVE_AUDIT_ORIGIN.get()
        if active is None or active.verifier is not self:
            raise _blocked("tax Audit origin is outside its active owner scope")
        _require_outer_read_committed(using=self._using)
        active.origin.__post_init__()
        return active.origin

    def locked_current_scope_with_replay(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        replay_probe: TaxAssessmentExactReplayProbePort,
    ) -> AbstractContextManager[TaxAssessmentWriteLease]:
        """Enable complete original replay through the explicit optional scope port."""
        return self.locked_current_scope(
            assessment, actor_user_id=actor_user_id, using=using, replay_probe=replay_probe
        )

    @contextmanager
    def locked_current_scope(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        replay_probe: TaxAssessmentExactReplayProbePort | None = None,
    ) -> Iterator[TaxAssessmentWriteLease]:
        """Hold RBAC, physical/source/policy, current grant and Audit checks in the caller UOW."""

        _require_outer_read_committed(using=using)
        if using != self._using or not isinstance(assessment, CorporateActionTaxAssessment):
            raise _blocked("assessment verifier alias or input type is invalid")
        if type(assessment) is not CorporateActionTaxAssessment:
            raise _blocked("assessment must use the exact typed Domain contract")
        if type(actor_user_id) is not int or actor_user_id <= 0:
            raise _blocked("an authenticated owner identity is required")
        if replay_probe is not None and not isinstance(
            replay_probe, TaxAssessmentExactReplayProbePort
        ):
            raise _blocked("an explicit retained-assessment replay reader is required")
        try:
            assessment.verify_integrity()
        except DeferredDividendTaxValidationError as error:
            raise _blocked("assessment Domain integrity verification failed") from error
        if actor_user_id != assessment.owner_user_id:
            raise _blocked("only the exact assessment owner may request qualification")
        if self._selector.binding.owner_user_id != actor_user_id:
            raise _blocked("server-selected grant belongs to another owner")
        if _ACTIVE_AUDIT_ORIGIN.get() is not None:
            raise _blocked("tax owner-scope contexts cannot be nested")

        with locked_simulated_action_trading_eligibility(user_id=actor_user_id, using=using):
            with self._scope_locker.lock_owned_scope(
                physical_account_id=assessment.account_id,
                owner_user_id=actor_user_id,
                expected_binding=self._selector.binding,
                request=None,
                expected_grant_schema=self._expected_grant_schema,
            ) as locked_scope:
                _require_exact_scope_shape(
                    locked_scope=locked_scope,
                    assessment=assessment,
                    selector=self._selector,
                    actor_user_id=actor_user_id,
                    expected_grant_schema=self._expected_grant_schema,
                )
                with locked_current_simulated_corporate_action_write_grant(
                    selector=self._selector,
                    using=using,
                    required_capability=SimulatedCorporateActionWriteCapability.TAX_ASSESS,
                ) as grant:
                    entry_now = _server_now()
                    _require_exact_scope_and_grant(
                        assessment=assessment,
                        actor_user_id=actor_user_id,
                        selector=self._selector,
                        locked_scope=locked_scope,
                        grant=grant,
                        expected_grant_schema=self._expected_grant_schema,
                        as_of=entry_now,
                    )
                    audit_scope = AuditScopeRef(
                        self._selector.binding.tenant_id, self._selector.binding.owner_id
                    )
                    qualification: CurrentTaxAssessmentQualification | None = None
                    qualification_at: datetime | None = None
                    replay_evidence: TaxAssessmentExactReplayEvidence | None = None
                    probe_at = _server_now()
                    if probe_at < entry_now:
                        raise _blocked("server clock moved backwards before assessment replay")
                    if replay_probe is not None:
                        candidate = replay_probe.find_exact_replay(
                            assessment,
                            actor_user_id=actor_user_id,
                            audit_scope=audit_scope,
                            as_of=probe_at,
                        )
                        if candidate is not None:
                            if type(candidate) is not TaxAssessmentExactReplayEvidence:
                                raise _blocked("retained assessment replay evidence is untyped")
                            if candidate.official_window_proof is not None:
                                candidate.verify_for(
                                    assessment,
                                    audit_scope=audit_scope,
                                    canonical_account_id=self._selector.binding.account_id,
                                    environment=self._environment,
                                    as_of=probe_at,
                                )
                                replay_evidence = candidate
                    if replay_evidence is None:
                        qualification_at = _server_now()
                        if qualification_at < probe_at:
                            raise _blocked("server clock moved backwards before qualification")
                        qualification = self._qualification_provider.read_current(
                            assessment,
                            canonical_account_id=self._selector.binding.account_id,
                            environment=self._environment,
                            using=using,
                            as_of=qualification_at,
                        )
                        if type(qualification) is not CurrentTaxAssessmentQualification:
                            raise _blocked("current qualification result is untyped")
                        qualification.verify_for(
                            assessment,
                            canonical_account_id=self._selector.binding.account_id,
                            environment=self._environment,
                            as_of=qualification_at,
                        )
                    audit_now = _server_now()
                    last_entry_read = probe_at if qualification_at is None else qualification_at
                    if audit_now < last_entry_read:
                        raise _blocked("server clock moved backwards during tax scope checks")
                    audit_lease = _require_audit_lease(
                        environment=self._environment, using=using, as_of=audit_now
                    )
                    deadlines = [
                        _utc(locked_scope.valid_until, field_name="locked scope valid_until"),
                        _utc(grant.valid_until, field_name="grant valid_until"),
                        _utc(audit_lease.valid_until, field_name="Audit valid_until"),
                    ]
                    if qualification is not None:
                        deadlines.append(
                            _utc(qualification.valid_until, field_name="qualification valid_until")
                        )
                    fixed_deadline = min(deadlines)
                    if fixed_deadline <= audit_now:
                        raise _blocked(
                            "tax authority or Audit lease is expired",
                            code="TAX_ASSESSMENT_AUTHORITY_EXPIRED",
                        )
                    lease = _make_write_lease(
                        assessment=assessment,
                        actor_user_id=actor_user_id,
                        using=using,
                        grant=grant,
                        valid_until=fixed_deadline,
                        as_of=audit_now,
                    )
                    if qualification is not None:
                        selected_window_proof = qualification.official_window_proof
                    elif replay_evidence is not None:
                        selected_window_proof = replay_evidence.official_window_proof
                    else:
                        raise _blocked(
                            "assessment has neither current nor retained window evidence"
                        )
                    origin = TaxAssessmentAuditOrigin(
                        lease=lease,
                        scope=audit_scope,
                        grant_content_sha256=grant.content_hash,
                        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
                        official_window_proof=selected_window_proof,
                        write_mode=("append" if replay_evidence is None else "exact_retry_only"),
                        replay_evidence=replay_evidence,
                    )
                    origin.__post_init__()
                    token: Token[_ActiveAuditOrigin | None] = _ACTIVE_AUDIT_ORIGIN.set(
                        _ActiveAuditOrigin(verifier=self, origin=origin)
                    )
                    try:
                        yield lease
                    finally:
                        _ACTIVE_AUDIT_ORIGIN.reset(token)

        final_qualification_at = _server_now()
        if final_qualification_at < audit_now:
            raise _blocked("server clock moved backwards before final tax qualification")
        if replay_evidence is None:
            if qualification is None:
                raise _blocked("new assessment has no current qualification")
            current_qualification = self._qualification_provider.read_current(
                assessment,
                canonical_account_id=self._selector.binding.account_id,
                environment=self._environment,
                using=using,
                as_of=final_qualification_at,
            )
            if type(current_qualification) is not CurrentTaxAssessmentQualification:
                raise _blocked("final current qualification result is untyped")
            current_qualification.verify_for(
                assessment,
                canonical_account_id=self._selector.binding.account_id,
                environment=self._environment,
                as_of=final_qualification_at,
            )
            if current_qualification != qualification:
                raise _blocked("current tax qualification changed before transaction exit")
        else:
            if replay_probe is None:
                raise _blocked("exact assessment retry has no retained replay reader")
            current_replay = replay_probe.find_exact_replay(
                assessment,
                actor_user_id=actor_user_id,
                audit_scope=AuditScopeRef(
                    self._selector.binding.tenant_id, self._selector.binding.owner_id
                ),
                as_of=final_qualification_at,
            )
            if type(current_replay) is not TaxAssessmentExactReplayEvidence:
                raise _blocked("original assessment replay disappeared before transaction exit")
            current_replay.verify_for(
                assessment,
                audit_scope=AuditScopeRef(
                    self._selector.binding.tenant_id, self._selector.binding.owner_id
                ),
                canonical_account_id=self._selector.binding.account_id,
                environment=self._environment,
                as_of=final_qualification_at,
            )
            if current_replay != replay_evidence:
                raise _blocked("original assessment replay changed before transaction exit")

        with locked_current_simulated_corporate_action_write_grant(
            selector=self._selector,
            using=using,
            required_capability=SimulatedCorporateActionWriteCapability.TAX_ASSESS,
        ) as final_grant:
            if final_grant != grant:
                raise _blocked("current tax grant changed before transaction exit")
        final_audit_at = _server_now()
        if final_audit_at < final_qualification_at:
            raise _blocked("server clock moved backwards during final tax checks")
        final_audit_lease = _require_audit_lease(
            environment=self._environment, using=using, as_of=final_audit_at
        )
        final_now = _server_now()
        if final_now < final_audit_at:
            raise _blocked("server clock moved backwards before transaction exit")
        if _utc(final_audit_lease.valid_until, field_name="Audit valid_until") <= final_now:
            raise _blocked(
                "global Audit/Outbox readiness expired before transaction exit",
                code="TAX_ASSESSMENT_AUTHORITY_EXPIRED",
            )
        lease.verify_for(assessment, actor_user_id=actor_user_id, using=using, as_of=final_now)
        lease.assert_live(as_of=final_now)


def _require_exact_scope_shape(
    *,
    locked_scope: LockedSimulatedCorporateActionWriteScope,
    assessment: CorporateActionTaxAssessment,
    selector: SimulatedCorporateActionWriteGrantSelector,
    actor_user_id: int,
    expected_grant_schema: str,
) -> None:
    """Reject wrong owner, schema, or tax capability before reading the current grant."""

    _permission_for_schema(expected_grant_schema)
    if type(locked_scope) is not LockedSimulatedCorporateActionWriteScope:
        raise _blocked("locked Account scope is untyped")
    locked_scope.__post_init__()
    if (
        locked_scope.physical_account_id != assessment.account_id
        or locked_scope.binding != selector.binding
        or selector.binding.owner_user_id != assessment.owner_user_id
        or actor_user_id != assessment.owner_user_id
        or locked_scope.grant_schema != expected_grant_schema
        or locked_scope.capabilities is None
        or SimulatedCorporateActionWriteCapability.TAX_ASSESS not in locked_scope.capabilities
    ):
        raise _blocked("current configured Account scope does not include exact tax assessment")


__all__ = ["DjangoTaxAssessmentOwnerScopeVerifier"]
