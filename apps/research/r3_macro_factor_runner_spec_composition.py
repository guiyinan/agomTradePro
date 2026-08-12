"""Production composition for the Research-owned R3 runner-spec ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError

from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec
from apps.research.application.r3_macro_factor_runner_spec import (
    ExactMacroFactorRunnerSpecDefinitionProvider,
    GetExactMacroFactorRunnerSpec,
    MacroFactorRunnerSpecConflict,
    MacroFactorRunnerSpecUnavailable,
    RegisterMacroFactorRunnerSpec,
    RegisterMacroFactorRunnerSpecCommand,
)
from apps.research.domain.r3_macro_factor_runner_spec import (
    PersistedMacroFactorRunnerSpecRecord,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_repository import (
    DjangoMacroFactorRunnerSpecProvider,
    DjangoR3MacroFactorRunnerSpecClock,
    DjangoR3MacroFactorRunnerSpecDefinitionProvider,
    DjangoR3MacroFactorRunnerSpecRepository,
    R3MacroFactorRunnerSpecClock,
    _DjangoR3MacroFactorRunnerSpecStore,
)


class _R3MacroFactorRunnerSpecRegistrationWriter:
    """Resolve and reread one owner spec inside the exact append UoW."""

    __slots__ = (
        "_clock",
        "_provider",
        "_repository",
        "_store",
        "_unit_of_work_key",
    )

    def __init__(
        self,
        *,
        provider: DjangoR3MacroFactorRunnerSpecDefinitionProvider,
        repository: DjangoR3MacroFactorRunnerSpecRepository,
        store: _DjangoR3MacroFactorRunnerSpecStore,
        clock: R3MacroFactorRunnerSpecClock,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._store = store
        self._clock = clock
        self._unit_of_work_key = store.unit_of_work_key
        self._require_uow_key()

    def register(
        self,
        command: RegisterMacroFactorRunnerSpecCommand,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Read, time, reread, compare, and append without caller-owned content."""

        try:
            command.__post_init__()
            self._require_uow_key()
            with self._store.atomic():
                self._require_uow_key()
                first = self._read_owner_spec(command, as_of=command.as_of)
                self._require_uow_key()
                ledger_recorded_at = self._trusted_now()
                if command.as_of > ledger_recorded_at:
                    raise MacroFactorRunnerSpecUnavailable(
                        "future R3 runner-spec registration cutoff"
                    )
                second = self._read_owner_spec(command, as_of=ledger_recorded_at)
                if first != second or first.content_hash.lower() != second.content_hash.lower():
                    raise MacroFactorRunnerSpecUnavailable(
                        "R3 runner-spec owner definition changed during registration"
                    )
                if second.registered_at > command.as_of:
                    raise MacroFactorRunnerSpecUnavailable(
                        "R3 runner spec was not owner-known at the requested cutoff"
                    )
                self._require_uow_key()
                return self._store.append(
                    PersistedMacroFactorRunnerSpecRecord.create(
                        spec=second,
                        ledger_recorded_at=ledger_recorded_at,
                    )
                )
        except MacroFactorRunnerSpecConflict:
            raise
        except MacroFactorRunnerSpecUnavailable:
            raise
        except IntegrityError as error:
            raise MacroFactorRunnerSpecConflict("R3 runner-spec append race lost") from error
        except Exception as error:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner-spec owner, clock, or record is unavailable"
            ) from error

    def _require_uow_key(self) -> None:
        keys = {
            self._provider.unit_of_work_key,
            self._repository.unit_of_work_key,
            self._store.unit_of_work_key,
        }
        if keys != {self._unit_of_work_key}:
            raise ValueError("R3 runner-spec unit of work changed after composition")

    def _read_owner_spec(
        self,
        command: RegisterMacroFactorRunnerSpecCommand,
        *,
        as_of: datetime,
    ) -> MacroFactorRunnerSpec:
        spec = self._provider.get_exact(
            spec_id=command.spec_id,
            spec_version=command.spec_version,
            as_of=as_of,
        )
        if spec is None:
            raise MacroFactorRunnerSpecUnavailable(
                "exact authoritative R3 runner spec is unavailable"
            )
        validated = spec.validated_copy()
        if validated.run_key != command.spec_id or validated.run_version != command.spec_version:
            raise MacroFactorRunnerSpecUnavailable("R3 runner-spec owner identity substitution")
        return validated

    def _trusted_now(self) -> datetime:
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise MacroFactorRunnerSpecUnavailable("R3 runner-spec server clock is naive")
        return now


class _UnavailableMacroFactorRunnerSpecRegistrationFacade:
    """State-free production mutation surface while no owner query is composed."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterMacroFactorRunnerSpecCommand,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Validate the ID-only command, then fail without constructing a store."""

        try:
            if type(command) is not RegisterMacroFactorRunnerSpecCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner-spec registration command is invalid"
            ) from error
        raise MacroFactorRunnerSpecUnavailable(
            "R3 runner-spec authoritative owner provider is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR3MacroFactorRunnerSpecRuntime:
    """Inert production registration plus exact read/provider capabilities."""

    register: _UnavailableMacroFactorRunnerSpecRegistrationFacade
    get_exact: GetExactMacroFactorRunnerSpec
    provider: DjangoMacroFactorRunnerSpecProvider


@dataclass(frozen=True, slots=True)
class _DjangoR3MacroFactorRunnerSpecTestRuntime:
    """Private injectable runtime used only by component tests."""

    register: RegisterMacroFactorRunnerSpec
    get_exact: GetExactMacroFactorRunnerSpec
    provider: DjangoMacroFactorRunnerSpecProvider
    repository: DjangoR3MacroFactorRunnerSpecRepository


def build_django_r3_macro_factor_runner_spec_runtime(
    *,
    using: str = "default",
) -> DjangoR3MacroFactorRunnerSpecRuntime:
    """Build no writer/store graph while the authoritative owner is absent."""

    repository = DjangoR3MacroFactorRunnerSpecRepository(using=using)
    return DjangoR3MacroFactorRunnerSpecRuntime(
        register=_UnavailableMacroFactorRunnerSpecRegistrationFacade(),
        get_exact=GetExactMacroFactorRunnerSpec(repository),
        provider=DjangoMacroFactorRunnerSpecProvider(repository),
    )


def _build_django_r3_macro_factor_runner_spec_test_runtime(
    *,
    definition_provider: ExactMacroFactorRunnerSpecDefinitionProvider,
    using: str = "default",
    clock: R3MacroFactorRunnerSpecClock | None = None,
) -> _DjangoR3MacroFactorRunnerSpecTestRuntime:
    """Build the private UoW-coherent runtime for persistence tests."""

    authoritative_clock = clock or DjangoR3MacroFactorRunnerSpecClock()
    repository = DjangoR3MacroFactorRunnerSpecRepository(
        using=using,
        clock=authoritative_clock,
    )
    store = _DjangoR3MacroFactorRunnerSpecStore(using=using)
    owner_provider = DjangoR3MacroFactorRunnerSpecDefinitionProvider(definition_provider)
    keys = {
        repository.unit_of_work_key,
        store.unit_of_work_key,
        owner_provider.unit_of_work_key,
    }
    if len(keys) != 1:
        raise ValueError("R3 runner-spec runtime requires one shared unit of work")
    writer = _R3MacroFactorRunnerSpecRegistrationWriter(
        provider=owner_provider,
        repository=repository,
        store=store,
        clock=authoritative_clock,
    )
    return _DjangoR3MacroFactorRunnerSpecTestRuntime(
        register=RegisterMacroFactorRunnerSpec(writer),
        get_exact=GetExactMacroFactorRunnerSpec(repository),
        provider=DjangoMacroFactorRunnerSpecProvider(repository),
        repository=repository,
    )


__all__ = [
    "DjangoR3MacroFactorRunnerSpecRuntime",
    "build_django_r3_macro_factor_runner_spec_runtime",
]
