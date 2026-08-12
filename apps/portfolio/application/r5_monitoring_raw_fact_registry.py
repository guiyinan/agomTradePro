"""ID-only Portfolio registration for canonical R5 monitoring raw facts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactDefinition,
    PortfolioR5MonitoringRawFactSourceReceipt,
)
from apps.portfolio.domain.r5_relative_value_monitoring_contracts import (
    _require_aware,
    _require_token,
)
from apps.portfolio.domain.r5_relative_value_monitoring_facts import (
    R5PostPromotionMonitoringFact,
)


class PortfolioR5MonitoringRawFactUnavailable(RuntimeError):
    """A raw-fact definition, source, clock, or shared UoW is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""


class PortfolioR5MonitoringRawFactDefinitionProvider(_UowBound, Protocol):
    """Canonical Portfolio raw-fact definition source."""

    def get_exact(
        self,
        *,
        fact_id: str,
        fact_version: str,
        as_of: datetime,
    ) -> PortfolioR5MonitoringRawFactDefinition | None:
        """Return one exact raw-fact definition by identity."""


class PortfolioR5MonitoringRawFactSourceProvider(_UowBound, Protocol):
    """Independent source receipt for one raw-fact definition."""

    def get_exact(
        self,
        *,
        fact_id: str,
        fact_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> PortfolioR5MonitoringRawFactSourceReceipt | None:
        """Return a receipt bound to the exact definition."""


class PortfolioR5MonitoringRawFactStore(_UowBound, Protocol):
    """Private append capability for the Portfolio ledger."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared transaction."""

    def append(
        self,
        *,
        definition: PortfolioR5MonitoringRawFactDefinition,
        source: PortfolioR5MonitoringRawFactSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R5PostPromotionMonitoringFact:
        """Append or replay one exact raw-fact winner."""


class PortfolioR5MonitoringRawFactClock(_UowBound, Protocol):
    """Shared-UoW trusted server clock."""

    def now(self) -> datetime:
        """Return one aware server timestamp inside the transaction."""


@dataclass(frozen=True)
class RegisterPortfolioR5MonitoringRawFactCommand:
    """Fact identity only; no raw values, metrics, hashes, or caller clock."""

    fact_id: str
    fact_version: str

    def __post_init__(self) -> None:
        _require_token(self.fact_id, "Portfolio R5 monitoring fact_id")
        _require_token(self.fact_version, "Portfolio R5 monitoring fact_version")


class RegisterPortfolioR5MonitoringRawFact:
    """Double-read and append one exact Portfolio raw fact."""

    def __init__(
        self,
        *,
        definition_provider: PortfolioR5MonitoringRawFactDefinitionProvider,
        source_provider: PortfolioR5MonitoringRawFactSourceProvider,
        store: PortfolioR5MonitoringRawFactStore,
        clock: PortfolioR5MonitoringRawFactClock,
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
        self._expected_uow_key = _capture_shared_uow(self._participants)

    def execute(
        self,
        command: RegisterPortfolioR5MonitoringRawFactCommand,
    ) -> R5PostPromotionMonitoringFact:
        """Register one fact while deriving no value from caller input."""

        _validate_command(command)
        try:
            self._require_bound_participants()
            with self._store.atomic():
                self._require_bound_participants()
                now = self._clock.now()
                _require_aware(now, "Portfolio R5 monitoring server clock")
                first = self._read(command, now=now)
                self._require_bound_participants()
                second = self._read(command, now=now)
                self._require_bound_participants()
                if first != second:
                    raise PortfolioR5MonitoringRawFactUnavailable(
                        "Portfolio R5 monitoring owners changed during registration"
                    )
                definition, source = second
                persisted = self._store.append(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_bound_participants()
                if type(persisted) is not R5PostPromotionMonitoringFact:
                    raise TypeError("Portfolio R5 monitoring store returned another type")
                canonical = persisted.validated_copy()
                if canonical != definition.fact:
                    raise ValueError("Portfolio R5 monitoring winner differs")
                return canonical
        except PortfolioR5MonitoringRawFactUnavailable:
            raise
        except Exception as error:
            raise PortfolioR5MonitoringRawFactUnavailable(
                "Portfolio R5 monitoring raw-fact registration is unavailable"
            ) from error

    def _require_bound_participants(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if any(
            actual is not expected
            for actual, expected in zip(current, self._participants, strict=True)
        ):
            raise PortfolioR5MonitoringRawFactUnavailable(
                "Portfolio R5 monitoring participant was replaced"
            )
        _require_expected_uow(current, self._expected_uow_key)

    def _read(
        self,
        command: RegisterPortfolioR5MonitoringRawFactCommand,
        *,
        now: datetime,
    ) -> tuple[
        PortfolioR5MonitoringRawFactDefinition,
        PortfolioR5MonitoringRawFactSourceReceipt,
    ]:
        value = self._definition_provider.get_exact(
            fact_id=command.fact_id,
            fact_version=command.fact_version,
            as_of=now,
        )
        if type(value) is not PortfolioR5MonitoringRawFactDefinition:
            raise TypeError("Portfolio R5 monitoring fact definition is unavailable")
        definition = value.validated_copy()
        fact = definition.fact
        if (
            fact.fact_id != command.fact_id
            or fact.fact_version != command.fact_version
            or not fact.recorded_at <= now < fact.valid_until
        ):
            raise ValueError("Portfolio R5 monitoring fact identity or window differs")
        source_value = self._source_provider.get_exact(
            fact_id=command.fact_id,
            fact_version=command.fact_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        if type(source_value) is not PortfolioR5MonitoringRawFactSourceReceipt:
            raise TypeError("Portfolio R5 monitoring source receipt is unavailable")
        source = source_value.validated_copy()
        if not (
            source.fact_id == command.fact_id
            and source.fact_version == command.fact_version
            and source.definition_hash == definition.content_hash
            and source.available_at <= now < source.valid_until
        ):
            raise ValueError("Portfolio R5 monitoring source receipt differs")
        return definition, source


def _capture_shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys = tuple(_uow_key(item) for item in participants)
    if len(set(keys)) != 1:
        raise PortfolioR5MonitoringRawFactUnavailable(
            "Portfolio R5 monitoring owners use different unit of work identities"
        )
    return keys[0]


def _require_expected_uow(
    participants: tuple[_UowBound, ...],
    expected_uow_key: str,
) -> None:
    if any(_uow_key(item) != expected_uow_key for item in participants):
        raise PortfolioR5MonitoringRawFactUnavailable(
            "Portfolio R5 monitoring unit of work identity changed"
        )


def _uow_key(value: _UowBound) -> str:
    key = value.unit_of_work_key
    if type(key) is not str or not key.strip():
        raise PortfolioR5MonitoringRawFactUnavailable(
            "Portfolio R5 monitoring unit of work identity is invalid"
        )
    return key


def _validate_command(command: object) -> None:
    try:
        if type(command) is not RegisterPortfolioR5MonitoringRawFactCommand:
            raise TypeError
        RegisterPortfolioR5MonitoringRawFactCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise PortfolioR5MonitoringRawFactUnavailable(
            "Portfolio R5 monitoring raw-fact command is malformed"
        ) from error


__all__ = [
    "PortfolioR5MonitoringRawFactClock",
    "PortfolioR5MonitoringRawFactDefinitionProvider",
    "PortfolioR5MonitoringRawFactSourceProvider",
    "PortfolioR5MonitoringRawFactStore",
    "PortfolioR5MonitoringRawFactUnavailable",
    "RegisterPortfolioR5MonitoringRawFact",
    "RegisterPortfolioR5MonitoringRawFactCommand",
]
