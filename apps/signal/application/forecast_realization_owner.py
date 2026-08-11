"""ID-only Application ports for Signal-owned R7 realization manifests."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from re import fullmatch
from typing import Protocol

from apps.signal.domain.forecast_realization_owner import (
    ForecastOutcomeOwnerRecord,
    ForecastRealizationManifest,
    ForecastRealizationManifestSource,
)


class ForecastRealizationOwnerUnavailable(RuntimeError):
    """One exact owner source or append capability is unavailable."""


def _require_token(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 300
        or any(character.isspace() for character in value)
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


class ForecastRealizationManifestSourceProvider(_UnitOfWorkBound, Protocol):
    """Outcome-free canonical membership source used by the ID-only writer."""

    def get_exact(
        self,
        *,
        owner_record_id: str,
        owner_record_version: str,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource | None:
        """Return one exact source manifest without raw outcome values."""


class ForecastOutcomeOwnerProvider(_UnitOfWorkBound, Protocol):
    """Exact read port for an existing immutable ForecastOutcome row."""

    def get_exact(
        self,
        *,
        entry_id: str,
        as_of: datetime,
    ) -> ForecastOutcomeOwnerRecord | None:
        """Return an exact scenario outcome or ``None`` when it is absent."""


class ForecastRealizationManifestRepository(_UnitOfWorkBound, Protocol):
    """Read-only exact PIT repository for append-only owner manifests."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_result_hash: str,
        period_id: str,
        period_version: str,
        expected_period_hash: str,
        as_of: datetime,
    ) -> ForecastRealizationManifest | None:
        """Return one exact manifest; never latest, current, or a list."""


class ForecastRealizationManifestWriter(Protocol):
    """Private persistence boundary exposed only through an ID-only use case."""

    def append(
        self,
        command: AppendForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest:
        """Reread owner sources and append one manifest atomically."""


class ForecastRealizationClock(_UnitOfWorkBound, Protocol):
    """Trusted server clock participating in the same owner transaction."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class ForecastRealizationUnitOfWork(_UnitOfWorkBound, Protocol):
    """Shared transaction for metadata, outcome, and receipt operations."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one atomic transaction."""


@dataclass(frozen=True)
class AppendForecastRealizationManifestCommand:
    """Caller-safe write selector with no outcomes, clocks, or probabilities."""

    owner_record_id: str
    owner_record_version: str

    def __post_init__(self) -> None:
        _require_token(self.owner_record_id, "owner_record_id")
        _require_token(self.owner_record_version, "owner_record_version")


@dataclass(frozen=True)
class ExactForecastRealizationManifestCommand:
    """Hash-bound exact PIT selector for one result-period owner record."""

    result_id: str
    result_version: str
    expected_result_hash: str
    period_id: str
    period_version: str
    expected_period_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.result_id, "result_id")
        _require_token(self.result_version, "result_version")
        _require_hash(self.expected_result_hash, "expected_result_hash")
        _require_token(self.period_id, "period_id")
        _require_token(self.period_version, "period_version")
        _require_hash(self.expected_period_hash, "expected_period_hash")
        _require_aware(self.as_of, "as_of")


class AppendForecastRealizationManifest:
    """Invoke the closure-bound canonical writer with an ID-only command."""

    def __init__(self, writer: ForecastRealizationManifestWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: AppendForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest:
        """Validate the selector before any source read or write."""

        if type(command) is not AppendForecastRealizationManifestCommand:
            raise ForecastRealizationOwnerUnavailable("realization manifest command is malformed")
        AppendForecastRealizationManifestCommand.__post_init__(command)
        value = self._writer.append(command)
        if type(value) is not ForecastRealizationManifest:
            raise ForecastRealizationOwnerUnavailable(
                "realization manifest writer returned an invalid Domain type"
            )
        return ForecastRealizationManifest.validated_copy(value)


class GetExactForecastRealizationManifest:
    """Expose only exact, hash-bound PIT reads from the Signal owner ledger."""

    def __init__(self, repository: ForecastRealizationManifestRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact repository transaction identity."""

        return self._repository.unit_of_work_key

    def execute(
        self,
        command: ExactForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest | None:
        """Return an exact manifest or preserve absence as ``None``."""

        if type(command) is not ExactForecastRealizationManifestCommand:
            raise ForecastRealizationOwnerUnavailable(
                "realization manifest query command is malformed"
            )
        ExactForecastRealizationManifestCommand.__post_init__(command)
        value = self._repository.get_exact(
            result_id=command.result_id,
            result_version=command.result_version,
            expected_result_hash=command.expected_result_hash,
            period_id=command.period_id,
            period_version=command.period_version,
            expected_period_hash=command.expected_period_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        if type(value) is not ForecastRealizationManifest:
            raise ForecastRealizationOwnerUnavailable(
                "realization manifest repository returned an invalid Domain type"
            )
        manifest = ForecastRealizationManifest.validated_copy(value)
        if (
            manifest.result_id != command.result_id
            or manifest.result_version != command.result_version
            or manifest.result_hash != command.expected_result_hash
            or manifest.period_id != command.period_id
            or manifest.period_version != command.period_version
            or manifest.period_hash != command.expected_period_hash
            or not manifest.recorded_at <= manifest.pit_as_of <= command.as_of
            or command.as_of >= manifest.valid_until
        ):
            return None
        return manifest


__all__ = [
    "AppendForecastRealizationManifest",
    "AppendForecastRealizationManifestCommand",
    "ExactForecastRealizationManifestCommand",
    "ForecastOutcomeOwnerProvider",
    "ForecastRealizationClock",
    "ForecastRealizationManifestRepository",
    "ForecastRealizationManifestSourceProvider",
    "ForecastRealizationOwnerUnavailable",
    "ForecastRealizationUnitOfWork",
    "GetExactForecastRealizationManifest",
]
