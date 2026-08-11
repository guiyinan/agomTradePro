"""ID-only application ports for Data Center evaluation actual evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.domain.evaluation_actual_manifest import (
    CanonicalEvaluationActualGraph,
    EvaluationActualSourceDefinition,
    MaterializedEvaluationActualManifest,
    PersistedEvaluationActualSourceDefinition,
)


def _require_token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a non-blank token")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class EvaluationActualConflict(ValueError):
    """An immutable source or manifest identity already has another winner."""


class EvaluationActualCorruption(ValueError):
    """Persisted payload, header or live content seal is inconsistent."""


class EvaluationActualUnavailable(ValueError):
    """Exact canonical evidence is unavailable at the requested PIT cutoff."""


class EvaluationActualClock(Protocol):
    """Trusted server clock participating in the shared database UoW."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def now(self) -> datetime:
        """Return the authoritative server time."""


class ExactEvaluationActualSourceDefinitionProvider(Protocol):
    """Canonical owner query for one complete source definition."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvaluationActualSourceDefinition | None:
        """Return one exact owner definition known at ``as_of``."""


class ExactEvaluationActualGraphProvider(Protocol):
    """Canonical exact fact/member/vintage query used for materialization."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        definition: EvaluationActualSourceDefinition,
        as_of: datetime,
    ) -> CanonicalEvaluationActualGraph | None:
        """Return one complete owner graph without constructing a snapshot."""


class EvaluationActualReadRepository(Protocol):
    """Capability-minimal exact/PIT repository retained by read paths."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_source_definition(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedEvaluationActualSourceDefinition | None:
        """Read one exact definition knowable at ``as_of``."""

    def get_manifest(
        self,
        *,
        manifest_id: str,
        manifest_version: str,
        as_of: datetime,
    ) -> MaterializedEvaluationActualManifest | None:
        """Read one exact materialized receipt knowable at ``as_of``."""


class EvaluationActualAtomicStore(Protocol):
    """Private append capability used only by controlled composition."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one all-or-nothing owner reread and append boundary."""

    def append_source_definition(
        self,
        record: PersistedEvaluationActualSourceDefinition,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Append one exact definition or return its exact winner."""

    def append_manifest(
        self,
        manifest: MaterializedEvaluationActualManifest,
    ) -> MaterializedEvaluationActualManifest:
        """Append one exact manifest or return its exact winner."""


class EvaluationActualSourceRegistrationWriter(Protocol):
    """Private ID-only definition registration port."""

    def register(
        self,
        command: RegisterEvaluationActualSourceCommand,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Reread the owner and append a trusted server-time receipt."""


class EvaluationActualManifestMaterializationWriter(Protocol):
    """Private ID-only actual graph materialization port."""

    def materialize(
        self,
        command: MaterializeEvaluationActualManifestCommand,
    ) -> MaterializedEvaluationActualManifest:
        """Reread canonical facts and append an internally built manifest."""


@dataclass(frozen=True, slots=True)
class RegisterEvaluationActualSourceCommand:
    """Identifier/version/cutoff-only source registration request."""

    source_id: str
    source_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class MaterializeEvaluationActualManifestCommand:
    """ID-only request to build one manifest from registered owner evidence."""

    manifest_id: str
    manifest_version: str
    source_id: str
    source_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.manifest_id, "manifest_id")
        _require_token(self.manifest_version, "manifest_version")
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetExactEvaluationActualSourceCommand:
    """Exact source-definition historical query."""

    source_id: str
    source_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_aware(self.as_of, "as_of")


class RegisterEvaluationActualSource:
    """Expose only ID-only definition registration."""

    __slots__ = ("_writer",)

    def __init__(self, writer: EvaluationActualSourceRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterEvaluationActualSourceCommand,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Live-revalidate a command before delegating to the private writer."""

        _validate_registration_command(command)
        return self._writer.register(command)


class MaterializeEvaluationActualManifest:
    """Expose only ID-only canonical actual materialization."""

    __slots__ = ("_writer",)

    def __init__(self, writer: EvaluationActualManifestMaterializationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: MaterializeEvaluationActualManifestCommand,
    ) -> MaterializedEvaluationActualManifest:
        """Live-revalidate a command before delegating to the private writer."""

        _validate_materialization_command(command)
        return self._writer.materialize(command)


class GetExactEvaluationActualSource:
    """Read one exact registered source definition with no fallback."""

    __slots__ = ("_repository",)

    def __init__(self, repository: EvaluationActualReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactEvaluationActualSourceCommand,
    ) -> PersistedEvaluationActualSourceDefinition | None:
        """Return only an exact identity knowable at the query cutoff."""

        try:
            if type(command) is not GetExactEvaluationActualSourceCommand:
                raise TypeError
            GetExactEvaluationActualSourceCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise EvaluationActualUnavailable(
                "evaluation actual source query command is invalid"
            ) from error
        return self._repository.get_source_definition(
            source_id=command.source_id,
            source_version=command.source_version,
            as_of=command.as_of,
        )


def _validate_registration_command(command: RegisterEvaluationActualSourceCommand) -> None:
    try:
        if type(command) is not RegisterEvaluationActualSourceCommand:
            raise TypeError
        RegisterEvaluationActualSourceCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise EvaluationActualUnavailable(
            "evaluation actual source registration command is invalid"
        ) from error


def _validate_materialization_command(
    command: MaterializeEvaluationActualManifestCommand,
) -> None:
    try:
        if type(command) is not MaterializeEvaluationActualManifestCommand:
            raise TypeError
        MaterializeEvaluationActualManifestCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise EvaluationActualUnavailable(
            "evaluation actual materialization command is invalid"
        ) from error


__all__ = [
    "EvaluationActualAtomicStore",
    "EvaluationActualClock",
    "EvaluationActualConflict",
    "EvaluationActualCorruption",
    "EvaluationActualManifestMaterializationWriter",
    "EvaluationActualReadRepository",
    "EvaluationActualSourceRegistrationWriter",
    "EvaluationActualUnavailable",
    "ExactEvaluationActualGraphProvider",
    "ExactEvaluationActualSourceDefinitionProvider",
    "GetExactEvaluationActualSource",
    "GetExactEvaluationActualSourceCommand",
    "MaterializeEvaluationActualManifest",
    "MaterializeEvaluationActualManifestCommand",
    "RegisterEvaluationActualSource",
    "RegisterEvaluationActualSourceCommand",
]
