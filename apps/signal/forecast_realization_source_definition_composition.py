"""Composition root for the Signal realization-source definition registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.signal.application.forecast_realization_source_definition import (
    CanonicalForecastRealizationSourceProvider,
    ForecastRealizationSourceDefinitionClock,
    ForecastRealizationSourceDefinitionUnavailable,
    GetExactForecastRealizationSourceDefinition,
    RegisterForecastRealizationSourceDefinition,
    RegisterForecastRealizationSourceDefinitionCommand,
)
from apps.signal.domain.forecast_realization_owner import ForecastRealizationManifestSource
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
    validated_manifest_source_copy,
)
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationSourceDefinitionMemberModel,
    ForecastRealizationSourceDefinitionModel,
    _activate_forecast_realization_uow,
    _claim_forecast_realization_insert,
)
from apps.signal.infrastructure.forecast_realization_source_definition_repository import (
    DjangoForecastRealizationSourceDefinitionRepository,
    ForecastRealizationSourceDefinitionCorruption,
    _definition_from_model,
    _definition_member_model_values,
    _definition_model_values,
)


class DjangoForecastRealizationSourceDefinitionClock:
    """Trusted Django server clock bound to one database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the timezone-aware server timestamp."""

        return timezone.now()


class UnavailableForecastRealizationSourceDefinitionRegistrationFacade:
    """Stateless public registration surface while no canonical owner exists."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterForecastRealizationSourceDefinitionCommand,
    ) -> ForecastRealizationSourceDefinition:
        """Revalidate an ID-only command and fail closed with zero writes."""

        try:
            if type(command) is not RegisterForecastRealizationSourceDefinitionCommand:
                raise TypeError
            RegisterForecastRealizationSourceDefinitionCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition registration command is malformed"
            ) from error
        raise ForecastRealizationSourceDefinitionUnavailable(
            "canonical Forecast Ledger definition provider is unavailable"
        )


@dataclass(frozen=True)
class DjangoForecastRealizationSourceDefinitionRuntime:
    """Public inert registration plus read-only exact registry query."""

    register: UnavailableForecastRealizationSourceDefinitionRegistrationFacade
    query: GetExactForecastRealizationSourceDefinition


@dataclass(frozen=True)
class _DjangoForecastRealizationSourceDefinitionTestRuntime:
    """Private provider-injected runtime retained for component verification."""

    register: RegisterForecastRealizationSourceDefinition
    query: GetExactForecastRealizationSourceDefinition


def build_django_forecast_realization_source_definition_query(
    *, using: str = "default"
) -> GetExactForecastRealizationSourceDefinition:
    """Build the public read-only hash-bound PIT registry query."""

    return GetExactForecastRealizationSourceDefinition(
        DjangoForecastRealizationSourceDefinitionRepository(using=using)
    )


def build_django_forecast_realization_source_definition_runtime(
    *, using: str = "default"
) -> DjangoForecastRealizationSourceDefinitionRuntime:
    """Build inert public registration plus exact read-only lookup."""

    return DjangoForecastRealizationSourceDefinitionRuntime(
        register=UnavailableForecastRealizationSourceDefinitionRegistrationFacade(),
        query=build_django_forecast_realization_source_definition_query(using=using),
    )


def _build_django_forecast_realization_source_definition_test_runtime(
    *,
    source_provider: CanonicalForecastRealizationSourceProvider,
    clock: ForecastRealizationSourceDefinitionClock | None = None,
    using: str = "default",
) -> _DjangoForecastRealizationSourceDefinitionTestRuntime:
    """Bind one canonical definition provider to an append-only test registry."""

    repository = DjangoForecastRealizationSourceDefinitionRepository(using=using)
    server_clock = clock or DjangoForecastRealizationSourceDefinitionClock(using=using)
    expected_key = f"django:{using}"
    try:
        keys = {
            expected_key,
            repository.unit_of_work_key,
            source_provider.unit_of_work_key,
            server_clock.unit_of_work_key,
        }
    except Exception as error:
        raise ForecastRealizationSourceDefinitionUnavailable(
            "source definition UoW identity is unavailable"
        ) from error
    if keys != {expected_key}:
        raise ForecastRealizationSourceDefinitionUnavailable(
            "source definition owners use different UoWs"
        )
    token = object()

    def read_source(
        command: RegisterForecastRealizationSourceDefinitionCommand,
        *,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource:
        value = source_provider.get_exact(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            as_of=as_of,
        )
        if value is None:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "canonical realization source definition is unavailable"
            )
        try:
            source = validated_manifest_source_copy(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "canonical realization source definition is invalid"
            ) from error
        if (
            source.owner_record_id != command.owner_record_id
            or source.owner_record_version != command.owner_record_version
            or not source.available_at <= as_of < source.valid_until
        ):
            raise ForecastRealizationSourceDefinitionUnavailable(
                "canonical realization source identity or clocks are invalid"
            )
        return source

    def existing_by_owner(
        source: ForecastRealizationManifestSource,
    ) -> ForecastRealizationSourceDefinitionModel | None:
        return (
            ForecastRealizationSourceDefinitionModel._default_manager.using(using)
            .select_for_update()
            .prefetch_related("source_members")
            .filter(
                owner_record_id=source.owner_record_id,
                owner_record_version=source.owner_record_version,
            )
            .first()
        )

    def match_existing(
        model: ForecastRealizationSourceDefinitionModel,
        expected_source: ForecastRealizationManifestSource,
    ) -> ForecastRealizationSourceDefinition:
        restored = _definition_from_model(model)
        if restored.source != expected_source:
            raise ForecastRealizationSourceDefinitionUnavailable(
                "source definition owner identity forks to different evidence"
            )
        return restored

    def append_candidate(
        candidate: ForecastRealizationSourceDefinition,
    ) -> ForecastRealizationSourceDefinition:
        existing = existing_by_owner(candidate.source)
        if existing is not None:
            return match_existing(existing, candidate.source)
        definition_values = _definition_model_values(candidate)
        try:
            with transaction.atomic(using=using):
                with _activate_forecast_realization_uow(token):
                    definition_model = ForecastRealizationSourceDefinitionModel(**definition_values)
                    definition_model.full_clean()
                    with _claim_forecast_realization_insert(
                        token=token,
                        model_type=ForecastRealizationSourceDefinitionModel,
                        expected_values=definition_values,
                    ):
                        definition_model.save(force_insert=True, using=using)
                    definition_id = definition_model.pk
                    for member in candidate.source.members:
                        member_values = _definition_member_model_values(
                            member,
                            definition_id=definition_id,
                        )
                        member_model = ForecastRealizationSourceDefinitionMemberModel(
                            **member_values
                        )
                        member_model.full_clean()
                        with _claim_forecast_realization_insert(
                            token=token,
                            model_type=ForecastRealizationSourceDefinitionMemberModel,
                            expected_values=member_values,
                        ):
                            member_model.save(force_insert=True, using=using)
        except (IntegrityError, ValidationError) as error:
            winner = existing_by_owner(candidate.source)
            if winner is None:
                raise ForecastRealizationSourceDefinitionUnavailable(
                    "source definition append failed"
                ) from error
            try:
                return match_existing(winner, candidate.source)
            except ForecastRealizationSourceDefinitionCorruption as corruption:
                raise ForecastRealizationSourceDefinitionUnavailable(
                    "source definition append failed"
                ) from corruption
        return _definition_from_model(definition_model)

    class _ClosureBoundWriter:
        __slots__ = ()

        def register(
            self,
            command: RegisterForecastRealizationSourceDefinitionCommand,
        ) -> ForecastRealizationSourceDefinition:
            """Double-read the canonical graph before one atomic append."""

            try:
                with transaction.atomic(using=using):
                    with _activate_forecast_realization_uow(token):
                        now = server_clock.now()
                        if (
                            not isinstance(now, datetime)
                            or now.tzinfo is None
                            or now.utcoffset() is None
                        ):
                            raise ForecastRealizationSourceDefinitionUnavailable(
                                "source definition server clock is invalid"
                            )
                        first_source = read_source(command, as_of=now)
                        second_source = read_source(command, as_of=now)
                        if first_source != second_source:
                            raise ForecastRealizationSourceDefinitionUnavailable(
                                "canonical source definition changed during reread"
                            )
                        existing = existing_by_owner(second_source)
                        if existing is not None:
                            return match_existing(existing, second_source)
                        candidate = ForecastRealizationSourceDefinition.create(
                            source=second_source,
                            registered_at=now,
                        )
                        return append_candidate(candidate)
            except ForecastRealizationSourceDefinitionUnavailable:
                raise
            except (
                ForecastRealizationSourceDefinitionCorruption,
                TypeError,
                ValueError,
            ) as error:
                raise ForecastRealizationSourceDefinitionUnavailable(
                    "source definition owner reread failed closed"
                ) from error

    return _DjangoForecastRealizationSourceDefinitionTestRuntime(
        register=RegisterForecastRealizationSourceDefinition(_ClosureBoundWriter()),
        query=GetExactForecastRealizationSourceDefinition(repository),
    )


__all__ = [
    "DjangoForecastRealizationSourceDefinitionRuntime",
    "build_django_forecast_realization_source_definition_query",
    "build_django_forecast_realization_source_definition_runtime",
]
