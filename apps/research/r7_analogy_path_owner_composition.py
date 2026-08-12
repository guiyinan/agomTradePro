"""Capability-isolated composition for Research-owned R7 analogy/path evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r7_analogy_path_owner import (
    HistoricalAnalogyDefinitionSource,
    HistoricalAnalogyRawSourceProvider,
    R7AnalogyPathOwnerClock,
    R7AnalogyPathOwnerUnavailable,
    RegisterHistoricalAnalogyDefinition,
    RegisterHistoricalAnalogyDefinitionCommand,
    RegisterHistoricalAnalogyReceipt,
    RegisterHistoricalAnalogyReceiptCommand,
    RegisterScenarioPathDefinition,
    RegisterScenarioPathDefinitionCommand,
    RegisterScenarioPathReceipt,
    RegisterScenarioPathReceiptCommand,
    ScenarioPathDefinitionSource,
    ScenarioPathRawSourceProvider,
)
from apps.research.infrastructure.r7_analogy_path_owner_repository import (
    DjangoR7AnalogyDefinitionRepository,
    DjangoR7AnalogyPathOwnerClock,
    DjangoR7HistoricalAnalogyProvider,
    DjangoR7PathDefinitionRepository,
    DjangoR7PathStudyProvider,
    _build_r7_analogy_path_stores,
)


class UnavailableHistoricalAnalogyDefinitionRegistrationFacade:
    """Stateless production facade without analogy-definition write authority."""

    __slots__ = ()

    def execute(self, command: RegisterHistoricalAnalogyDefinitionCommand) -> NoReturn:
        """Validate an identity-only command and stop before database access."""

        _validate_analogy_definition_command(command)
        raise R7AnalogyPathOwnerUnavailable(
            "canonical historical analogy definition source is unavailable"
        )


class UnavailableHistoricalAnalogyReceiptRegistrationFacade:
    """Stateless production facade without analogy-receipt write authority."""

    __slots__ = ()

    def execute(self, command: RegisterHistoricalAnalogyReceiptCommand) -> NoReturn:
        """Validate an identity-only command and stop before database access."""

        _validate_analogy_receipt_command(command)
        raise R7AnalogyPathOwnerUnavailable(
            "canonical historical analogy raw source is unavailable"
        )


class UnavailableScenarioPathDefinitionRegistrationFacade:
    """Stateless production facade without path-definition write authority."""

    __slots__ = ()

    def execute(self, command: RegisterScenarioPathDefinitionCommand) -> NoReturn:
        """Validate an identity-only command and stop before database access."""

        _validate_path_definition_command(command)
        raise R7AnalogyPathOwnerUnavailable(
            "canonical scenario path definition source is unavailable"
        )


class UnavailableScenarioPathReceiptRegistrationFacade:
    """Stateless production facade without path-receipt write authority."""

    __slots__ = ()

    def execute(self, command: RegisterScenarioPathReceiptCommand) -> NoReturn:
        """Validate an identity-only command and stop before database access."""

        _validate_path_receipt_command(command)
        raise R7AnalogyPathOwnerUnavailable("canonical scenario path raw source is unavailable")


@dataclass(frozen=True, slots=True)
class DjangoR7AnalogyPathOwnerRuntime:
    """Public read-only owner adapters plus deliberately inert registration."""

    register_analogy_definition: UnavailableHistoricalAnalogyDefinitionRegistrationFacade
    register_analogy_receipt: UnavailableHistoricalAnalogyReceiptRegistrationFacade
    register_path_definition: UnavailableScenarioPathDefinitionRegistrationFacade
    register_path_receipt: UnavailableScenarioPathReceiptRegistrationFacade
    historical_analogy_provider: DjangoR7HistoricalAnalogyProvider
    path_study_provider: DjangoR7PathStudyProvider


@dataclass(frozen=True, slots=True)
class _DjangoR7AnalogyPathOwnerTestRuntime:
    """Private source-backed owner graph used only by component tests."""

    register_analogy_definition: RegisterHistoricalAnalogyDefinition
    register_analogy_receipt: RegisterHistoricalAnalogyReceipt
    register_path_definition: RegisterScenarioPathDefinition
    register_path_receipt: RegisterScenarioPathReceipt
    historical_analogy_provider: DjangoR7HistoricalAnalogyProvider
    path_study_provider: DjangoR7PathStudyProvider
    analogy_raw_source: HistoricalAnalogyRawSourceProvider
    path_raw_source: ScenarioPathRawSourceProvider


def build_django_r7_analogy_path_owner_runtime(
    *, using: str = "default"
) -> DjangoR7AnalogyPathOwnerRuntime:
    """Expose exact reads without retaining a source, clock, store, or token."""

    return DjangoR7AnalogyPathOwnerRuntime(
        register_analogy_definition=(UnavailableHistoricalAnalogyDefinitionRegistrationFacade()),
        register_analogy_receipt=UnavailableHistoricalAnalogyReceiptRegistrationFacade(),
        register_path_definition=UnavailableScenarioPathDefinitionRegistrationFacade(),
        register_path_receipt=UnavailableScenarioPathReceiptRegistrationFacade(),
        historical_analogy_provider=DjangoR7HistoricalAnalogyProvider(using=using),
        path_study_provider=DjangoR7PathStudyProvider(using=using),
    )


def _build_django_r7_analogy_path_owner_test_runtime(
    *,
    analogy_definition_source: HistoricalAnalogyDefinitionSource,
    analogy_raw_source: HistoricalAnalogyRawSourceProvider,
    path_definition_source: ScenarioPathDefinitionSource,
    path_raw_source: ScenarioPathRawSourceProvider,
    clock: R7AnalogyPathOwnerClock | None = None,
    using: str = "default",
) -> _DjangoR7AnalogyPathOwnerTestRuntime:
    """Wire all four private stores to exact sources and one trusted clock."""

    trusted_clock = clock or DjangoR7AnalogyPathOwnerClock(using=using)
    stores = _build_r7_analogy_path_stores(using=using, clock=trusted_clock)
    return _DjangoR7AnalogyPathOwnerTestRuntime(
        register_analogy_definition=RegisterHistoricalAnalogyDefinition(
            source=analogy_definition_source,
            store=stores.analogy_definition,
            clock=trusted_clock,
        ),
        register_analogy_receipt=RegisterHistoricalAnalogyReceipt(
            definition_source=DjangoR7AnalogyDefinitionRepository(using=using),
            raw_source=analogy_raw_source,
            store=stores.analogy_receipt,
            clock=trusted_clock,
        ),
        register_path_definition=RegisterScenarioPathDefinition(
            source=path_definition_source,
            store=stores.path_definition,
            clock=trusted_clock,
        ),
        register_path_receipt=RegisterScenarioPathReceipt(
            definition_source=DjangoR7PathDefinitionRepository(using=using),
            raw_source=path_raw_source,
            store=stores.path_receipt,
            clock=trusted_clock,
        ),
        historical_analogy_provider=DjangoR7HistoricalAnalogyProvider(using=using),
        path_study_provider=DjangoR7PathStudyProvider(using=using),
        analogy_raw_source=analogy_raw_source,
        path_raw_source=path_raw_source,
    )


def _validate_analogy_definition_command(command: object) -> None:
    try:
        if type(command) is not RegisterHistoricalAnalogyDefinitionCommand:
            raise TypeError("historical analogy definition command type differs")
        RegisterHistoricalAnalogyDefinitionCommand.__post_init__(command)
        rebuilt = RegisterHistoricalAnalogyDefinitionCommand(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        if rebuilt != command:
            raise ValueError("historical analogy definition command differs after replay")
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerUnavailable(
            "malformed historical analogy definition registration command"
        ) from error


def _validate_analogy_receipt_command(command: object) -> None:
    try:
        if type(command) is not RegisterHistoricalAnalogyReceiptCommand:
            raise TypeError("historical analogy receipt command type differs")
        RegisterHistoricalAnalogyReceiptCommand.__post_init__(command)
        rebuilt = RegisterHistoricalAnalogyReceiptCommand(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            as_of=command.as_of,
        )
        if rebuilt != command:
            raise ValueError("historical analogy receipt command differs after replay")
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerUnavailable(
            "malformed historical analogy receipt registration command"
        ) from error


def _validate_path_definition_command(command: object) -> None:
    try:
        if type(command) is not RegisterScenarioPathDefinitionCommand:
            raise TypeError("scenario path definition command type differs")
        RegisterScenarioPathDefinitionCommand.__post_init__(command)
        rebuilt = RegisterScenarioPathDefinitionCommand(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        if rebuilt != command:
            raise ValueError("scenario path definition command differs after replay")
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerUnavailable(
            "malformed scenario path definition registration command"
        ) from error


def _validate_path_receipt_command(command: object) -> None:
    try:
        if type(command) is not RegisterScenarioPathReceiptCommand:
            raise TypeError("scenario path receipt command type differs")
        RegisterScenarioPathReceiptCommand.__post_init__(command)
        rebuilt = RegisterScenarioPathReceiptCommand(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            as_of=command.as_of,
        )
        if rebuilt != command:
            raise ValueError("scenario path receipt command differs after replay")
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerUnavailable(
            "malformed scenario path receipt registration command"
        ) from error


__all__ = [
    "DjangoR7AnalogyPathOwnerRuntime",
    "UnavailableHistoricalAnalogyDefinitionRegistrationFacade",
    "UnavailableHistoricalAnalogyReceiptRegistrationFacade",
    "UnavailableScenarioPathDefinitionRegistrationFacade",
    "UnavailableScenarioPathReceiptRegistrationFacade",
    "build_django_r7_analogy_path_owner_runtime",
]
