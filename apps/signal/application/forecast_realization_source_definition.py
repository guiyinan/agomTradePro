"""ID-only Application ports for the Signal realization-source registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from typing import Protocol

from apps.signal.domain.forecast_realization_owner import ForecastRealizationManifestSource
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
)


class ForecastRealizationSourceDefinitionUnavailable(RuntimeError):
    """The exact canonical source or registry capability is unavailable."""


def _require_token(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 300
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction identity."""


class CanonicalForecastRealizationSourceProvider(_UnitOfWorkBound, Protocol):
    """Canonical Forecast Ledger result/calendar/period definition read port."""

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        """Return one complete outcome-free owner source at an exact cutoff."""


class ForecastRealizationSourceDefinitionClock(_UnitOfWorkBound, Protocol):
    """Trusted server clock bound to the registry transaction."""

    def now(self) -> datetime:
        """Return the timezone-aware database registration time."""


class ForecastRealizationSourceDefinitionRepository(_UnitOfWorkBound, Protocol):
    """Read-only hash-bound PIT definition registry."""

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> ForecastRealizationSourceDefinition | None:
        """Return one exact live definition or preserve absence as ``None``."""


class ForecastRealizationSourceDefinitionWriter(Protocol):
    """Private ID-only registry append boundary."""

    def register(
        self,
        command: RegisterForecastRealizationSourceDefinitionCommand,
    ) -> ForecastRealizationSourceDefinition:
        """Reread canonical definitions and append one stable graph."""


@dataclass(frozen=True)
class RegisterForecastRealizationSourceDefinitionCommand:
    """Caller-safe owner selector with no source payload or clocks."""

    owner_record_id: str
    owner_record_version: str

    def __post_init__(self) -> None:
        _require_token(self.owner_record_id, "owner_record_id")
        _require_token(self.owner_record_version, "owner_record_version")


@dataclass(frozen=True)
class ExactForecastRealizationSourceDefinitionCommand:
    """Hash-bound exact PIT selector for one versioned definition."""

    owner_record_id: str
    owner_record_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.owner_record_id, "owner_record_id")
        _require_token(self.owner_record_version, "owner_record_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


class RegisterForecastRealizationSourceDefinition:
    """Invoke a closure-bound owner writer using only source identity."""

    def __init__(self, writer: ForecastRealizationSourceDefinitionWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterForecastRealizationSourceDefinitionCommand,
    ) -> ForecastRealizationSourceDefinition:
        """Class-bound validate before the private writer can read or append."""

        if type(command) is not RegisterForecastRealizationSourceDefinitionCommand:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition registration command is malformed"
            )
        try:
            RegisterForecastRealizationSourceDefinitionCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition registration command is malformed"
            ) from error
        value = self._writer.register(command)
        if type(value) is not ForecastRealizationSourceDefinition:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition writer returned an invalid Domain type"
            )
        definition = value.validated_copy()
        if (
            definition.source.owner_record_id != command.owner_record_id
            or definition.source.owner_record_version != command.owner_record_version
        ):
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition writer returned a different owner identity"
            )
        return definition


class GetExactForecastRealizationSourceDefinition:
    """Expose only hash-bound exact PIT reads from the Signal registry."""

    def __init__(self, repository: ForecastRealizationSourceDefinitionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact repository transaction identity."""

        return self._repository.unit_of_work_key

    def execute(
        self,
        command: ExactForecastRealizationSourceDefinitionCommand,
    ) -> ForecastRealizationSourceDefinition | None:
        """Return one exact live definition or preserve absence as ``None``."""

        if type(command) is not ExactForecastRealizationSourceDefinitionCommand:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition query command is malformed"
            )
        try:
            ExactForecastRealizationSourceDefinitionCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition query command is malformed"
            ) from error
        value = self._repository.get_exact(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        if type(value) is not ForecastRealizationSourceDefinition:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition repository returned an invalid Domain type"
            )
        definition = value.validated_copy()
        if (
            definition.source.owner_record_id != command.owner_record_id
            or definition.source.owner_record_version != command.owner_record_version
            or definition.content_hash != command.expected_content_hash
            or definition.registered_at > command.as_of
            or command.as_of >= definition.source.valid_until
        ):
            return None
        return definition


__all__ = [
    "CanonicalForecastRealizationSourceProvider",
    "ExactForecastRealizationSourceDefinitionCommand",
    "ForecastRealizationSourceDefinitionClock",
    "ForecastRealizationSourceDefinitionRepository",
    "ForecastRealizationSourceDefinitionUnavailable",
    "GetExactForecastRealizationSourceDefinition",
    "RegisterForecastRealizationSourceDefinition",
    "RegisterForecastRealizationSourceDefinitionCommand",
]
