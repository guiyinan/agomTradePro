"""Concrete ID-only composition for Signal R7 realization owner receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.signal.application.forecast_realization_owner import (
    AppendForecastRealizationManifest,
    AppendForecastRealizationManifestCommand,
    ForecastRealizationClock,
    ForecastRealizationOwnerUnavailable,
    GetExactForecastRealizationManifest,
)
from apps.signal.domain.forecast_realization_owner import (
    ForecastOutcomeOwnerRecord,
    ForecastRealizationManifest,
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
)
from apps.signal.infrastructure.forecast_realization_models import (
    ForecastRealizationManifestModel,
    ForecastRealizationReceiptModel,
    _activate_forecast_realization_uow,
    _claim_forecast_realization_insert,
)
from apps.signal.infrastructure.forecast_realization_repository import (
    DjangoForecastOutcomeOwnerProvider,
    DjangoForecastRealizationManifestRepository,
    ForecastRealizationOwnerCorruption,
    _manifest_from_model,
    _manifest_model_values,
    _receipt_model_values,
)
from apps.signal.infrastructure.forecast_realization_source_definition_repository import (
    DjangoForecastRealizationManifestSourceRegistryProvider,
)


class DjangoForecastRealizationClock:
    """Django server clock bound to one database alias."""

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


@dataclass(frozen=True)
class DjangoForecastRealizationOwnerRuntime:
    """Public inert append plus exact read; no mutable owner capability."""

    append: UnavailableForecastRealizationAppendFacade
    query: GetExactForecastRealizationManifest


class UnavailableForecastRealizationAppendFacade:
    """Stateless production append surface while canonical metadata is absent."""

    __slots__ = ()

    def execute(
        self,
        command: AppendForecastRealizationManifestCommand,
    ) -> ForecastRealizationManifest:
        """Revalidate command shape, then fail closed without touching storage."""

        try:
            if type(command) is not AppendForecastRealizationManifestCommand:
                raise TypeError
            AppendForecastRealizationManifestCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastRealizationOwnerUnavailable(
                "forecast realization append command is malformed"
            ) from error
        raise ForecastRealizationOwnerUnavailable(
            "forecast realization canonical source provider is unavailable"
        )


@dataclass(frozen=True)
class _DjangoForecastRealizationOwnerTestRuntime:
    """Private injectable runtime retained only for component verification."""

    append: AppendForecastRealizationManifest
    query: GetExactForecastRealizationManifest


def _canonical_member_source(
    value: ForecastRealizationMemberSource,
) -> ForecastRealizationMemberSource:
    if type(value) is not ForecastRealizationMemberSource:
        raise ForecastRealizationOwnerUnavailable(
            "realization member source has an invalid Domain type"
        )
    ForecastRealizationMemberSource.__post_init__(value)
    rebuilt = ForecastRealizationMemberSource.create(
        entry_id=value.entry_id,
        observation_id=value.observation_id,
        observation_version=value.observation_version,
        expected_observation_hash=value.expected_observation_hash,
        forecast_group_id=value.forecast_group_id,
        pit_manifest_version=value.pit_manifest_version,
        pit_manifest_hash=value.pit_manifest_hash,
        censoring_rule_version=value.censoring_rule_version,
        outcome_evidence_valid_until=value.outcome_evidence_valid_until,
        available_at=value.available_at,
        evidence_ref=value.evidence_ref,
    )
    if rebuilt != value:
        raise ForecastRealizationOwnerUnavailable("realization member source is noncanonical")
    return rebuilt


def _canonical_source(
    value: ForecastRealizationManifestSource,
) -> ForecastRealizationManifestSource:
    if type(value) is not ForecastRealizationManifestSource:
        raise ForecastRealizationOwnerUnavailable(
            "realization manifest source has an invalid Domain type"
        )
    ForecastRealizationManifestSource.__post_init__(value)
    members = tuple(_canonical_member_source(item) for item in value.members)
    rebuilt = ForecastRealizationManifestSource.create(
        owner_record_id=value.owner_record_id,
        owner_record_version=value.owner_record_version,
        result_id=value.result_id,
        result_version=value.result_version,
        result_hash=value.result_hash,
        calendar_id=value.calendar_id,
        calendar_version=value.calendar_version,
        period_id=value.period_id,
        period_version=value.period_version,
        period_hash=value.period_hash,
        period_start=value.period_start,
        period_end=value.period_end,
        available_at=value.available_at,
        valid_until=value.valid_until,
        evidence_ref=value.evidence_ref,
        members=members,
    )
    if rebuilt != value:
        raise ForecastRealizationOwnerUnavailable("realization manifest source is noncanonical")
    return rebuilt


def _canonical_outcome(value: ForecastOutcomeOwnerRecord) -> ForecastOutcomeOwnerRecord:
    if type(value) is not ForecastOutcomeOwnerRecord:
        raise ForecastRealizationOwnerUnavailable(
            "forecast outcome source has an invalid Domain type"
        )
    ForecastOutcomeOwnerRecord.__post_init__(value)
    rebuilt = ForecastOutcomeOwnerRecord.create(
        entry_id=value.entry_id,
        binding=value.binding,
        pit_manifest_id=value.pit_manifest_id,
        published_at=value.published_at,
        horizon_end=value.horizon_end,
        scenario_realized=value.scenario_realized,
        outcome_recorded_at=value.outcome_recorded_at,
    )
    if rebuilt != value:
        raise ForecastRealizationOwnerUnavailable("forecast outcome source is noncanonical")
    return rebuilt


def build_django_forecast_realization_manifest_query(
    *, using: str = "default"
) -> GetExactForecastRealizationManifest:
    """Build the public read-only exact PIT Signal owner query."""

    return GetExactForecastRealizationManifest(
        DjangoForecastRealizationManifestRepository(using=using)
    )


def build_django_forecast_realization_owner_runtime(
    *, using: str = "default"
) -> DjangoForecastRealizationOwnerRuntime:
    """Build inert production writes plus the read-only exact PIT query."""

    return DjangoForecastRealizationOwnerRuntime(
        append=UnavailableForecastRealizationAppendFacade(),
        query=build_django_forecast_realization_manifest_query(using=using),
    )


def _build_django_forecast_realization_owner_test_runtime(
    *,
    clock: ForecastRealizationClock | None = None,
    using: str = "default",
) -> _DjangoForecastRealizationOwnerTestRuntime:
    """Bind the exact Django source registry, outcomes, and receipts to one UoW."""

    repository = DjangoForecastRealizationManifestRepository(using=using)
    outcome_provider = DjangoForecastOutcomeOwnerProvider(using=using)
    source_provider = DjangoForecastRealizationManifestSourceRegistryProvider(using=using)
    server_clock = clock or DjangoForecastRealizationClock(using=using)
    expected_key = f"django:{using}"
    try:
        keys = {
            expected_key,
            repository.unit_of_work_key,
            outcome_provider.unit_of_work_key,
            source_provider.unit_of_work_key,
            server_clock.unit_of_work_key,
        }
    except Exception as error:
        raise ForecastRealizationOwnerUnavailable(
            "forecast realization UoW identity is unavailable"
        ) from error
    if keys != {expected_key}:
        raise ForecastRealizationOwnerUnavailable("forecast realization owners use different UoWs")
    token = object()

    def read_source(
        command: AppendForecastRealizationManifestCommand,
        *,
        as_of: datetime,
    ) -> ForecastRealizationManifestSource:
        value = source_provider.get_exact(
            owner_record_id=command.owner_record_id,
            owner_record_version=command.owner_record_version,
            as_of=as_of,
        )
        if value is None:
            raise ForecastRealizationOwnerUnavailable(
                "forecast realization manifest source is unavailable"
            )
        source = _canonical_source(value)
        if (
            source.owner_record_id != command.owner_record_id
            or source.owner_record_version != command.owner_record_version
            or not source.available_at <= as_of < source.valid_until
        ):
            raise ForecastRealizationOwnerUnavailable(
                "forecast realization source identity or clocks are invalid"
            )
        return source

    def read_outcomes(
        source: ForecastRealizationManifestSource,
        *,
        as_of: datetime,
    ) -> tuple[ForecastOutcomeOwnerRecord, ...]:
        outcomes: list[ForecastOutcomeOwnerRecord] = []
        for member in source.members:
            value = outcome_provider.get_exact(entry_id=member.entry_id, as_of=as_of)
            if value is None:
                raise ForecastRealizationOwnerUnavailable(
                    f"forecast realization outcome is unavailable: {member.entry_id}"
                )
            outcomes.append(_canonical_outcome(value))
        return tuple(outcomes)

    def existing_by_owner(
        source: ForecastRealizationManifestSource,
    ) -> ForecastRealizationManifestModel | None:
        return (
            ForecastRealizationManifestModel._default_manager.using(using)
            .select_for_update()
            .prefetch_related("receipts__entry")
            .filter(
                owner_record_id=source.owner_record_id,
                owner_record_version=source.owner_record_version,
            )
            .first()
        )

    def match_existing(
        model: ForecastRealizationManifestModel,
        expected: ForecastRealizationManifest,
        *,
        as_of: datetime,
    ) -> ForecastRealizationManifest:
        restored = _manifest_from_model(
            model=model,
            outcome_provider=outcome_provider,
            as_of=as_of,
        )
        if restored != expected:
            raise ForecastRealizationOwnerUnavailable(
                "forecast realization owner identity conflicts with different evidence"
            )
        return restored

    def append_candidate(
        candidate: ForecastRealizationManifest,
        source: ForecastRealizationManifestSource,
        *,
        as_of: datetime,
    ) -> ForecastRealizationManifest:
        existing = existing_by_owner(source)
        if existing is not None:
            return match_existing(existing, candidate, as_of=as_of)
        manifest_values = _manifest_model_values(candidate)
        try:
            with transaction.atomic(using=using):
                with _activate_forecast_realization_uow(token):
                    manifest_model = ForecastRealizationManifestModel(**manifest_values)
                    manifest_model.full_clean()
                    with _claim_forecast_realization_insert(
                        token=token,
                        model_type=ForecastRealizationManifestModel,
                        expected_values=manifest_values,
                    ):
                        manifest_model.save(force_insert=True, using=using)
                    for receipt, metadata in zip(candidate.members, source.members, strict=True):
                        receipt_values = _receipt_model_values(
                            receipt,
                            manifest_id=manifest_model.pk,
                            entry_id=receipt.entry_id,
                            member_source_hash=metadata.content_hash,
                        )
                        receipt_model = ForecastRealizationReceiptModel(**receipt_values)
                        receipt_model.full_clean()
                        with _claim_forecast_realization_insert(
                            token=token,
                            model_type=ForecastRealizationReceiptModel,
                            expected_values=receipt_values,
                        ):
                            receipt_model.save(force_insert=True, using=using)
        except (IntegrityError, ValidationError) as error:
            winner = existing_by_owner(source)
            if winner is None:
                raise ForecastRealizationOwnerUnavailable(
                    "forecast realization receipt append failed"
                ) from error
            try:
                return match_existing(winner, candidate, as_of=as_of)
            except ForecastRealizationOwnerCorruption as corruption:
                raise ForecastRealizationOwnerUnavailable(
                    "forecast realization receipt append failed"
                ) from corruption
        return _manifest_from_model(
            model=manifest_model,
            outcome_provider=outcome_provider,
            as_of=as_of,
        )

    class _ClosureBoundWriter:
        __slots__ = ()

        def append(
            self,
            command: AppendForecastRealizationManifestCommand,
        ) -> ForecastRealizationManifest:
            """Double-read exact sources and append only the stable graph."""

            try:
                with transaction.atomic(using=using):
                    with _activate_forecast_realization_uow(token):
                        now = server_clock.now()
                        if now.tzinfo is None or now.utcoffset() is None:
                            raise ForecastRealizationOwnerUnavailable(
                                "forecast realization server clock is invalid"
                            )
                        first_source = read_source(command, as_of=now)
                        first_outcomes = read_outcomes(first_source, as_of=now)
                        second_source = read_source(command, as_of=now)
                        second_outcomes = read_outcomes(second_source, as_of=now)
                        if first_source != second_source or first_outcomes != second_outcomes:
                            raise ForecastRealizationOwnerUnavailable(
                                "forecast realization owner graph changed during reread"
                            )
                        candidate = ForecastRealizationManifest.from_sources(
                            source=second_source,
                            outcomes=second_outcomes,
                            recorded_at=now,
                        )
                        return append_candidate(
                            candidate,
                            second_source,
                            as_of=now,
                        )
            except ForecastRealizationOwnerUnavailable:
                raise
            except (ForecastRealizationOwnerCorruption, TypeError, ValueError) as error:
                raise ForecastRealizationOwnerUnavailable(
                    "forecast realization owner reread failed closed"
                ) from error

    return _DjangoForecastRealizationOwnerTestRuntime(
        append=AppendForecastRealizationManifest(_ClosureBoundWriter()),
        query=GetExactForecastRealizationManifest(repository),
    )


__all__ = [
    "DjangoForecastRealizationOwnerRuntime",
    "build_django_forecast_realization_manifest_query",
    "build_django_forecast_realization_owner_runtime",
]
