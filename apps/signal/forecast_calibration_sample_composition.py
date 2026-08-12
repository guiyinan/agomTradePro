"""Composition root for Signal-owned R7 calibration sample evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.signal.application.forecast_calibration_sample import (
    ExactForecastCalibrationEntryOwnerProvider,
    ExactForecastCalibrationSampleSourceProvider,
    ForecastCalibrationSampleUnavailable,
    ForecastCalibrationTrustedClock,
    GetExactForecastCalibrationSample,
    RegisterForecastCalibrationSampleDefinition,
    RegisterForecastCalibrationSampleDefinitionCommand,
    RegisterForecastCalibrationSampleReceipt,
    RegisterForecastCalibrationSampleReceiptCommand,
)
from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationSampleDefinition,
    ForecastCalibrationSampleMemberReceipt,
    ForecastCalibrationSampleReceipt,
    ForecastCalibrationSampleSource,
)
from apps.signal.infrastructure.forecast_calibration_entry_provider import (
    DjangoForecastCalibrationEntryOwnerProvider,
)
from apps.signal.infrastructure.forecast_calibration_sample_repository import (
    DjangoForecastCalibrationSampleQueryRepository,
    DjangoForecastCalibrationSampleRepository,
    ForecastCalibrationSampleCorruption,
)
from apps.signal.infrastructure.forecast_realization_models import (
    _activate_forecast_realization_uow,
)


class DjangoForecastCalibrationTrustedClock:
    """Trusted server clock bound to the calibration registry UoW."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""

        return timezone.now()


class UnavailableForecastCalibrationDefinitionRegistrationFacade:
    """Stateless production facade with no definition mutation capability."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterForecastCalibrationSampleDefinitionCommand,
    ) -> ForecastCalibrationSampleDefinition:
        """Class-bound validate an ID-only command, then fail closed."""

        try:
            if type(command) is not RegisterForecastCalibrationSampleDefinitionCommand:
                raise TypeError
            RegisterForecastCalibrationSampleDefinitionCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable(
                "calibration definition command is malformed"
            ) from exc
        raise ForecastCalibrationSampleUnavailable(
            "canonical calibration definition registration is unavailable"
        )


class UnavailableForecastCalibrationReceiptRegistrationFacade:
    """Stateless production facade with no receipt mutation capability."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterForecastCalibrationSampleReceiptCommand,
    ) -> ForecastCalibrationSampleReceipt:
        """Class-bound validate an ID-only command, then fail closed."""

        try:
            if type(command) is not RegisterForecastCalibrationSampleReceiptCommand:
                raise TypeError
            RegisterForecastCalibrationSampleReceiptCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable(
                "calibration receipt command is malformed"
            ) from exc
        raise ForecastCalibrationSampleUnavailable(
            "canonical calibration receipt registration is unavailable"
        )


@dataclass(frozen=True)
class DjangoForecastCalibrationSampleRuntime:
    """Public inert mutation facades plus one exact read-only query."""

    register_definition: UnavailableForecastCalibrationDefinitionRegistrationFacade
    register_receipt: UnavailableForecastCalibrationReceiptRegistrationFacade
    query: GetExactForecastCalibrationSample


@dataclass(frozen=True)
class _DjangoForecastCalibrationSampleTestRuntime:
    """Private owner-injected runtime used for component verification."""

    register_definition: RegisterForecastCalibrationSampleDefinition
    register_receipt: RegisterForecastCalibrationSampleReceipt
    query: GetExactForecastCalibrationSample


def build_django_forecast_calibration_sample_query(
    *,
    using: str = "default",
) -> GetExactForecastCalibrationSample:
    """Build the production read-only exact scope/window/PIT query."""

    return GetExactForecastCalibrationSample(
        DjangoForecastCalibrationSampleQueryRepository(using=using)
    )


def build_django_forecast_calibration_sample_runtime(
    *,
    using: str = "default",
) -> DjangoForecastCalibrationSampleRuntime:
    """Build public inert registration and read-only owner lookup."""

    return DjangoForecastCalibrationSampleRuntime(
        register_definition=UnavailableForecastCalibrationDefinitionRegistrationFacade(),
        register_receipt=UnavailableForecastCalibrationReceiptRegistrationFacade(),
        query=build_django_forecast_calibration_sample_query(using=using),
    )


def _build_django_forecast_calibration_sample_test_runtime(
    *,
    source_provider: ExactForecastCalibrationSampleSourceProvider,
    entry_provider: ExactForecastCalibrationEntryOwnerProvider | None = None,
    clock: ForecastCalibrationTrustedClock | None = None,
    using: str = "default",
) -> _DjangoForecastCalibrationSampleTestRuntime:
    """Bind trusted owner providers to the private atomic append workflow."""

    repository = DjangoForecastCalibrationSampleRepository(using=using)
    ledger_provider = entry_provider or DjangoForecastCalibrationEntryOwnerProvider(using=using)
    server_clock = clock or DjangoForecastCalibrationTrustedClock(using=using)
    expected_key = f"django:{using}"
    participants = (repository, source_provider, ledger_provider, server_clock)
    participant_identity = tuple(participants)

    def require_live_participants() -> None:
        current = (repository, source_provider, ledger_provider, server_clock)
        if any(
            actual is not sealed
            for actual, sealed in zip(current, participant_identity, strict=True)
        ):
            raise ForecastCalibrationSampleUnavailable(
                "calibration owner participant identity changed"
            )
        try:
            keys = tuple(participant.unit_of_work_key for participant in current)
        except Exception as exc:
            raise ForecastCalibrationSampleUnavailable(
                "calibration owner UoW identity is unavailable"
            ) from exc
        if any(type(key) is not str or key != expected_key for key in keys):
            raise ForecastCalibrationSampleUnavailable(
                "calibration owners use different units of work"
            )

    require_live_participants()
    token = object()

    def trusted_now() -> datetime:
        require_live_participants()
        value = server_clock.now()
        require_live_participants()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ForecastCalibrationSampleUnavailable("calibration trusted clock is malformed")
        return value

    def read_source(
        command: RegisterForecastCalibrationSampleDefinitionCommand,
    ) -> ForecastCalibrationSampleSource:
        require_live_participants()
        value = source_provider.get_source(
            sample_id=command.sample_id,
            sample_version=command.sample_version,
            as_of=command.as_of,
        )
        require_live_participants()
        if value is None:
            raise ForecastCalibrationSampleUnavailable(
                "canonical calibration membership source is unavailable"
            )
        try:
            if type(value) is not ForecastCalibrationSampleSource:
                raise ValueError("source type is not canonical")
            source = value.validated_copy()
        except (AttributeError, TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable(
                "canonical calibration membership source is malformed"
            ) from exc
        if (
            source.sample_id != command.sample_id
            or source.sample_version != command.sample_version
            or not source.available_at <= command.as_of < source.valid_until
        ):
            raise ForecastCalibrationSampleUnavailable(
                "canonical calibration membership source does not match command"
            )
        return source

    def read_definition(
        command: RegisterForecastCalibrationSampleReceiptCommand,
    ) -> ForecastCalibrationSampleDefinition:
        require_live_participants()
        definition = repository.get_definition(
            sample_id=command.sample_id,
            sample_version=command.sample_version,
            as_of=command.as_of,
        )
        require_live_participants()
        if definition is None:
            raise ForecastCalibrationSampleUnavailable(
                "canonical calibration definition is unavailable"
            )
        return definition.validated_copy()

    def read_entry(
        expected_entry_id: str,
        *,
        as_of: datetime,
    ) -> ForecastCalibrationEntryOwnerRecord:
        require_live_participants()
        value = ledger_provider.get_entry(entry_id=expected_entry_id, as_of=as_of)
        require_live_participants()
        if value is None:
            raise ForecastCalibrationSampleUnavailable(
                "expected Forecast Ledger entry is unavailable"
            )
        try:
            if type(value) is not ForecastCalibrationEntryOwnerRecord:
                raise ValueError("owner record type is not canonical")
            owner = value.validated_copy()
        except (AttributeError, TypeError, ValueError) as exc:
            raise ForecastCalibrationSampleUnavailable(
                "Forecast Ledger owner record is malformed"
            ) from exc
        if owner.entry_id != expected_entry_id:
            raise ForecastCalibrationSampleUnavailable(
                "Forecast Ledger owner record identity was substituted"
            )
        if owner.entry_recorded_at > as_of:
            raise ForecastCalibrationSampleUnavailable(
                "Forecast Ledger owner record is after the PIT cutoff"
            )
        if owner.outcome_recorded_at is not None and owner.outcome_recorded_at > as_of:
            raise ForecastCalibrationSampleUnavailable(
                "ForecastOutcome owner record is after the PIT cutoff"
            )
        return owner

    class _DefinitionAppender:
        __slots__ = ()

        def register(
            self,
            command: RegisterForecastCalibrationSampleDefinitionCommand,
        ) -> ForecastCalibrationSampleDefinition:
            """Double-read membership and atomically append one definition graph."""

            try:
                require_live_participants()
                with transaction.atomic(using=using):
                    require_live_participants()
                    with _activate_forecast_realization_uow(token):
                        first = read_source(command)
                        second = read_source(command)
                        if first != second:
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration membership changed during exact reread"
                            )
                        registered_at = trusted_now()
                        final_source = read_source(command)
                        if final_source != first or final_source != second:
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration membership changed before append"
                            )
                        candidate = ForecastCalibrationSampleDefinition.create(
                            source=final_source,
                            registered_at=registered_at,
                        )
                        require_live_participants()
                        appended = repository.append_definition(candidate, token=token)
                        require_live_participants()
                        if (
                            type(appended) is not ForecastCalibrationSampleDefinition
                            or appended != candidate
                        ):
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration definition append result is inconsistent"
                            )
                        return appended
            except ForecastCalibrationSampleUnavailable:
                raise
            except (
                ForecastCalibrationSampleCorruption,
                IntegrityError,
                ValidationError,
                TypeError,
                ValueError,
            ) as exc:
                raise ForecastCalibrationSampleUnavailable(
                    "calibration definition append failed closed"
                ) from exc

    class _ReceiptAppender:
        __slots__ = ()

        def register(
            self,
            command: RegisterForecastCalibrationSampleReceiptCommand,
        ) -> ForecastCalibrationSampleReceipt:
            """Double-read definition and every ledger owner before one append."""

            try:
                require_live_participants()
                with transaction.atomic(using=using):
                    require_live_participants()
                    with _activate_forecast_realization_uow(token):
                        first_definition = read_definition(command)
                        first_owners = tuple(
                            read_entry(member.entry_id, as_of=command.as_of)
                            for member in first_definition.source.members
                        )
                        second_owners = tuple(
                            read_entry(member.entry_id, as_of=command.as_of)
                            for member in first_definition.source.members
                        )
                        second_definition = read_definition(command)
                        if first_definition != second_definition or first_owners != second_owners:
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration owner graph changed during exact reread"
                            )
                        recorded_at = trusted_now()
                        if recorded_at < command.as_of:
                            raise ForecastCalibrationSampleUnavailable(
                                "trusted recording clock precedes pit_as_of"
                            )
                        final_definition = read_definition(command)
                        final_owners = tuple(
                            read_entry(member.entry_id, as_of=command.as_of)
                            for member in final_definition.source.members
                        )
                        if (
                            final_definition != first_definition
                            or final_definition != second_definition
                            or final_owners != first_owners
                            or final_owners != second_owners
                        ):
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration owner graph changed before append"
                            )
                        members = tuple(
                            ForecastCalibrationSampleMemberReceipt.from_sources(
                                expected=expected,
                                owner=owner,
                                recorded_at=recorded_at,
                            )
                            for expected, owner in zip(
                                final_definition.source.members,
                                final_owners,
                                strict=True,
                            )
                        )
                        candidate = ForecastCalibrationSampleReceipt.create(
                            definition=final_definition,
                            pit_as_of=command.as_of,
                            recorded_at=recorded_at,
                            members=members,
                        )
                        require_live_participants()
                        appended = repository.append_receipt(candidate, token=token)
                        require_live_participants()
                        if (
                            type(appended) is not ForecastCalibrationSampleReceipt
                            or appended != candidate
                        ):
                            raise ForecastCalibrationSampleUnavailable(
                                "calibration receipt append result is inconsistent"
                            )
                        return appended
            except ForecastCalibrationSampleUnavailable:
                raise
            except (
                ForecastCalibrationSampleCorruption,
                IntegrityError,
                ValidationError,
                TypeError,
                ValueError,
            ) as exc:
                raise ForecastCalibrationSampleUnavailable(
                    "calibration receipt append failed closed"
                ) from exc

    return _DjangoForecastCalibrationSampleTestRuntime(
        register_definition=RegisterForecastCalibrationSampleDefinition(_DefinitionAppender()),
        register_receipt=RegisterForecastCalibrationSampleReceipt(_ReceiptAppender()),
        query=GetExactForecastCalibrationSample(repository),
    )


__all__ = [
    "DjangoForecastCalibrationSampleRuntime",
    "build_django_forecast_calibration_sample_query",
    "build_django_forecast_calibration_sample_runtime",
]
