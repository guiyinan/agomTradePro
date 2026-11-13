"""Owner-grant authorization for audited simulated corporate-action writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
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
from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.system_audit_runtime_readiness_composition import (
    read_system_audit_runtime_readiness as get_system_audit_authority_lease,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    CorporateActionSourceTimestampReplayVerifier,
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from core.exceptions import AuthorizationError


@dataclass(frozen=True, slots=True)
class OwnerGrantedCorporateActionAuthority:
    """Exact current owner grant, operation capability and Audit scope for one UOW."""

    user_id: int
    scope: AuditScopeRef
    grant: SimulatedCorporateActionWriteGrant
    authority_valid_until: datetime
    required_capability: SimulatedCorporateActionWriteCapability = (
        SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE
    )

    def __post_init__(self) -> None:
        """Require the scope and finite cutoff to derive from the exact grant."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("owner-granted account user id is invalid")
        if type(self.scope) is not AuditScopeRef:
            raise TypeError("owner-granted Audit scope must be exact")
        self.scope.__post_init__()
        if type(self.grant) is not SimulatedCorporateActionWriteGrant:
            raise TypeError("owner-granted authority requires an exact grant")
        self.grant.__post_init__()
        if (
            self.user_id != self.grant.binding.owner_user_id
            or self.scope
            != AuditScopeRef(
                tenant_id=self.grant.binding.tenant_id,
                owner_id=self.grant.binding.owner_id,
            )
            or type(self.required_capability) is not SimulatedCorporateActionWriteCapability
            or self.grant.schema
            not in {
                SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
                SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
                SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
            }
            or (
                self.grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
                and (
                    self.grant.permission != SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
                    or self.required_capability
                    is not SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE
                )
            )
            or (
                self.grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
                and (
                    self.grant.permission != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
                    or self.required_capability
                    is not SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE
                )
            )
            or (
                self.grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
                and (
                    self.grant.permission != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
                    or self.required_capability
                    not in {
                        SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE,
                        SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
                        SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
                    }
                )
            )
            or not self.grant.supports_capability(self.required_capability)
            or self.grant.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        ):
            raise ValueError("owner-granted Audit scope differs from the exact Account grant")
        if (
            type(self.authority_valid_until) is not datetime
            or self.authority_valid_until.tzinfo is None
            or self.authority_valid_until.utcoffset() is None
            or not self.grant.recorded_at < self.authority_valid_until <= self.grant.valid_until
        ):
            raise ValueError("owner-granted authority validity is not finite and exact")


@dataclass(frozen=True, slots=True)
class _ActiveAuthority:
    """Private context-bound owner authority for one active write transaction."""

    authority: OwnerGrantedCorporateActionAuthority
    request: CorporateActionStageRequest
    replay_timestamp_verifier: CorporateActionSourceTimestampReplayVerifier | None


_ACTIVE_AUTHORITY: ContextVar[tuple[object, _ActiveAuthority] | None] = ContextVar(
    "simulated_corporate_action_owner_grant_authority", default=None
)


class DjangoCorporateActionOwnerGrantGate:
    """Hold exact owner, current Account grant and Audit readiness in one UOW."""

    __slots__ = (
        "_environment",
        "_expected_grant_schema",
        "_scope_locker",
        "_selector",
        "_using",
    )

    def __init__(
        self,
        *,
        selector: SimulatedCorporateActionWriteGrantSelector,
        scope_locker: DjangoSimulatedCorporateActionWriteScopeLocker,
        using: str,
        environment: str,
        expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    ) -> None:
        """Bind one server-selected grant to its concrete same-alias scope locker."""

        if type(selector) is not SimulatedCorporateActionWriteGrantSelector:
            raise CorporateActionPostingBlockedError(
                "owner-grant selector type is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        if type(expected_grant_schema) is not str or expected_grant_schema not in {
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
        }:
            raise CorporateActionPostingBlockedError(
                "owner-grant schema is unsupported",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        try:
            selector.__post_init__()
        except (TypeError, ValueError) as error:
            raise CorporateActionPostingBlockedError(
                "owner-grant selector is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            ) from error
        if (
            type(scope_locker) is not DjangoSimulatedCorporateActionWriteScopeLocker
            or type(using) is not str
            or using != DEFAULT_DB_ALIAS
            or scope_locker.database_alias != using
            or type(environment) is not str
            or not environment
            or environment.strip() != environment
            or any(character.isspace() for character in environment)
            or scope_locker.runtime_environment != environment
        ):
            raise CorporateActionPostingBlockedError(
                "owner-grant scope locker or alias is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        self._selector = selector
        self._scope_locker = scope_locker
        self._using = using
        self._environment = environment
        self._expected_grant_schema = expected_grant_schema

    @property
    def database_alias(self) -> str:
        """Return the alias that owns every locked source and grant participant."""

        return self._using

    @property
    def runtime_environment(self) -> str:
        """Return the exact Config Center environment held by the source locker."""

        return self._environment

    def _block(self, message: str, *, code: str) -> CorporateActionPostingBlockedError:
        """Construct one stable posting-domain failure without leaking authority data."""

        return CorporateActionPostingBlockedError(message, code=code)

    def _grant_matches_locked_scope(
        self,
        *,
        grant: SimulatedCorporateActionWriteGrant,
        scope: LockedSimulatedCorporateActionWriteScope,
        required_capability: SimulatedCorporateActionWriteCapability,
    ) -> bool:
        """Require the exact server schema and selected capability in policy scope."""

        if (
            grant.schema != self._expected_grant_schema
            or scope.grant_schema != self._expected_grant_schema
            or not grant.supports_capability(required_capability)
        ):
            return False
        if self._expected_grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
            return all(
                value is None
                for value in (
                    grant.capabilities,
                    grant.terms_version,
                    grant.terms_sha256,
                    scope.capabilities,
                    scope.terms_version,
                    scope.terms_sha256,
                )
            )
        if grant.capabilities is None or scope.capabilities is None:
            return False
        return (
            set(grant.capabilities).issubset(scope.capabilities)
            and grant.terms_version == scope.terms_version
            and grant.terms_sha256 == scope.terms_sha256
        )

    def _require_request(
        self, request: CorporateActionStageRequest
    ) -> SimulatedCorporateActionWriteCapability:
        """Bind one exact ordinary stage to its schema-specific owner capability."""

        if type(request) is not CorporateActionStageRequest:
            raise self._block(
                "owner-grant gate requires one exact corporate-action request",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        try:
            request.__post_init__()
        except (TypeError, ValueError) as error:
            raise self._block(
                "owner-grant request is invalid", code="CORPORATE_ACTION_INPUT_INVALID"
            ) from error
        ordinary_entry = request.entry_kind in {
            CorporateActionEntryKind.POSTING,
            CorporateActionEntryKind.SUCCESSOR,
        }
        cash_stage = (
            request.action_kind is CorporateActionKind.CASH_DIVIDEND
            and request.stage
            in {CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT}
            and ordinary_entry
        )
        if self._expected_grant_schema in {
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
            SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        }:
            required_capability = (
                SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE if cash_stage else None
            )
        elif cash_stage:
            required_capability = SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE
        elif (
            request.action_kind is CorporateActionKind.SHARE_DISTRIBUTION
            and request.stage
            in {
                CorporateActionStage.SHARE_ENTITLEMENT,
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            and ordinary_entry
        ):
            required_capability = SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE
        elif (
            request.action_kind is CorporateActionKind.RIGHTS_ISSUE
            and request.stage is CorporateActionStage.RIGHTS_NOT_EXERCISED
            and request.entry_kind is CorporateActionEntryKind.NO_EFFECT
        ):
            required_capability = SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED
        else:
            required_capability = None
        if required_capability is None:
            raise self._block(
                "owner-grant schema does not authorize this exact action stage",
                code="CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        if request.owner_user_id != self._selector.binding.owner_user_id:
            raise self._block(
                "owner-grant account differs from the locked owner",
                code="CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
            )
        return required_capability

    def _read_audit_lease(self, *, as_of: datetime) -> SystemAuditAuthorityLease:
        """Require global transactional-Outbox readiness without borrowing staff scope."""

        try:
            lease = get_system_audit_authority_lease(
                environment=self._environment, using=self._using
            )
        except SystemAuditCompositionUnavailable as error:
            raise self._block(
                "required corporate-action Audit/Outbox runtime is unavailable",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            ) from error
        if type(lease) is not SystemAuditAuthorityLease:
            raise self._block(
                "corporate-action Audit/Outbox readiness has an invalid type",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            )
        try:
            lease.__post_init__()
        except (TypeError, ValueError) as error:
            raise self._block(
                "corporate-action Audit/Outbox readiness is invalid",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            ) from error
        if (
            lease.mode != "required"
            or lease.outbox_enabled is not True
            or lease.valid_until is None
            or lease.valid_until <= as_of
            or lease.reason_code is not None
        ):
            raise self._block(
                "required corporate-action Audit/Outbox lease is unavailable",
                code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
            )
        return lease

    def assert_live(self, *, as_of: datetime) -> OwnerGrantedCorporateActionAuthority:
        """Recheck the active owner grant and global Audit readiness inside its UOW."""

        active = _ACTIVE_AUTHORITY.get()
        if active is None or active[0] is not self:
            raise self._block(
                "owner-grant authority is outside its locked write transaction",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        authority = active[1].authority
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise self._block(
                "owner-grant authority clock is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        server_now = timezone.now()
        if server_now.tzinfo is None or server_now.utcoffset() is None:
            raise self._block(
                "owner-grant server clock is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        checked_at = max(as_of, server_now)
        if checked_at >= authority.authority_valid_until or not authority.grant.is_active_at(
            checked_at
        ):
            raise self._block(
                "owner-granted corporate-action authority expired or changed",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        # Keep the initial cutoff fixed in authority_valid_until. A renewed current
        # lease may carry a different cutoff; only current operational readiness
        # matters here because the Audit lease does not grant owner write scope.
        self._read_audit_lease(as_of=checked_at)
        return authority

    def _assert_commit_deadline(self, *, authority: OwnerGrantedCorporateActionAuthority) -> None:
        """Recheck current grant, fixed cutoff, and Audit readiness after lock contexts exit."""

        try:
            with locked_current_simulated_corporate_action_write_grant(
                selector=authority.grant.selector,
                using=self._using,
                required_capability=authority.required_capability,
            ) as current_grant:
                if current_grant != authority.grant:
                    raise self._block(
                        "owner grant changed before transaction commit",
                        code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                    )
        except SimulatedCorporateActionWriteGrantUnavailable as error:
            raise self._block(
                "current owner grant failed its final commit check",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            ) from error

        lease = self._read_audit_lease(as_of=timezone.now())
        commit_time = timezone.now()
        if commit_time.tzinfo is None or commit_time.utcoffset() is None:
            raise self._block(
                "owner-grant final commit clock is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        if (
            commit_time >= authority.authority_valid_until
            or not authority.grant.is_active_at(commit_time)
            or lease.valid_until is None
            or lease.valid_until <= commit_time
        ):
            raise self._block(
                "owner grant or required Audit lease expired before transaction commit",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )

    def assert_source_timestamp_current_or_proven(
        self, *, request: CorporateActionStageRequest
    ) -> None:
        """Require current physical/source timestamps or an exact audited replay proof."""

        active = _ACTIVE_AUTHORITY.get()
        if active is None or active[0] is not self or active[1].request != request:
            raise self._block(
                "source timestamp check is outside its exact owner-grant transaction",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        try:
            self._scope_locker.assert_source_timestamp_current_or_proven(
                request=request,
                grant=active[1].authority.grant,
                verifier=active[1].replay_timestamp_verifier,
            )
        except SimulatedCorporateActionWriteGrantUnavailable as error:
            raise self._block(
                "physical account source requires exact audited replay proof",
                code="CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
            ) from error

    @contextmanager
    def atomic_authority(
        self,
        request: CorporateActionStageRequest,
        *,
        replay_timestamp_verifier: CorporateActionSourceTimestampReplayVerifier | None = None,
    ) -> Iterator[OwnerGrantedCorporateActionAuthority]:
        """Open the outer same-alias UOW and hold owner/grant/source locks through exit."""

        if _ACTIVE_AUTHORITY.get() is not None:
            raise self._block(
                "owner-grant write UOW cannot be nested",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        if replay_timestamp_verifier is not None and not isinstance(
            replay_timestamp_verifier, CorporateActionSourceTimestampReplayVerifier
        ):
            raise self._block(
                "source timestamp replay verifier is invalid",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            )
        required_capability = self._require_request(request)
        try:
            connection = connections[self._using]
            if (
                connection.vendor != "postgresql"
                or connection.in_atomic_block
                or not connection.get_autocommit()
            ):
                raise self._block(
                    "owner-grant write requires a fresh outer PostgreSQL transaction",
                    code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                )
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise self._block(
                "owner-grant database alias is unavailable",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            ) from error

        try:
            with transaction.atomic(using=self._using):
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    if cursor.fetchone() != ("read committed",):
                        raise self._block(
                            "owner-grant write requires READ COMMITTED",
                            code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                        )
                with locked_simulated_action_trading_eligibility(
                    user_id=self._selector.binding.owner_user_id,
                    using=self._using,
                ):
                    with self._scope_locker.lock_owned_scope(
                        physical_account_id=request.account_id,
                        owner_user_id=self._selector.binding.owner_user_id,
                        expected_binding=self._selector.binding,
                        request=request,
                        expected_grant_schema=self._expected_grant_schema,
                    ) as scope:
                        if type(scope) is not LockedSimulatedCorporateActionWriteScope:
                            raise self._block(
                                "locked owner source scope is invalid",
                                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                            )
                        try:
                            scope.__post_init__()
                        except (TypeError, ValueError) as error:
                            raise self._block(
                                "locked owner source scope is invalid",
                                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                            ) from error
                        if (
                            scope.physical_account_id != request.account_id
                            or scope.binding != self._selector.binding
                        ):
                            raise self._block(
                                "locked physical, source or policy scope differs from the grant",
                                code="CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID",
                            )
                        with locked_current_simulated_corporate_action_write_grant(
                            selector=self._selector,
                            using=self._using,
                            required_capability=required_capability,
                        ) as grant:
                            if type(grant) is not SimulatedCorporateActionWriteGrant:
                                raise self._block(
                                    "current Account grant type is invalid",
                                    code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                                )
                            now = timezone.now()
                            if (
                                grant.selector != self._selector
                                or grant.binding != scope.binding
                                or not self._grant_matches_locked_scope(
                                    grant=grant,
                                    scope=scope,
                                    required_capability=required_capability,
                                )
                                or grant.valid_until > scope.valid_until
                                or not grant.is_active_at(now)
                            ):
                                raise self._block(
                                    "current Account grant differs from the locked source scope",
                                    code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                                )
                            lease = self._read_audit_lease(as_of=now)
                            audit_valid_until = lease.valid_until
                            if audit_valid_until is None:
                                raise self._block(
                                    "Audit/Outbox readiness has no finite validity",
                                    code="CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE",
                                )
                            valid_until = min(
                                grant.valid_until, scope.valid_until, audit_valid_until
                            )
                            if not now < valid_until:
                                raise self._block(
                                    "owner-granted authority has no remaining validity",
                                    code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
                                )
                            authority = OwnerGrantedCorporateActionAuthority(
                                user_id=grant.binding.owner_user_id,
                                scope=AuditScopeRef(
                                    tenant_id=grant.binding.tenant_id,
                                    owner_id=grant.binding.owner_id,
                                ),
                                grant=grant,
                                authority_valid_until=valid_until,
                                required_capability=required_capability,
                            )
                            state = _ActiveAuthority(
                                authority=authority,
                                request=request,
                                replay_timestamp_verifier=replay_timestamp_verifier,
                            )
                            token: Token[tuple[object, _ActiveAuthority] | None] = (
                                _ACTIVE_AUTHORITY.set((self, state))
                            )
                            try:
                                self.assert_live(as_of=timezone.now())
                                yield authority
                                self.assert_live(as_of=timezone.now())
                            finally:
                                _ACTIVE_AUTHORITY.reset(token)
                self._assert_commit_deadline(authority=authority)
        except (
            SimulatedCorporateActionWriteGrantUnavailable,
            SimulatedAccountRowSourceV2Conflict,
            SimulatedAccountRowSourceV2Corruption,
            SimulatedAccountRowSourceV2Unavailable,
            AuthorizationError,
        ) as error:
            raise self._block(
                "current owner, source, policy or grant cannot authorize this posting",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            ) from error
        except (DatabaseError, ConnectionDoesNotExist) as error:
            raise self._block(
                "owner-grant write transaction is unavailable",
                code="CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE",
            ) from error


__all__ = [
    "DjangoCorporateActionOwnerGrantGate",
    "OwnerGrantedCorporateActionAuthority",
]
