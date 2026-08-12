"""ID-only registration for Portfolio-owned raw R8 monitoring feedback."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedback,
    PortfolioR8MonitoringFeedbackDefinition,
    PortfolioR8MonitoringFeedbackSourceReceipt,
)


class PortfolioR8MonitoringFeedbackRegistryUnavailable(RuntimeError):
    """A feedback definition, source, trusted clock, or UoW is unavailable."""


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""


class PortfolioR8MonitoringFeedbackDefinitionProvider(_UowBound, Protocol):
    """Independent raw feedback definition source."""

    def get_exact(
        self,
        *,
        feedback_id: str,
        feedback_version: str,
        as_of: datetime,
    ) -> PortfolioR8MonitoringFeedbackDefinition | None:
        """Return one exact raw feedback definition."""


class PortfolioR8MonitoringFeedbackSourceProvider(_UowBound, Protocol):
    """Independent receipt source for an exact feedback definition."""

    def get_exact(
        self,
        *,
        feedback_id: str,
        feedback_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> PortfolioR8MonitoringFeedbackSourceReceipt | None:
        """Return the source receipt bound to one definition."""


class PortfolioR8MonitoringFeedbackStore(_UowBound, Protocol):
    """Private append capability retained outside public composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared Portfolio transaction."""

    def append(
        self,
        *,
        definition: PortfolioR8MonitoringFeedbackDefinition,
        source: PortfolioR8MonitoringFeedbackSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> PortfolioR8MonitoringFeedback:
        """Append or replay one exact raw feedback winner."""


class PortfolioR8MonitoringFeedbackRegistryClock(_UowBound, Protocol):
    """Trusted Portfolio server clock."""

    def now(self) -> datetime:
        """Return a timezone-aware owner timestamp."""


@dataclass(frozen=True)
class RegisterPortfolioR8MonitoringFeedbackCommand:
    """Feedback identity only; no raw values, source objects, or clocks."""

    feedback_id: str
    feedback_version: str

    def __post_init__(self) -> None:
        _token(self.feedback_id, "Portfolio R8 feedback_id")
        _token(self.feedback_version, "Portfolio R8 feedback_version")


class RegisterPortfolioR8MonitoringFeedback:
    """Double-read exact raw owners before one trusted-clock append."""

    def __init__(
        self,
        *,
        definition_provider: PortfolioR8MonitoringFeedbackDefinitionProvider,
        source_provider: PortfolioR8MonitoringFeedbackSourceProvider,
        store: PortfolioR8MonitoringFeedbackStore,
        clock: PortfolioR8MonitoringFeedbackRegistryClock,
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
        command: RegisterPortfolioR8MonitoringFeedbackCommand,
    ) -> PortfolioR8MonitoringFeedback:
        """Append only a stable exact graph; every failure remains zero-write."""

        try:
            _validate_command(command)
            self._require_unchanged()
            with self._store.atomic():
                self._require_unchanged()
                now = self._clock.now()
                _aware(now, "Portfolio R8 feedback trusted clock")
                first = self._read(command, now=now)
                self._require_unchanged()
                second = self._read(command, now=now)
                self._require_unchanged()
                if first != second:
                    raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
                        "Portfolio R8 feedback owner graph changed during reread"
                    )
                definition, source = second
                result = self._store.append(
                    definition=definition,
                    source=source,
                    ledger_recorded_at=now,
                )
                self._require_unchanged()
                if type(result) is not PortfolioR8MonitoringFeedback:
                    raise TypeError("Portfolio R8 feedback store returned another type")
                canonical = PortfolioR8MonitoringFeedback.validated_copy(result)
                if canonical != definition.feedback:
                    raise ValueError("Portfolio R8 feedback winner differs")
                return canonical
        except PortfolioR8MonitoringFeedbackRegistryUnavailable:
            raise
        except Exception as error:
            raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
                "Portfolio R8 monitoring feedback registration is unavailable"
            ) from error

    def _read(
        self,
        command: RegisterPortfolioR8MonitoringFeedbackCommand,
        *,
        now: datetime,
    ) -> tuple[
        PortfolioR8MonitoringFeedbackDefinition,
        PortfolioR8MonitoringFeedbackSourceReceipt,
    ]:
        value = self._definition_provider.get_exact(
            feedback_id=command.feedback_id,
            feedback_version=command.feedback_version,
            as_of=now,
        )
        if type(value) is not PortfolioR8MonitoringFeedbackDefinition:
            raise TypeError("Portfolio R8 feedback definition is unavailable")
        definition = PortfolioR8MonitoringFeedbackDefinition.validated_copy(value)
        feedback = definition.feedback
        if (
            feedback.feedback_id != command.feedback_id
            or feedback.feedback_version != command.feedback_version
            or not feedback.available_at <= now < feedback.valid_until
        ):
            raise ValueError("Portfolio R8 feedback identity or validity differs")
        source_value = self._source_provider.get_exact(
            feedback_id=command.feedback_id,
            feedback_version=command.feedback_version,
            definition_hash=definition.content_hash,
            as_of=now,
        )
        if type(source_value) is not PortfolioR8MonitoringFeedbackSourceReceipt:
            raise TypeError("Portfolio R8 feedback source receipt is unavailable")
        source = PortfolioR8MonitoringFeedbackSourceReceipt.validated_copy(source_value)
        if not (
            source.feedback_id == command.feedback_id
            and source.feedback_version == command.feedback_version
            and source.definition_hash == definition.content_hash
            and source.available_at <= now < source.valid_until
            and source.valid_until >= feedback.valid_until
        ):
            raise ValueError("Portfolio R8 feedback source receipt differs")
        return definition, source

    def _require_unchanged(self) -> None:
        current: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._source_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in current) != self._participant_ids:
            raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
                "Portfolio R8 feedback registry participant was replaced"
            )
        if _shared_uow(current) != self._expected_uow_key:
            raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
                "Portfolio R8 feedback registry UoW identity changed"
            )


def _validate_command(command: object) -> None:
    try:
        if type(command) is not RegisterPortfolioR8MonitoringFeedbackCommand:
            raise TypeError("Portfolio R8 feedback command type differs")
        RegisterPortfolioR8MonitoringFeedbackCommand.__post_init__(command)
        rebuilt = RegisterPortfolioR8MonitoringFeedbackCommand(
            feedback_id=command.feedback_id,
            feedback_version=command.feedback_version,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
            "Portfolio R8 feedback registration command is malformed"
        ) from error
    if rebuilt != command:
        raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
            "Portfolio R8 feedback command failed live validation"
        )


def _shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys = {_uow_key(item) for item in participants}
    if len(keys) != 1:
        raise PortfolioR8MonitoringFeedbackRegistryUnavailable(
            "Portfolio R8 feedback owners use different units of work"
        )
    return next(iter(keys))


def _uow_key(value: _UowBound) -> str:
    return _token(value.unit_of_work_key, "Portfolio R8 feedback UoW key")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "PortfolioR8MonitoringFeedbackDefinitionProvider",
    "PortfolioR8MonitoringFeedbackRegistryClock",
    "PortfolioR8MonitoringFeedbackRegistryUnavailable",
    "PortfolioR8MonitoringFeedbackSourceProvider",
    "PortfolioR8MonitoringFeedbackStore",
    "RegisterPortfolioR8MonitoringFeedback",
    "RegisterPortfolioR8MonitoringFeedbackCommand",
]
