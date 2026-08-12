"""ID-only Application contracts for the Research-owned R3 runner-spec ledger."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec
from apps.research.domain.r3_macro_factor_runner_spec import (
    PersistedMacroFactorRunnerSpecRecord,
)


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a non-blank token")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a sha256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class MacroFactorRunnerSpecConflict(ValueError):
    """The requested immutable spec identity was already sealed."""


class MacroFactorRunnerSpecCorruption(ValueError):
    """Persisted bytes or headers do not match their canonical seals."""


class MacroFactorRunnerSpecUnavailable(ValueError):
    """No exact authoritative spec is available at the requested cutoff."""


class ExactMacroFactorRunnerSpecDefinitionProvider(Protocol):
    """Read one complete owner definition without accepting caller spec fields."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction boundary used by the owner query."""

    def get_exact(
        self,
        *,
        spec_id: str,
        spec_version: int,
        as_of: datetime,
    ) -> MacroFactorRunnerSpec | None:
        """Return the exact owner definition known at ``as_of`` or ``None``."""


class MacroFactorRunnerSpecRepository(Protocol):
    """Read-only exact/PIT port for persisted authoritative specs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction boundary used by persisted reads."""

    def get_exact(
        self,
        *,
        spec_id: str,
        spec_version: int,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedMacroFactorRunnerSpecRecord | None:
        """Return one exact record with no latest or fallback behavior."""

    def get_by_identity(
        self,
        *,
        spec_id: str,
        spec_version: int,
    ) -> PersistedMacroFactorRunnerSpecRecord | None:
        """Strictly restore one exact identity for the runner provider port."""


class MacroFactorRunnerSpecRegistrationWriter(Protocol):
    """Private writer that resolves an ID-only command inside one append."""

    def register(
        self,
        command: RegisterMacroFactorRunnerSpecCommand,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Reread the owner definition and append one server-timed record."""


class MacroFactorRunnerSpecAtomicStore(Protocol):
    """Private append-only store retained only by test composition."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction boundary used by registration."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one all-or-nothing registration boundary."""

    def append(
        self,
        record: PersistedMacroFactorRunnerSpecRecord,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Append one exact record or raise a stable conflict."""


@dataclass(frozen=True)
class RegisterMacroFactorRunnerSpecCommand:
    """Identifier/version/cutoff-only registration request."""

    spec_id: str
    spec_version: int
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.spec_id, "spec_id")
        if type(self.spec_version) is not int or self.spec_version <= 0:
            raise ValueError("spec_version must be a positive integer")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetExactMacroFactorRunnerSpecCommand:
    """Exact historical query without latest/current fallback."""

    spec_id: str
    spec_version: int
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.spec_id, "spec_id")
        if type(self.spec_version) is not int or self.spec_version <= 0:
            raise ValueError("spec_version must be a positive integer")
        _require_sha256(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


class RegisterMacroFactorRunnerSpec:
    """Expose only the ID-only registration operation."""

    def __init__(self, writer: MacroFactorRunnerSpecRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterMacroFactorRunnerSpecCommand,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Revalidate the command before delegating to the private writer."""

        try:
            if type(command) is not RegisterMacroFactorRunnerSpecCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner-spec registration command is invalid"
            ) from error
        return self._writer.register(command)


class GetExactMacroFactorRunnerSpec:
    """Read one content-addressed persisted spec record."""

    def __init__(self, repository: MacroFactorRunnerSpecRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactMacroFactorRunnerSpecCommand,
    ) -> PersistedMacroFactorRunnerSpecRecord | None:
        """Return only the exact identity/hash knowable at ``as_of``."""

        try:
            if type(command) is not GetExactMacroFactorRunnerSpecCommand:
                raise TypeError
            command.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner-spec exact query command is invalid"
            ) from error
        return self._repository.get_exact(
            spec_id=command.spec_id,
            spec_version=command.spec_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


__all__ = [
    "ExactMacroFactorRunnerSpecDefinitionProvider",
    "GetExactMacroFactorRunnerSpec",
    "GetExactMacroFactorRunnerSpecCommand",
    "MacroFactorRunnerSpecAtomicStore",
    "MacroFactorRunnerSpecConflict",
    "MacroFactorRunnerSpecCorruption",
    "MacroFactorRunnerSpecRegistrationWriter",
    "MacroFactorRunnerSpecRepository",
    "MacroFactorRunnerSpecUnavailable",
    "RegisterMacroFactorRunnerSpec",
    "RegisterMacroFactorRunnerSpecCommand",
]
