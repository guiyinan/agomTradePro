"""ID-only workflow for future Broker order risk authorization."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.risk_center.domain.broker_order_risk_authorization import (
    BROKER_ORDER_RISK_SUBJECT_VERSION,
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
    BrokerOrderRiskScope,
)


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class BrokerOrderRiskAuthorizationUnavailable(ValueError):
    """An exact active source, subject, or authorization is unavailable."""


class BrokerOrderRiskAuthorizationConflict(ValueError):
    """An immutable identity or logical head already has another winner."""


class BrokerOrderRiskAuthorizationCorruption(ValueError):
    """A trusted provider or persisted value failed exact integrity checks."""


@dataclass(frozen=True, slots=True)
class BrokerOrderExecutionScopeDefinition:
    """Consumer-owned projection of one exact active Broker execution scope."""

    execution_scope_id: str
    execution_scope_version: str
    execution_scope_hash: str
    account_id: int
    plan_id: str
    plan_version: str
    plan_content_hash: str
    plan_approval_hash: str
    plan_valid_until: datetime
    order_id: str
    order_version: str
    order_content_hash: str
    order_valid_until: datetime
    scope_valid_until: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "execution_scope_id",
            "execution_scope_version",
            "plan_id",
            "plan_version",
            "order_id",
            "order_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "execution_scope_hash",
            "plan_content_hash",
            "plan_approval_hash",
            "order_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        for field_name in (
            "plan_valid_until",
            "order_valid_until",
            "scope_valid_until",
            "recorded_at",
        ):
            _require_aware(getattr(self, field_name), field_name)

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact definition is knowable and active."""

        _require_aware(as_of, "as_of")
        return (
            self.recorded_at
            <= as_of
            < min(self.plan_valid_until, self.order_valid_until, self.scope_valid_until)
        )


@dataclass(frozen=True, slots=True)
class BrokerOrderRiskPolicyDefinition:
    """Trusted Risk-owned execution-eligible policy projection."""

    policy_id: str
    policy_version: str
    policy_content_hash: str
    account_id: int
    activated_at: datetime
    valid_until: datetime
    recorded_at: datetime
    permission_cap: str = "execution_eligible"

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "policy_id")
        _require_token(self.policy_version, "policy_version")
        _require_hash(self.policy_content_hash, "policy_content_hash")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        for field_name in ("activated_at", "valid_until", "recorded_at"):
            _require_aware(getattr(self, field_name), field_name)
        if self.recorded_at > self.activated_at or self.activated_at >= self.valid_until:
            raise ValueError("risk policy clock sequence is invalid")
        if self.permission_cap != "execution_eligible":
            raise ValueError("risk policy is not execution eligible")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact policy is knowable and active."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= self.activated_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class RegisterBrokerOrderRiskAuthorizationSubjectCommand:
    """ID-only command; account, hashes, permission, and clocks are provider-owned."""

    subject_id: str
    execution_scope_id: str
    execution_scope_version: str
    policy_id: str
    policy_version: str
    subject_version: str = BROKER_ORDER_RISK_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "execution_scope_id",
            "execution_scope_version",
            "policy_id",
            "policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ApproveBrokerOrderRiskAuthorizationCommand:
    """ID-only authorization command using the server clock."""

    subject_id: str
    authorization_id: str
    subject_version: str = BROKER_ORDER_RISK_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for field_name in ("subject_id", "subject_version", "authorization_id"):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetExactBrokerOrderRiskAuthorizationCommand:
    """Exact identity/hash/PIT read selector."""

    authorization_id: str
    authorization_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "authorization_id")
        _require_token(self.authorization_version, "authorization_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


class ExactActiveBrokerOrderExecutionScopeProvider(Protocol):
    """Broker Application public port projected at the composition root."""

    def get_exact_active(
        self,
        *,
        execution_scope_id: str,
        execution_scope_version: str,
        as_of: datetime,
    ) -> BrokerOrderExecutionScopeDefinition | None:
        """Return the exact active current scope at one server cutoff."""


class ExactActiveBrokerOrderRiskPolicyProvider(Protocol):
    """Risk policy owner port; callers cannot submit policy content."""

    def get_exact_active(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> BrokerOrderRiskPolicyDefinition | None:
        """Return the exact active current policy at one server cutoff."""


class ExactBrokerOrderRiskAuthorizationSubjectProvider(Protocol):
    """Exact persisted subject reader."""

    def get_exact(
        self,
        *,
        subject_id: str,
        subject_version: str,
        as_of: datetime,
    ) -> BrokerOrderRiskAuthorizationSubject | None:
        """Return one exact subject knowable at the cutoff."""


class BrokerOrderRiskAuthorizationRepository(Protocol):
    """Append-only first-winner store and exact read authority."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Risk Center server clock."""

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationSubject | None:
        """Return one immutable subject identity winner."""

    def get_authorization_winner(
        self, *, authorization_id: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return one immutable authorization identity winner."""

    def get_current_head(
        self, *, account_id: int, order_id: str, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return the unique current logical authorization head."""

    def append_subject(
        self, subject: BrokerOrderRiskAuthorizationSubject, *, recorded_at: datetime
    ) -> BrokerOrderRiskAuthorizationSubject:
        """Append or return the exact first winner."""

    def append(
        self,
        record: BrokerOrderRiskAuthorizationRecord,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerOrderRiskAuthorizationRecord:
        """Append with current-head compare-and-swap."""

    def get_exact_by_hash(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return an exact authorization knowable at the PIT cutoff."""


class RegisterBrokerOrderRiskAuthorizationSubject:
    """Register one provider-owned Broker scope and Risk policy intersection."""

    def __init__(
        self,
        *,
        scope_provider: ExactActiveBrokerOrderExecutionScopeProvider,
        policy_provider: ExactActiveBrokerOrderRiskPolicyProvider,
        repository: BrokerOrderRiskAuthorizationRepository,
        actor: BrokerOrderRiskAuthorizationActor,
    ) -> None:
        self._scope_provider = scope_provider
        self._policy_provider = policy_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: RegisterBrokerOrderRiskAuthorizationSubjectCommand
    ) -> BrokerOrderRiskAuthorizationSubject:
        """Seal one first-winner subject after two exact owner reads."""

        if not self._actor.is_human_staff:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "risk authorization registration requires human staff"
            )
        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Risk Center server clock")
            first_scope = self._read_scope(command, recorded_at)
            first_policy = self._read_policy(command, recorded_at)
            if first_scope.account_id != first_policy.account_id:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "Broker scope and Risk policy account identities differ"
                )
            winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                account_id=first_scope.account_id,
                order_id=first_scope.order_id,
                as_of=recorded_at,
            )
            final_scope = self._read_scope(command, recorded_at)
            final_policy = self._read_policy(command, recorded_at)
            if first_scope != final_scope or first_policy != final_policy:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "authorization sources changed during registration"
                )
            scope = self._build_scope(final_scope, final_policy)
            candidate = BrokerOrderRiskAuthorizationSubject(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                scope=scope,
                requested_by=self._actor,
                requested_at=recorded_at,
                valid_until=scope.effective_valid_until,
                supersedes_authorization_hash=head.content_hash if head else None,
            )
            if winner is not None:
                if winner != candidate:
                    raise BrokerOrderRiskAuthorizationConflict(
                        "risk authorization subject identity has another first winner"
                    )
                return winner
            persisted = self._repository.append_subject(candidate, recorded_at=recorded_at)
            if persisted != candidate:
                raise BrokerOrderRiskAuthorizationConflict(
                    "concurrent risk subject first winner differs"
                )
            return persisted

    def _read_scope(
        self,
        command: RegisterBrokerOrderRiskAuthorizationSubjectCommand,
        as_of: datetime,
    ) -> BrokerOrderExecutionScopeDefinition:
        value = self._scope_provider.get_exact_active(
            execution_scope_id=command.execution_scope_id,
            execution_scope_version=command.execution_scope_version,
            as_of=as_of,
        )
        if value is None:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active Broker execution scope is unavailable"
            )
        if type(value) is not BrokerOrderExecutionScopeDefinition:
            raise BrokerOrderRiskAuthorizationCorruption("Broker scope type substitution")
        if not value.is_active_at(as_of):
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active Broker execution scope is unavailable"
            )
        if (
            value.execution_scope_id != command.execution_scope_id
            or value.execution_scope_version != command.execution_scope_version
        ):
            raise BrokerOrderRiskAuthorizationCorruption("Broker scope identity substitution")
        return value

    def _read_policy(
        self,
        command: RegisterBrokerOrderRiskAuthorizationSubjectCommand,
        as_of: datetime,
    ) -> BrokerOrderRiskPolicyDefinition:
        value = self._policy_provider.get_exact_active(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            as_of=as_of,
        )
        if value is None:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active Broker order Risk policy is unavailable"
            )
        if type(value) is not BrokerOrderRiskPolicyDefinition:
            raise BrokerOrderRiskAuthorizationCorruption("Risk policy type substitution")
        if not value.is_active_at(as_of):
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active Broker order Risk policy is unavailable"
            )
        if value.policy_id != command.policy_id or value.policy_version != command.policy_version:
            raise BrokerOrderRiskAuthorizationCorruption("Risk policy identity substitution")
        return value

    @staticmethod
    def _build_scope(
        source: BrokerOrderExecutionScopeDefinition,
        policy: BrokerOrderRiskPolicyDefinition,
    ) -> BrokerOrderRiskScope:
        return BrokerOrderRiskScope(
            account_id=source.account_id,
            execution_scope_id=source.execution_scope_id,
            execution_scope_version=source.execution_scope_version,
            execution_scope_hash=source.execution_scope_hash,
            plan_id=source.plan_id,
            plan_version=source.plan_version,
            plan_content_hash=source.plan_content_hash,
            plan_approval_hash=source.plan_approval_hash,
            plan_valid_until=source.plan_valid_until,
            order_id=source.order_id,
            order_version=source.order_version,
            order_content_hash=source.order_content_hash,
            order_valid_until=source.order_valid_until,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_content_hash=policy.policy_content_hash,
            policy_valid_until=policy.valid_until,
            execution_scope_valid_until=source.scope_valid_until,
        )


class ApproveBrokerOrderRiskAuthorization:
    """Approve one exact subject with a distinct trusted human actor."""

    def __init__(
        self,
        *,
        subject_provider: ExactBrokerOrderRiskAuthorizationSubjectProvider,
        scope_provider: ExactActiveBrokerOrderExecutionScopeProvider,
        policy_provider: ExactActiveBrokerOrderRiskPolicyProvider,
        repository: BrokerOrderRiskAuthorizationRepository,
        actor: BrokerOrderRiskAuthorizationActor,
    ) -> None:
        self._subject_provider = subject_provider
        self._scope_provider = scope_provider
        self._policy_provider = policy_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: ApproveBrokerOrderRiskAuthorizationCommand
    ) -> BrokerOrderRiskAuthorizationRecord:
        """Seal one first-winner authorization using the server clock."""

        if not self._actor.is_human_staff:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "risk authorization approval requires human staff"
            )
        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Risk Center server clock")
            first = self._read_subject(command, recorded_at)
            first_scope, first_policy = self._read_sources(first, recorded_at)
            winner = self._repository.get_authorization_winner(
                authorization_id=command.authorization_id, as_of=recorded_at
            )
            head = self._repository.get_current_head(
                account_id=first.scope.account_id,
                order_id=first.scope.order_id,
                as_of=recorded_at,
            )
            final = self._read_subject(command, recorded_at)
            final_scope, final_policy = self._read_sources(final, recorded_at)
            if first != final or first_scope != final_scope or first_policy != final_policy:
                raise BrokerOrderRiskAuthorizationCorruption(
                    "risk authorization subject or owner source changed during approval"
                )
            predecessor = head.content_hash if head else None
            if final.supersedes_authorization_hash != predecessor:
                raise BrokerOrderRiskAuthorizationConflict(
                    "risk authorization subject no longer binds current head"
                )
            candidate = BrokerOrderRiskAuthorizationRecord(
                authorization_id=command.authorization_id,
                subject=final,
                approved_by=self._actor,
                issued_at=recorded_at,
                valid_until=final.valid_until,
            )
            if winner is not None:
                if winner != candidate:
                    raise BrokerOrderRiskAuthorizationConflict(
                        "risk authorization identity has another first winner"
                    )
                return winner
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=predecessor,
                recorded_at=recorded_at,
            )
            if persisted != candidate:
                raise BrokerOrderRiskAuthorizationConflict(
                    "concurrent risk authorization first winner differs"
                )
            return persisted

    def _read_subject(
        self, command: ApproveBrokerOrderRiskAuthorizationCommand, as_of: datetime
    ) -> BrokerOrderRiskAuthorizationSubject:
        value = self._subject_provider.get_exact(
            subject_id=command.subject_id,
            subject_version=command.subject_version,
            as_of=as_of,
        )
        if value is None:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active risk authorization subject is unavailable"
            )
        if type(value) is not BrokerOrderRiskAuthorizationSubject:
            raise BrokerOrderRiskAuthorizationCorruption("risk subject type substitution")
        if not value.is_valid_at(as_of):
            raise BrokerOrderRiskAuthorizationUnavailable(
                "exact active risk authorization subject is unavailable"
            )
        if (
            value.subject_id != command.subject_id
            or value.subject_version != command.subject_version
        ):
            raise BrokerOrderRiskAuthorizationCorruption("risk subject identity substitution")
        return value

    def _read_sources(
        self,
        subject: BrokerOrderRiskAuthorizationSubject,
        as_of: datetime,
    ) -> tuple[BrokerOrderExecutionScopeDefinition, BrokerOrderRiskPolicyDefinition]:
        scope = self._scope_provider.get_exact_active(
            execution_scope_id=subject.scope.execution_scope_id,
            execution_scope_version=subject.scope.execution_scope_version,
            as_of=as_of,
        )
        policy = self._policy_provider.get_exact_active(
            policy_id=subject.scope.policy_id,
            policy_version=subject.scope.policy_version,
            as_of=as_of,
        )
        if scope is None or policy is None:
            raise BrokerOrderRiskAuthorizationUnavailable(
                "authorization owner source is no longer active"
            )
        if (
            type(scope) is not BrokerOrderExecutionScopeDefinition
            or type(policy) is not BrokerOrderRiskPolicyDefinition
        ):
            raise BrokerOrderRiskAuthorizationCorruption(
                "authorization owner source type substitution"
            )
        if not scope.is_active_at(as_of) or not policy.is_active_at(as_of):
            raise BrokerOrderRiskAuthorizationUnavailable(
                "authorization owner source is no longer active"
            )
        rebuilt = RegisterBrokerOrderRiskAuthorizationSubject._build_scope(scope, policy)
        if rebuilt != subject.scope:
            raise BrokerOrderRiskAuthorizationCorruption(
                "authorization owner source no longer matches the sealed subject"
            )
        return scope, policy


class GetExactBrokerOrderRiskAuthorization:
    """Expose a strict exact identity/hash/PIT read."""

    def __init__(self, repository: BrokerOrderRiskAuthorizationRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactBrokerOrderRiskAuthorizationCommand
    ) -> BrokerOrderRiskAuthorizationRecord | None:
        """Return only the exact valid authorization requested by the consumer."""

        value = self._repository.get_exact_by_hash(
            authorization_id=command.authorization_id,
            authorization_version=command.authorization_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        if type(value) is not BrokerOrderRiskAuthorizationRecord:
            raise BrokerOrderRiskAuthorizationCorruption("authorization type substitution")
        BrokerOrderRiskAuthorizationRecord.__post_init__(value)
        if (
            value.authorization_id != command.authorization_id
            or value.authorization_version != command.authorization_version
            or value.content_hash != command.expected_content_hash
        ):
            raise BrokerOrderRiskAuthorizationCorruption("authorization identity substitution")
        if not value.is_valid_at(command.as_of):
            return None
        return value


__all__ = [
    "ApproveBrokerOrderRiskAuthorization",
    "ApproveBrokerOrderRiskAuthorizationCommand",
    "BrokerOrderExecutionScopeDefinition",
    "BrokerOrderRiskAuthorizationConflict",
    "BrokerOrderRiskAuthorizationCorruption",
    "BrokerOrderRiskAuthorizationRepository",
    "BrokerOrderRiskAuthorizationUnavailable",
    "BrokerOrderRiskPolicyDefinition",
    "ExactActiveBrokerOrderExecutionScopeProvider",
    "ExactActiveBrokerOrderRiskPolicyProvider",
    "ExactBrokerOrderRiskAuthorizationSubjectProvider",
    "GetExactBrokerOrderRiskAuthorization",
    "GetExactBrokerOrderRiskAuthorizationCommand",
    "RegisterBrokerOrderRiskAuthorizationSubject",
    "RegisterBrokerOrderRiskAuthorizationSubjectCommand",
]
