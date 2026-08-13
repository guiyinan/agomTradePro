"""ID-only workflow for Portfolio benchmark methodology bundle activation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundleActivation,
    validate_policy_benchmark_methodology_activation_successor,
)


def _token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class PolicyBenchmarkMethodologyActivationUnavailable(ValueError):
    """One exact definition, methodology, subject, or activation is unavailable."""


class PolicyBenchmarkMethodologyActivationConflict(ValueError):
    """An immutable identity or logical head has another first winner."""


class PolicyBenchmarkMethodologyActivationCorruption(ValueError):
    """A trusted provider or repository substituted invalid state."""


@dataclass(frozen=True, slots=True)
class RegisterPolicyBenchmarkMethodologyActivationSubjectCommand:
    """ID-only registration selector without hashes, clocks, or actor payloads."""

    subject_id: str
    subject_version: str
    definition_id: str
    definition_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "definition_id",
            "definition_version",
        ):
            _token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ApprovePolicyBenchmarkMethodologyActivationCommand:
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
            _token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class GetExactPolicyBenchmarkMethodologyActivationCommand:
    """Historical exact identity/hash/PIT selector."""

    activation_id: str
    activation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.activation_id, "activation_id")
        _token(self.activation_version, "activation_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentPolicyBenchmarkMethodologyActivationCommand:
    """Closed selector for one exact logical-current bundle activation."""

    activation: PolicyBenchmarkMethodologyBundleActivation
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.activation) is not PolicyBenchmarkMethodologyBundleActivation:
            raise TypeError("activation must be an exact bundle activation")
        PolicyBenchmarkMethodologyBundleActivation.__post_init__(self.activation)
        _aware(self.as_of, "as_of")


class ExactPolicyBenchmarkDefinitionProvider(Protocol):
    """Portfolio-owned exact-current benchmark definition reader."""

    def get_exact_current(
        self,
        *,
        definition_id: str,
        definition_version: str,
        as_of: datetime,
    ) -> PortfolioPolicyBenchmarkDefinition | None:
        """Return the exact logical-current definition at the cutoff."""


class ExactPolicyBenchmarkMethodologyProvider(Protocol):
    """Portfolio-owned exact-current methodology definition reader."""

    def get_exact_current(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> PolicyBenchmarkMethodologyRef | None:
        """Return one exact logical-current methodology reference."""


class PolicyBenchmarkMethodologyActivationRepository(Protocol):
    """Private append-only subject/activation persistence port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one private first-winner transaction."""

    def now(self) -> datetime:
        """Return the authoritative Portfolio server clock."""

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyActivationSubject | None:
        """Return one immutable subject identity winner."""

    def get_activation_winner(
        self, *, activation_id: str, activation_version: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return one immutable activation identity winner."""

    def get_current_head(
        self, *, definition_id: str, as_of: datetime
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return the logical bundle activation head at the cutoff."""

    def append_subject(
        self,
        subject: PolicyBenchmarkMethodologyActivationSubject,
        *,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        """Append or replay one exact subject first winner."""

    def append(
        self,
        activation: PolicyBenchmarkMethodologyBundleActivation,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        """CAS-append or replay one exact activation."""

    def get_exact_by_hash(
        self,
        *,
        activation_id: str,
        activation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return one historical exact identity/hash record."""


class RegisterPolicyBenchmarkMethodologyActivationSubject:
    """Register one server-owned request for an exact five-source bundle."""

    def __init__(
        self,
        *,
        definition_provider: ExactPolicyBenchmarkDefinitionProvider,
        methodology_provider: ExactPolicyBenchmarkMethodologyProvider,
        repository: PolicyBenchmarkMethodologyActivationRepository,
        actor: PolicyBenchmarkMethodologyActivationActor,
    ) -> None:
        PolicyBenchmarkMethodologyActivationActor.__post_init__(actor)
        self._definition_provider = definition_provider
        self._methodology_provider = methodology_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: RegisterPolicyBenchmarkMethodologyActivationSubjectCommand
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        """Double-read the definition graph and append one actor-owned winner."""

        if type(command) is not RegisterPolicyBenchmarkMethodologyActivationSubjectCommand:
            raise TypeError("command must be exact registration command")
        RegisterPolicyBenchmarkMethodologyActivationSubjectCommand.__post_init__(command)
        with self._repository.atomic():
            cutoff = _aware(self._repository.now(), "Portfolio server clock")
            first = _read_graph(
                self._definition_provider,
                self._methodology_provider,
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                as_of=cutoff,
            )
            winner = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                definition_id=command.definition_id,
                as_of=cutoff,
            )
            final = _read_graph(
                self._definition_provider,
                self._methodology_provider,
                definition_id=command.definition_id,
                definition_version=command.definition_version,
                as_of=cutoff,
            )
            if first != final:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "benchmark definition graph changed during registration"
                )
            if winner is not None:
                checked = _subject(winner)
                if not _subject_matches(checked, final, self._actor):
                    raise PolicyBenchmarkMethodologyActivationConflict(
                        "activation subject identity has another first winner"
                    )
                return checked
            checked_head = _head_for_definition(head, command.definition_id)
            predecessor = checked_head.content_hash if checked_head is not None else None
            candidate = PolicyBenchmarkMethodologyActivationSubject.create(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                definition=final,
                requested_by=self._actor,
                requested_at=cutoff,
                supersedes_activation_hash=predecessor,
            )
            persisted = self._repository.append_subject(candidate, recorded_at=cutoff)
            if _subject(persisted) != candidate:
                raise PolicyBenchmarkMethodologyActivationConflict(
                    "concurrent activation subject first winner differs"
                )
            return persisted


class ApprovePolicyBenchmarkMethodologyActivation:
    """Approve an exact persisted bundle subject with a second server actor."""

    def __init__(
        self,
        *,
        definition_provider: ExactPolicyBenchmarkDefinitionProvider,
        methodology_provider: ExactPolicyBenchmarkMethodologyProvider,
        repository: PolicyBenchmarkMethodologyActivationRepository,
        actor: PolicyBenchmarkMethodologyActivationActor,
    ) -> None:
        PolicyBenchmarkMethodologyActivationActor.__post_init__(actor)
        self._definition_provider = definition_provider
        self._methodology_provider = methodology_provider
        self._repository = repository
        self._actor = actor

    def execute(
        self, command: ApprovePolicyBenchmarkMethodologyActivationCommand
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        """Revalidate the subject and five sources before predecessor-CAS append."""

        if type(command) is not ApprovePolicyBenchmarkMethodologyActivationCommand:
            raise TypeError("command must be exact approval command")
        ApprovePolicyBenchmarkMethodologyActivationCommand.__post_init__(command)
        with self._repository.atomic():
            cutoff = _aware(self._repository.now(), "Portfolio server clock")
            first_subject = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=cutoff,
            )
            if first_subject is None:
                raise PolicyBenchmarkMethodologyActivationUnavailable(
                    "exact activation subject is unavailable"
                )
            subject = _subject(first_subject)
            if (
                self._actor.actor_id == subject.requested_by.actor_id
                or self._actor.user_id == subject.requested_by.user_id
            ):
                raise PolicyBenchmarkMethodologyActivationUnavailable(
                    "activation approval requires a distinct authenticated actor"
                )
            first_definition = _read_graph(
                self._definition_provider,
                self._methodology_provider,
                definition_id=subject.definition_id,
                definition_version=subject.definition_version,
                as_of=cutoff,
            )
            _require_subject_graph(subject, first_definition)
            winner = self._repository.get_activation_winner(
                activation_id=command.activation_id,
                activation_version=command.activation_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                definition_id=subject.definition_id,
                as_of=cutoff,
            )
            final_subject = self._repository.get_subject_winner(
                subject_id=command.subject_id,
                subject_version=command.subject_version,
                as_of=cutoff,
            )
            final_definition = _read_graph(
                self._definition_provider,
                self._methodology_provider,
                definition_id=subject.definition_id,
                definition_version=subject.definition_version,
                as_of=cutoff,
            )
            if final_subject is None or _subject(final_subject) != subject:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "activation subject changed during approval"
                )
            if first_definition != final_definition:
                raise PolicyBenchmarkMethodologyActivationCorruption(
                    "benchmark definition graph changed during approval"
                )
            _require_subject_graph(subject, final_definition)
            if winner is not None:
                checked = _activation(winner)
                if checked.subject != subject or checked.approved_by != self._actor:
                    raise PolicyBenchmarkMethodologyActivationConflict(
                        "activation identity has another first winner"
                    )
                checked_head = _head_for_definition(head, subject.definition_id)
                if checked_head != checked:
                    raise PolicyBenchmarkMethodologyActivationConflict(
                        "activation winner is no longer the logical current head"
                    )
                return checked
            checked_head = _head_for_definition(head, subject.definition_id)
            predecessor = checked_head.content_hash if checked_head is not None else None
            if subject.supersedes_activation_hash != predecessor:
                raise PolicyBenchmarkMethodologyActivationConflict(
                    "activation subject no longer binds the current head"
                )
            candidate = PolicyBenchmarkMethodologyBundleActivation.create(
                activation_id=command.activation_id,
                activation_version=command.activation_version,
                subject=subject,
                approved_by=self._actor,
                issued_at=cutoff,
            )
            if checked_head is not None:
                try:
                    validate_policy_benchmark_methodology_activation_successor(
                        checked_head, candidate
                    )
                except (TypeError, ValueError) as error:
                    raise PolicyBenchmarkMethodologyActivationConflict(
                        "activation successor is invalid"
                    ) from error
            persisted = self._repository.append(
                candidate,
                expected_predecessor_hash=predecessor,
                recorded_at=cutoff,
            )
            if _activation(persisted) != candidate:
                raise PolicyBenchmarkMethodologyActivationConflict(
                    "concurrent activation first winner differs"
                )
            return persisted


class GetExactPolicyBenchmarkMethodologyActivation:
    """Read historical exact activation by identity, hash, and PIT."""

    def __init__(self, repository: PolicyBenchmarkMethodologyActivationRepository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactPolicyBenchmarkMethodologyActivationCommand
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Return only the exact knowable configuration activation."""

        if type(command) is not GetExactPolicyBenchmarkMethodologyActivationCommand:
            raise TypeError("command must be exact historical read command")
        GetExactPolicyBenchmarkMethodologyActivationCommand.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            activation_id=command.activation_id,
            activation_version=command.activation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        activation = _activation(value)
        if (
            activation.activation_id != command.activation_id
            or activation.activation_version != command.activation_version
            or activation.content_hash != command.expected_content_hash
        ):
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "exact activation identity substitution"
            )
        if not activation.is_valid_at(command.as_of):
            return None
        _require_safe_authority(activation)
        return activation


class GetCurrentPolicyBenchmarkMethodologyActivation:
    """Read one exact logical-current activation with a still-current source graph."""

    def __init__(
        self,
        *,
        definition_provider: ExactPolicyBenchmarkDefinitionProvider,
        methodology_provider: ExactPolicyBenchmarkMethodologyProvider,
        repository: PolicyBenchmarkMethodologyActivationRepository,
    ) -> None:
        self._definition_provider = definition_provider
        self._methodology_provider = methodology_provider
        self._repository = repository

    def execute(
        self, command: GetCurrentPolicyBenchmarkMethodologyActivationCommand
    ) -> PolicyBenchmarkMethodologyBundleActivation | None:
        """Reject superseded activation or any stale/replaced methodology source."""

        if type(command) is not GetCurrentPolicyBenchmarkMethodologyActivationCommand:
            raise TypeError("command must be exact current read command")
        GetCurrentPolicyBenchmarkMethodologyActivationCommand.__post_init__(command)
        expected = command.activation
        exact = GetExactPolicyBenchmarkMethodologyActivation(self._repository).execute(
            GetExactPolicyBenchmarkMethodologyActivationCommand(
                activation_id=expected.activation_id,
                activation_version=expected.activation_version,
                expected_content_hash=expected.content_hash,
                as_of=command.as_of,
            )
        )
        if exact is None or exact != expected:
            return None
        head = self._repository.get_current_head(
            definition_id=expected.subject.definition_id,
            as_of=command.as_of,
        )
        if head is None or _activation(head) != expected:
            return None
        try:
            definition = _read_graph(
                self._definition_provider,
                self._methodology_provider,
                definition_id=expected.subject.definition_id,
                definition_version=expected.subject.definition_version,
                as_of=command.as_of,
            )
            _require_subject_graph(expected.subject, definition)
        except PolicyBenchmarkMethodologyActivationUnavailable:
            return None
        _require_safe_authority(expected)
        return expected


def _read_graph(
    definition_provider: ExactPolicyBenchmarkDefinitionProvider,
    methodology_provider: ExactPolicyBenchmarkMethodologyProvider,
    *,
    definition_id: str,
    definition_version: str,
    as_of: datetime,
) -> PortfolioPolicyBenchmarkDefinition:
    definition = definition_provider.get_exact_current(
        definition_id=definition_id,
        definition_version=definition_version,
        as_of=as_of,
    )
    if definition is None:
        raise PolicyBenchmarkMethodologyActivationUnavailable(
            "exact current benchmark definition is unavailable"
        )
    if type(definition) is not PortfolioPolicyBenchmarkDefinition:
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "benchmark definition type substitution"
        )
    PortfolioPolicyBenchmarkDefinition.__post_init__(definition)
    if (
        definition.definition_id != definition_id
        or definition.definition_version != definition_version
        or not definition.is_knowable_at(as_of)
    ):
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "benchmark definition selector substitution"
        )
    for expected in _definition_refs(definition):
        actual = methodology_provider.get_exact_current(
            artifact_type=expected.artifact_type,
            artifact_id=expected.artifact_id,
            artifact_version=expected.artifact_version,
            as_of=as_of,
        )
        if actual is None:
            raise PolicyBenchmarkMethodologyActivationUnavailable(
                f"exact current {expected.artifact_type} is unavailable"
            )
        if type(actual) is not PolicyBenchmarkMethodologyRef:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology definition type substitution"
            )
        PolicyBenchmarkMethodologyRef.__post_init__(actual)
        if actual != expected:
            raise PolicyBenchmarkMethodologyActivationCorruption(
                "methodology definition selector or content substitution"
            )
        if not actual.recorded_at <= as_of < actual.valid_until:
            raise PolicyBenchmarkMethodologyActivationUnavailable(
                "methodology definition is not current"
            )
    return definition


def _definition_refs(
    definition: PortfolioPolicyBenchmarkDefinition,
) -> tuple[PolicyBenchmarkMethodologyRef, ...]:
    return (
        definition.corporate_action_ref,
        definition.cost_tax_ref,
        definition.fx_fixing_ref,
        definition.price_fixing_ref,
        definition.trading_calendar_ref,
    )


def _subject_matches(
    subject: PolicyBenchmarkMethodologyActivationSubject,
    definition: PortfolioPolicyBenchmarkDefinition,
    actor: PolicyBenchmarkMethodologyActivationActor,
) -> bool:
    expected = PolicyBenchmarkMethodologyActivationSubject.create(
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        definition=definition,
        requested_by=actor,
        requested_at=subject.requested_at,
        supersedes_activation_hash=subject.supersedes_activation_hash,
    )
    return bool(expected == subject)


def _require_subject_graph(
    subject: PolicyBenchmarkMethodologyActivationSubject,
    definition: PortfolioPolicyBenchmarkDefinition,
) -> None:
    expected = PolicyBenchmarkMethodologyActivationSubject.create(
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        definition=definition,
        requested_by=subject.requested_by,
        requested_at=subject.requested_at,
        supersedes_activation_hash=subject.supersedes_activation_hash,
    )
    if expected != subject:
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "activation subject no longer binds the exact definition graph"
        )


def _subject(value: object) -> PolicyBenchmarkMethodologyActivationSubject:
    if type(value) is not PolicyBenchmarkMethodologyActivationSubject:
        raise PolicyBenchmarkMethodologyActivationCorruption("activation subject type substitution")
    PolicyBenchmarkMethodologyActivationSubject.__post_init__(value)
    return value


def _activation(value: object) -> PolicyBenchmarkMethodologyBundleActivation:
    if type(value) is not PolicyBenchmarkMethodologyBundleActivation:
        raise PolicyBenchmarkMethodologyActivationCorruption("bundle activation type substitution")
    PolicyBenchmarkMethodologyBundleActivation.__post_init__(value)
    return value


def _head_for_definition(
    value: object | None,
    definition_id: str,
) -> PolicyBenchmarkMethodologyBundleActivation | None:
    if value is None:
        return None
    head = _activation(value)
    if head.subject.definition_id != definition_id:
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "logical current head definition substitution"
        )
    return head


def _require_safe_authority(
    activation: PolicyBenchmarkMethodologyBundleActivation,
) -> None:
    if (
        activation.daily_valuation_authority
        or activation.broker_execution_authority
        or not activation.must_not_execute
    ):
        raise PolicyBenchmarkMethodologyActivationCorruption(
            "bundle activation authority substitution"
        )


__all__ = [
    "ApprovePolicyBenchmarkMethodologyActivation",
    "ApprovePolicyBenchmarkMethodologyActivationCommand",
    "ExactPolicyBenchmarkDefinitionProvider",
    "ExactPolicyBenchmarkMethodologyProvider",
    "GetCurrentPolicyBenchmarkMethodologyActivation",
    "GetCurrentPolicyBenchmarkMethodologyActivationCommand",
    "GetExactPolicyBenchmarkMethodologyActivation",
    "GetExactPolicyBenchmarkMethodologyActivationCommand",
    "PolicyBenchmarkMethodologyActivationConflict",
    "PolicyBenchmarkMethodologyActivationCorruption",
    "PolicyBenchmarkMethodologyActivationRepository",
    "PolicyBenchmarkMethodologyActivationUnavailable",
    "RegisterPolicyBenchmarkMethodologyActivationSubject",
    "RegisterPolicyBenchmarkMethodologyActivationSubjectCommand",
]
