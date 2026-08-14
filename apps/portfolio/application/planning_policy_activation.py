"""ID-only workflow for Portfolio planning-policy activation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.planning_policy_activation import (
    PlanningPolicyActivation,
    PlanningPolicyActivationActor,
    PlanningPolicyActivationSubject,
    validate_planning_policy_activation_successor,
)
from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition


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


class PlanningPolicyActivationUnavailable(ValueError):
    """An exact definition, subject, or activation is unavailable."""


class PlanningPolicyActivationConflict(ValueError):
    """An immutable identity or logical head has another first winner."""


class PlanningPolicyActivationCorruption(ValueError):
    """A trusted provider or repository substituted invalid state."""


@dataclass(frozen=True, slots=True)
class RegisterPlanningPolicyActivationSubjectCommand:
    """ID-only registration selector; no hashes, clocks, or actor payloads."""

    subject_id: str
    subject_version: str
    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "policy_id",
            "policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ApprovePlanningPolicyActivationCommand:
    """ID-only approval selector."""

    subject_id: str
    subject_version: str
    activation_id: str
    activation_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "activation_id",
            "activation_version",
        ):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetCurrentPlanningPolicyActivationCommand:
    """Closed selector for an exact current activation."""

    activation_id: str
    activation_version: str
    expected_content_hash: str
    policy_id: str
    policy_version: str
    definition_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "activation_id",
            "activation_version",
            "policy_id",
            "policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_hash(self.definition_content_hash, "definition_content_hash")
        _require_aware(self.as_of, "as_of")


class ExactPlanningPolicyDefinitionProvider(Protocol):
    """Portfolio-owned exact and unexpired definition reader."""

    def get_exact(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> PlanningPolicyDefinition | None:
        """Return the exact definition at an aware cutoff."""


class PlanningPolicyActivationRepository(Protocol):
    """Private append-only subject and activation persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one private first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Portfolio server clock."""

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PlanningPolicyActivationSubject | None:
        """Return one immutable subject identity winner."""

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        """Return one immutable activation identity winner."""

    def get_current_head(
        self, *, policy_id: str, as_of: datetime
    ) -> PlanningPolicyActivation | None:
        """Return the logical activation head at the cutoff."""

    def append_subject(
        self,
        subject: PlanningPolicyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PlanningPolicyActivationSubject:
        """Append or return the exact subject first winner."""

    def append(
        self,
        activation: PlanningPolicyActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PlanningPolicyActivation:
        """Append or return the exact activation using predecessor CAS."""


class RegisterPlanningPolicyActivationSubject:
    """Register a server-owned request for one exact policy definition."""

    def __init__(
        self,
        *,
        definition_provider: ExactPlanningPolicyDefinitionProvider,
        repository: PlanningPolicyActivationRepository,
        actor: PlanningPolicyActivationActor,
    ) -> None:
        PlanningPolicyActivationActor.__post_init__(actor)
        self._definition_provider = definition_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: RegisterPlanningPolicyActivationSubjectCommand
    ) -> PlanningPolicyActivationSubject:
        """Double-read the definition and append one actor-owned first winner."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Portfolio server clock")
            first = self._read_definition(command, recorded_at)
            winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                policy_id=command.policy_id,
                as_of=recorded_at,
            )
            final = self._read_definition(command, recorded_at)
            if first != final:
                raise PlanningPolicyActivationCorruption(
                    "planning policy definition changed during registration"
                )
            if winner is not None:
                checked = _validate_subject(winner)
                if (
                    checked.subject_id != command.subject_id
                    or checked.subject_version != command.subject_version
                    or checked.policy_id != command.policy_id
                    or checked.policy_version != command.policy_version
                    or checked.definition_identity_hash != final.identity_hash
                    or checked.definition_content_hash != final.content_hash
                    or checked.requested_by != self._actor
                ):
                    raise PlanningPolicyActivationConflict(
                        "activation subject identity has another first winner"
                    )
                return checked
            predecessor = head.content_hash if head is not None else None
            candidate = PlanningPolicyActivationSubject.create(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                definition=final,
                requested_by=self._actor,
                requested_at=recorded_at,
                supersedes_activation_hash=predecessor,
            )
            persisted = self._repository.append_subject(
                candidate,
                recorded_at=recorded_at,
            )
            if _validate_subject(persisted) != candidate:
                raise PlanningPolicyActivationConflict(
                    "concurrent activation subject first winner differs"
                )
            return persisted

    def _read_definition(
        self,
        command: RegisterPlanningPolicyActivationSubjectCommand,
        as_of: datetime,
    ) -> PlanningPolicyDefinition:
        return _read_definition(
            self._definition_provider,
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            as_of=as_of,
        )


class ApprovePlanningPolicyActivation:
    """Approve an exact persisted subject with a second server actor."""

    def __init__(
        self,
        *,
        definition_provider: ExactPlanningPolicyDefinitionProvider,
        repository: PlanningPolicyActivationRepository,
        actor: PlanningPolicyActivationActor,
    ) -> None:
        PlanningPolicyActivationActor.__post_init__(actor)
        self._definition_provider = definition_provider
        self._repository = repository
        self._actor = actor

    def execute(self, command: ApprovePlanningPolicyActivationCommand) -> PlanningPolicyActivation:
        """Double-read the persisted subject and definition before CAS append."""

        with self._repository.atomic():
            recorded_at = self._repository.now()
            _require_aware(recorded_at, "Portfolio server clock")
            first_subject = self._read_subject(command, recorded_at)
            first_definition = _read_definition(
                self._definition_provider,
                policy_id=first_subject.policy_id,
                policy_version=first_subject.policy_version,
                as_of=recorded_at,
            )
            winner = self._repository.get_activation_winner(
                activation_id=command.activation_id,
                activation_version=command.activation_version,
                as_of=recorded_at,
            )
            head = self._repository.get_current_head(
                policy_id=first_subject.policy_id,
                as_of=recorded_at,
            )
            final_subject = self._read_subject(command, recorded_at)
            final_definition = _read_definition(
                self._definition_provider,
                policy_id=final_subject.policy_id,
                policy_version=final_subject.policy_version,
                as_of=recorded_at,
            )
            if first_subject != final_subject or first_definition != final_definition:
                raise PlanningPolicyActivationCorruption(
                    "activation sources changed during approval"
                )
            if (
                final_subject.definition_identity_hash != final_definition.identity_hash
                or final_subject.definition_content_hash != final_definition.content_hash
                or final_subject.valid_until != final_definition.valid_until
            ):
                raise PlanningPolicyActivationCorruption(
                    "activation subject no longer binds its exact definition"
                )
            if winner is not None:
                checked = _validate_activation(winner)
                if (
                    checked.activation_id != command.activation_id
                    or checked.activation_version != command.activation_version
                    or checked.subject != final_subject
                    or checked.approved_by != self._actor
                ):
                    raise PlanningPolicyActivationConflict(
                        "activation identity has another first winner"
                    )
                if head is None or _validate_activation(head) != checked:
                    raise PlanningPolicyActivationConflict(
                        "activation identity is no longer the current head"
                    )
                if not checked.is_valid_at(recorded_at):
                    raise PlanningPolicyActivationUnavailable(
                        "planning policy activation is no longer active"
                    )
                return checked
            expected_predecessor = final_subject.supersedes_activation_hash
            actual_predecessor = head.content_hash if head is not None else None
            if expected_predecessor != actual_predecessor:
                raise PlanningPolicyActivationConflict(
                    "activation subject no longer binds the logical head"
                )
            try:
                candidate = PlanningPolicyActivation.create(
                    activation_id=command.activation_id,
                    activation_version=command.activation_version,
                    subject=final_subject,
                    approved_by=self._actor,
                    issued_at=recorded_at,
                )
                if head is not None:
                    validate_planning_policy_activation_successor(head, candidate)
            except (TypeError, ValueError) as error:
                raise PlanningPolicyActivationConflict(
                    "planning policy activation approval is invalid"
                ) from error
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=expected_predecessor,
                recorded_at=recorded_at,
            )
            if _validate_activation(persisted) != candidate:
                raise PlanningPolicyActivationConflict("concurrent activation first winner differs")
            return persisted

    def _read_subject(
        self,
        command: ApprovePlanningPolicyActivationCommand,
        as_of: datetime,
    ) -> PlanningPolicyActivationSubject:
        value = self._repository.get_subject_winner(
            subject_id=command.subject_id,
            subject_version=command.subject_version,
            as_of=as_of,
        )
        if value is None:
            raise PlanningPolicyActivationUnavailable("exact activation subject is unavailable")
        checked = _validate_subject(value)
        if (
            checked.subject_id != command.subject_id
            or checked.subject_version != command.subject_version
        ):
            raise PlanningPolicyActivationCorruption("subject identity substitution")
        if not checked.is_valid_at(as_of):
            raise PlanningPolicyActivationUnavailable("exact activation subject is unavailable")
        return checked


class GetCurrentPlanningPolicyActivation:
    """Read only exact, valid, logical-current activation state."""

    def __init__(self, repository: PlanningPolicyActivationRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetCurrentPlanningPolicyActivationCommand
    ) -> PlanningPolicyActivation | None:
        """Return None for historical/superseded/expired state and fail on aliasing."""

        value = self._repository.get_activation_winner(
            activation_id=command.activation_id,
            activation_version=command.activation_version,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = _validate_activation(value)
        subject = checked.subject
        if (
            checked.activation_id != command.activation_id
            or checked.activation_version != command.activation_version
            or checked.content_hash != command.expected_content_hash
            or subject.policy_id != command.policy_id
            or subject.policy_version != command.policy_version
            or subject.definition_content_hash != command.definition_content_hash
        ):
            raise PlanningPolicyActivationCorruption("activation selector substitution")
        head = self._repository.get_current_head(
            policy_id=command.policy_id,
            as_of=command.as_of,
        )
        if head is None:
            raise PlanningPolicyActivationCorruption("activation ledger has no head")
        current = _validate_activation(head)
        if current.content_hash != checked.content_hash:
            return None
        if current != checked:
            raise PlanningPolicyActivationCorruption(
                "activation head differs from its identity winner"
            )
        return checked if checked.is_valid_at(command.as_of) else None


def _read_definition(
    provider: ExactPlanningPolicyDefinitionProvider,
    *,
    policy_id: str,
    policy_version: str,
    as_of: datetime,
) -> PlanningPolicyDefinition:
    value = provider.get_exact(
        policy_id=policy_id,
        policy_version=policy_version,
        as_of=as_of,
    )
    if value is None:
        raise PlanningPolicyActivationUnavailable("exact planning policy definition is unavailable")
    if type(value) is not PlanningPolicyDefinition:
        raise PlanningPolicyActivationCorruption("definition type substitution")
    try:
        PlanningPolicyDefinition.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PlanningPolicyActivationCorruption("definition is invalid") from error
    if value.policy_id != policy_id or value.policy_version != policy_version:
        raise PlanningPolicyActivationCorruption("definition identity substitution")
    if not value.is_knowable_at(as_of):
        raise PlanningPolicyActivationUnavailable("exact planning policy definition is unavailable")
    return value


def _validate_subject(value: object) -> PlanningPolicyActivationSubject:
    if type(value) is not PlanningPolicyActivationSubject:
        raise PlanningPolicyActivationCorruption("subject type substitution")
    try:
        PlanningPolicyActivationSubject.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PlanningPolicyActivationCorruption("subject is invalid") from error
    return value


def _validate_activation(value: object) -> PlanningPolicyActivation:
    if type(value) is not PlanningPolicyActivation:
        raise PlanningPolicyActivationCorruption("activation type substitution")
    try:
        PlanningPolicyActivation.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise PlanningPolicyActivationCorruption("activation is invalid") from error
    return value


__all__ = [
    "ApprovePlanningPolicyActivation",
    "ApprovePlanningPolicyActivationCommand",
    "ExactPlanningPolicyDefinitionProvider",
    "GetCurrentPlanningPolicyActivation",
    "GetCurrentPlanningPolicyActivationCommand",
    "PlanningPolicyActivationConflict",
    "PlanningPolicyActivationCorruption",
    "PlanningPolicyActivationRepository",
    "PlanningPolicyActivationUnavailable",
    "RegisterPlanningPolicyActivationSubject",
    "RegisterPlanningPolicyActivationSubjectCommand",
]
