"""Application boundary for the Signal-owned calibration sample registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationSampleDefinition,
    ForecastCalibrationSampleReceipt,
    ForecastCalibrationSampleSource,
)


def _token(value: object, field_name: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} is malformed")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = _token(value, field_name, maximum=64).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return normalized


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class ForecastCalibrationSampleUnavailable(RuntimeError):
    """Raised when canonical calibration evidence cannot be proven exactly."""


@dataclass(frozen=True)
class RegisterForecastCalibrationSampleDefinitionCommand:
    """ID-only command for canonical definition registration."""

    sample_id: str
    sample_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.sample_id, "sample_id")
        _token(self.sample_version, "sample_version")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True)
class RegisterForecastCalibrationSampleReceiptCommand:
    """ID-only command for exact Forecast Ledger outcome reread."""

    sample_id: str
    sample_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.sample_id, "sample_id")
        _token(self.sample_version, "sample_version")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True)
class ExactForecastCalibrationSampleCommand:
    """Exact scope/window/PIT selector for read-only calibration evidence."""

    scope_content_hash: str
    sample_window_start: datetime
    sample_window_end: datetime
    as_of: datetime

    def __post_init__(self) -> None:
        _digest(self.scope_content_hash, "scope_content_hash")
        start = _aware(self.sample_window_start, "sample_window_start")
        end = _aware(self.sample_window_end, "sample_window_end")
        as_of = _aware(self.as_of, "as_of")
        if not start < end <= as_of:
            raise ValueError("query clocks must satisfy window_start < window_end <= as_of")


class ForecastCalibrationSampleDefinitionWriter(Protocol):
    """Owner registration port hidden behind an Application use case."""

    def register(
        self,
        command: RegisterForecastCalibrationSampleDefinitionCommand,
    ) -> ForecastCalibrationSampleDefinition:
        """Register one canonical definition from owner data."""


class ExactForecastCalibrationSampleSourceProvider(Protocol):
    """Canonical Forecast Ledger membership source used only by owner workflow."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def get_source(
        self,
        *,
        sample_id: str,
        sample_version: str,
        as_of: datetime,
    ) -> ForecastCalibrationSampleSource | None:
        """Return an outcome-free exact membership definition."""


class ExactForecastCalibrationEntryOwnerProvider(Protocol):
    """Exact immutable Forecast Ledger entry/outcome reread port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def get_entry(
        self,
        *,
        entry_id: str,
        as_of: datetime,
    ) -> ForecastCalibrationEntryOwnerRecord | None:
        """Return a ledger member, including explicit unresolved state."""


class ForecastCalibrationTrustedClock(Protocol):
    """Trusted recording clock unavailable to public callers."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def now(self) -> datetime:
        """Return the current timezone-aware owner recording time."""


class ForecastCalibrationSampleReceiptWriter(Protocol):
    """Owner receipt port hidden behind an Application use case."""

    def register(
        self,
        command: RegisterForecastCalibrationSampleReceiptCommand,
    ) -> ForecastCalibrationSampleReceipt:
        """Reread owner facts and append one exhaustive receipt."""


class ExactForecastCalibrationSampleRepository(Protocol):
    """Read-only exact PIT repository port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction identity."""

    def get_for_scope(
        self,
        *,
        scope_content_hash: str,
        sample_window_start: datetime,
        sample_window_end: datetime,
        as_of: datetime,
    ) -> ForecastCalibrationSampleReceipt | None:
        """Return one unique valid receipt or ``None`` when no owner data exists."""


def _validate_definition_command(
    command: object,
) -> RegisterForecastCalibrationSampleDefinitionCommand:
    if type(command) is not RegisterForecastCalibrationSampleDefinitionCommand:
        raise ForecastCalibrationSampleUnavailable("malformed definition command")
    assert isinstance(command, RegisterForecastCalibrationSampleDefinitionCommand)
    try:
        RegisterForecastCalibrationSampleDefinitionCommand.__post_init__(command)
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleUnavailable("malformed definition command") from exc
    return command


def _validate_receipt_command(
    command: object,
) -> RegisterForecastCalibrationSampleReceiptCommand:
    if type(command) is not RegisterForecastCalibrationSampleReceiptCommand:
        raise ForecastCalibrationSampleUnavailable("malformed receipt command")
    assert isinstance(command, RegisterForecastCalibrationSampleReceiptCommand)
    try:
        RegisterForecastCalibrationSampleReceiptCommand.__post_init__(command)
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleUnavailable("malformed receipt command") from exc
    return command


def _validate_query_command(command: object) -> ExactForecastCalibrationSampleCommand:
    if type(command) is not ExactForecastCalibrationSampleCommand:
        raise ForecastCalibrationSampleUnavailable("malformed calibration query")
    assert isinstance(command, ExactForecastCalibrationSampleCommand)
    try:
        ExactForecastCalibrationSampleCommand.__post_init__(command)
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleUnavailable("malformed calibration query") from exc
    return command


class RegisterForecastCalibrationSampleDefinition:
    """Register one definition after enforcing an exact public command type."""

    def __init__(self, writer: ForecastCalibrationSampleDefinitionWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterForecastCalibrationSampleDefinitionCommand,
    ) -> ForecastCalibrationSampleDefinition:
        """Execute ID-only registration and validate the returned owner graph."""

        validated = _validate_definition_command(command)
        try:
            result = self._writer.register(validated)
            if type(result) is not ForecastCalibrationSampleDefinition:
                raise ValueError("writer returned a non-canonical definition")
            copy = result.validated_copy()
        except (TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable("malformed definition owner result") from exc
        if (
            copy.source.sample_id != validated.sample_id
            or copy.source.sample_version != validated.sample_version
            or copy.source.available_at > validated.as_of
        ):
            raise ForecastCalibrationSampleUnavailable(
                "definition owner result does not match command"
            )
        return copy


class RegisterForecastCalibrationSampleReceipt:
    """Append one receipt after enforcing an exact public command type."""

    def __init__(self, writer: ForecastCalibrationSampleReceiptWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterForecastCalibrationSampleReceiptCommand,
    ) -> ForecastCalibrationSampleReceipt:
        """Execute ID-only reread and validate the returned owner graph."""

        validated = _validate_receipt_command(command)
        try:
            result = self._writer.register(validated)
            if type(result) is not ForecastCalibrationSampleReceipt:
                raise ValueError("writer returned a non-canonical receipt")
            copy = result.validated_copy()
        except (TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable("malformed receipt owner result") from exc
        source = copy.definition.source
        if (
            source.sample_id != validated.sample_id
            or source.sample_version != validated.sample_version
            or copy.pit_as_of != validated.as_of
        ):
            raise ForecastCalibrationSampleUnavailable(
                "receipt owner result does not match command"
            )
        return copy


class GetExactForecastCalibrationSample:
    """Resolve one exact scope/window/PIT receipt without synthesis."""

    def __init__(self, repository: ExactForecastCalibrationSampleRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the owner registry's shared transaction identity."""

        return self._repository.unit_of_work_key

    def execute(
        self,
        command: ExactForecastCalibrationSampleCommand,
    ) -> ForecastCalibrationSampleReceipt | None:
        """Return a validated receipt or preserve blocking ``None``."""

        validated = _validate_query_command(command)
        result = self._repository.get_for_scope(
            scope_content_hash=validated.scope_content_hash,
            sample_window_start=validated.sample_window_start,
            sample_window_end=validated.sample_window_end,
            as_of=validated.as_of,
        )
        if result is None:
            return None
        try:
            if type(result) is not ForecastCalibrationSampleReceipt:
                raise ValueError("repository returned a non-canonical receipt")
            copy = result.validated_copy()
        except (TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable(
                "malformed calibration owner result"
            ) from exc
        source = copy.definition.source
        if (
            source.scope_content_hash != validated.scope_content_hash
            or source.sample_window_start != validated.sample_window_start
            or source.sample_window_end != validated.sample_window_end
            or copy.pit_as_of > validated.as_of
            or copy.recorded_at > validated.as_of
            or source.valid_until <= validated.as_of
        ):
            raise ForecastCalibrationSampleUnavailable(
                "calibration owner result does not match exact selectors"
            )
        return copy
