"""ID-only registration for the Research R2 explanatory-trial policy ledger."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MarketStructureTrialPolicy,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
    validated_r2_trial_policy,
)


class R2TrialPolicyRegistryUnavailable(RuntimeError):
    """An exact owner definition, UoW, clock, or append result is unavailable."""


class R2TrialPolicyRegistryConflict(R2TrialPolicyRegistryUnavailable):
    """One immutable identity already has another first winner."""


class R2TrialPolicyRegistryCorruption(R2TrialPolicyRegistryUnavailable):
    """Persisted R2 policy evidence is structurally inconsistent."""


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one exact shared transaction identity."""


class ExactR2TrialPolicyDefinitionProvider(_UowBound, Protocol):
    """Canonical Research owner query for a complete Phase-A policy."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        """Return one exact versioned owner definition at the PIT cutoff."""


class R2TrialPolicyRegistryStore(_UowBound, Protocol):
    """Private append-only capability retained by test composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared registration transaction."""

    def append(
        self, record: PersistedR2MarketStructureTrialPolicy
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Append or return the exact immutable winner."""


class R2TrialPolicyRegistryClock(_UowBound, Protocol):
    """Trusted server clock for the ledger recording time."""

    def now(self) -> datetime:
        """Return one exact timezone-aware timestamp."""


@dataclass(frozen=True)
class RegisterR2MarketStructureTrialPolicyCommand:
    """ID-only selector; no caller policy, hash, clock, or authorization."""

    policy_id: str
    policy_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "policy_id")
        _require_token(self.policy_version, "policy_version")
        _require_aware(self.as_of, "as_of")


class RegisterR2MarketStructureTrialPolicy:
    """Double-read one owner definition and server-stamp it before selection."""

    def __init__(
        self,
        *,
        definition_provider: ExactR2TrialPolicyDefinitionProvider,
        store: R2TrialPolicyRegistryStore,
        clock: R2TrialPolicyRegistryClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._store = store
        self._clock = clock
        self._participant_ids = tuple(id(item) for item in (definition_provider, store, clock))
        try:
            self._expected_uow_key = _shared_uow_key((definition_provider, store, clock))
            self._require_live_participants()
        except R2TrialPolicyRegistryUnavailable:
            raise
        except Exception as error:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial policy registry dependencies are unavailable"
            ) from error

    def execute(
        self, command: RegisterR2MarketStructureTrialPolicyCommand
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Append one exact owner-backed policy or fail atomically without writes."""

        try:
            if type(command) is not RegisterR2MarketStructureTrialPolicyCommand:
                raise TypeError("registration command type differs")
            RegisterR2MarketStructureTrialPolicyCommand.__post_init__(command)
            self._require_live_participants()
            with self._store.atomic():
                self._require_live_participants()
                ledger_recorded_at = self._clock.now()
                _require_aware(ledger_recorded_at, "clock.now")
                self._require_live_participants()
                if command.as_of > ledger_recorded_at:
                    raise R2TrialPolicyRegistryUnavailable("future R2 policy registration cutoff")
                first = self._read_owner(command, as_of=command.as_of)
                self._require_live_participants()
                second = self._read_owner(command, as_of=ledger_recorded_at)
                self._require_live_participants()
                if first != second:
                    raise R2TrialPolicyRegistryUnavailable(
                        "R2 trial policy owner definition changed"
                    )
                if first.registered_at > command.as_of:
                    raise R2TrialPolicyRegistryUnavailable(
                        "R2 trial policy was not owner-known at the cutoff"
                    )
                record = PersistedR2MarketStructureTrialPolicy.create(
                    policy=second,
                    ledger_recorded_at=ledger_recorded_at,
                )
                self._require_live_participants()
                result = self._store.append(record)
                self._require_live_participants()
                if type(result) is not PersistedR2MarketStructureTrialPolicy:
                    raise R2TrialPolicyRegistryUnavailable(
                        "R2 trial policy store returned another type"
                    )
                result = result.validated_copy()
                if result != record:
                    raise R2TrialPolicyRegistryUnavailable(
                        "R2 trial policy store substituted the receipt"
                    )
                return result
        except (
            R2TrialPolicyRegistryConflict,
            R2TrialPolicyRegistryCorruption,
            R2TrialPolicyRegistryUnavailable,
        ):
            raise
        except Exception as error:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial policy registration is unavailable"
            ) from error

    def _read_owner(
        self,
        command: RegisterR2MarketStructureTrialPolicyCommand,
        *,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy:
        policy = self._definition_provider.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            as_of=as_of,
        )
        if type(policy) is not R2MarketStructureTrialPolicy:
            raise R2TrialPolicyRegistryUnavailable(
                "exact R2 trial policy owner definition is unavailable"
            )
        validated = validated_r2_trial_policy(policy)
        if (validated.policy_id, validated.policy_version) != (
            command.policy_id,
            command.policy_version,
        ):
            raise R2TrialPolicyRegistryUnavailable("R2 trial policy owner identity was substituted")
        return validated

    def _require_live_participants(self) -> None:
        participants: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in participants) != self._participant_ids:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial policy registry participant was replaced"
            )
        if _shared_uow_key(participants) != self._expected_uow_key:
            raise R2TrialPolicyRegistryUnavailable("R2 trial policy registry UoW changed")


def _shared_uow_key(participants: tuple[_UowBound, ...]) -> str:
    keys: list[str] = []
    for participant in participants:
        key = participant.unit_of_work_key
        if type(key) is not str or not key.strip() or len(key) > 192:
            raise R2TrialPolicyRegistryUnavailable("R2 trial policy registry UoW key is invalid")
        keys.append(key)
    if len(set(keys)) != 1:
        raise R2TrialPolicyRegistryUnavailable("R2 trial policy registry requires one shared UoW")
    return keys[0]


__all__ = [
    "ExactR2TrialPolicyDefinitionProvider",
    "R2TrialPolicyRegistryClock",
    "R2TrialPolicyRegistryConflict",
    "R2TrialPolicyRegistryCorruption",
    "R2TrialPolicyRegistryStore",
    "R2TrialPolicyRegistryUnavailable",
    "RegisterR2MarketStructureTrialPolicy",
    "RegisterR2MarketStructureTrialPolicyCommand",
]
