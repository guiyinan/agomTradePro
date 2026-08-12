"""ID-only registration for the independent Research R8 monitoring policy."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringPolicy,
)
from apps.research.domain.r8_monitoring_policy_registry import (
    R8MonitoringPolicyDefinition,
    R8MonitoringPolicySourceReceipt,
)


class R8MonitoringPolicyRegistryUnavailable(RuntimeError):
    """The dedicated policy definition, source, clock, or UoW is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database transaction identity."""


class R8MonitoringPolicyDefinitionProvider(_UowBound, Protocol):
    """Dedicated Research policy definition owner port."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R8MonitoringPolicyDefinition | None:
        """Return one exact policy definition or explicit absence."""


class R8MonitoringPolicySourceProvider(_UowBound, Protocol):
    """Independent source receipt port for a policy definition."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> R8MonitoringPolicySourceReceipt | None:
        """Return the receipt bound to the exact definition."""


class R8MonitoringPolicyStore(_UowBound, Protocol):
    """Private append capability retained outside production builders."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared owner transaction."""

    def append(
        self,
        *,
        definition: R8MonitoringPolicyDefinition,
        source: R8MonitoringPolicySourceReceipt,
        ledger_recorded_at: datetime,
    ) -> GovernedOptimizationMonitoringPolicy:
        """Append or replay one exact policy winner."""


class R8MonitoringPolicyRegistryClock(_UowBound, Protocol):
    """Trusted server clock inside the shared UoW."""

    def now(self) -> datetime:
        """Return one timezone-aware owner timestamp."""


@dataclass(frozen=True)
class RegisterR8MonitoringPolicyCommand:
    """Policy identity only; no policy body, source, hash, or clock."""

    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        _token(self.policy_id, "R8 monitoring policy_id")
        _token(self.policy_version, "R8 monitoring policy_version")


class RegisterR8MonitoringPolicy:
    """Double-read the dedicated owner graph before one trusted append."""

    def __init__(
        self,
        *,
        definition_provider: R8MonitoringPolicyDefinitionProvider,
        source_provider: R8MonitoringPolicySourceProvider,
        store: R8MonitoringPolicyStore,
        clock: R8MonitoringPolicyRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._source_provider = source_provider
        self._store = store
        self._clock = clock
        self._participants: tuple[_UowBound, ...] = (
            definition_provider,
            source_provider,
            store,
            clock,
        )
        self._participant_ids = tuple(id(item) for item in self._participants)
        self._expected_uow_key = _shared_uow(self._participants)

    def execute(
        self,
        command: RegisterR8MonitoringPolicyCommand,
    ) -> GovernedOptimizationMonitoringPolicy:
        """Append only a stable policy graph; every failure remains zero-write."""

        try:
            _validate_command(command)
            self._require_unchanged()
            with self._store.atomic():
                self._require_unchanged()
                now = self._clock.now()
                _aware(now, "R8 monitoring policy trusted clock")
                first = self._read(command, now=now)
                self._require_unchanged()
                second = self._read(command, now=now)
                self._require_unchanged()
                if first != second:
                    raise R8MonitoringPolicyRegistryUnavailable(
                        "R8 monitoring policy owner graph changed during reread"
                    )
                definition, source = second
                result = self._store.append(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_unchanged()
                if type(result) is not GovernedOptimizationMonitoringPolicy:
                    raise TypeError("R8 monitoring policy store returned another type")
                canonical = R8MonitoringPolicyDefinition.from_policy(result).policy
                if canonical != definition.policy:
                    raise ValueError("R8 monitoring policy winner differs")
                return canonical
        except R8MonitoringPolicyRegistryUnavailable:
            raise
        except Exception as error:
            raise R8MonitoringPolicyRegistryUnavailable(
                "R8 monitoring policy registration is unavailable"
            ) from error

    def _read(
        self,
        command: RegisterR8MonitoringPolicyCommand,
        *,
        now: datetime,
    ) -> tuple[R8MonitoringPolicyDefinition, R8MonitoringPolicySourceReceipt]:
        value = self._definition_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            as_of=now,
        )
        if type(value) is not R8MonitoringPolicyDefinition:
            raise TypeError("dedicated R8 monitoring policy definition is unavailable")
        definition = R8MonitoringPolicyDefinition.validated_copy(value)
        policy = definition.policy
        if (
            policy.policy_id != command.policy_id
            or policy.policy_version != command.policy_version
            or not policy.recorded_at <= now < policy.valid_until
        ):
            raise ValueError("R8 monitoring policy identity or validity differs")
        source_value = self._source_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        if type(source_value) is not R8MonitoringPolicySourceReceipt:
            raise TypeError("R8 monitoring policy source receipt is unavailable")
        source = R8MonitoringPolicySourceReceipt.validated_copy(source_value)
        if not (
            source.policy_id == command.policy_id
            and source.policy_version == command.policy_version
            and source.definition_hash == definition.content_hash
            and source.available_at <= now < source.valid_until
            and source.valid_until >= policy.valid_until
        ):
            raise ValueError("R8 monitoring policy source receipt differs")
        return definition, source

    def _require_unchanged(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in current) != self._participant_ids:
            raise R8MonitoringPolicyRegistryUnavailable(
                "R8 monitoring policy registry participant was replaced"
            )
        if _shared_uow(current) != self._expected_uow_key:
            raise R8MonitoringPolicyRegistryUnavailable(
                "R8 monitoring policy registry UoW identity changed"
            )


def _validate_command(command: object) -> None:
    try:
        if type(command) is not RegisterR8MonitoringPolicyCommand:
            raise TypeError("R8 monitoring policy command type differs")
        RegisterR8MonitoringPolicyCommand.__post_init__(command)
        rebuilt = RegisterR8MonitoringPolicyCommand(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyRegistryUnavailable(
            "R8 monitoring policy registration command is malformed"
        ) from error
    if rebuilt != command:
        raise R8MonitoringPolicyRegistryUnavailable(
            "R8 monitoring policy command failed live validation"
        )


def _shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys = {_uow_key(item) for item in participants}
    if len(keys) != 1:
        raise R8MonitoringPolicyRegistryUnavailable(
            "R8 monitoring policy owners use different units of work"
        )
    return next(iter(keys))


def _uow_key(value: _UowBound) -> str:
    key = value.unit_of_work_key
    return _token(key, "R8 monitoring policy UoW key")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "R8MonitoringPolicyDefinitionProvider",
    "R8MonitoringPolicyRegistryClock",
    "R8MonitoringPolicyRegistryUnavailable",
    "R8MonitoringPolicySourceProvider",
    "R8MonitoringPolicyStore",
    "RegisterR8MonitoringPolicy",
    "RegisterR8MonitoringPolicyCommand",
]
