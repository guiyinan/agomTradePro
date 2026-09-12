"""Application contracts for durable Account ownership re-observation evidence."""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.physical_account_row_observation_v2 import (
    GetCurrentPhysicalAccountRowObservationV2Command,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from core.exceptions import DataValidationError, DuplicateResourceError

_RECORD_SEAL_DOMAIN = "canonical-account-ownership-reobservation.v1/record"
_LEDGER_SEAL_DOMAIN = "canonical-account-ownership-reobservation.v1/ledger"


class CanonicalAccountOwnershipReobservationV1Conflict(DuplicateResourceError):
    """The immutable first winner differs from the requested observation."""


class CanonicalAccountOwnershipReobservationV1Corruption(DataValidationError):
    """A repository or source reader substituted invalid durable evidence."""


def _token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _digest(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PersistedCanonicalAccountOwnershipReobservationV1:
    """Wrap one exact immutable re-observation for repository boundaries."""

    reobservation: CanonicalAccountOwnershipReobservationV1
    identity_hash: str = ""
    content_hash: str = ""
    record_seal: str = ""
    ledger_seal: str = ""

    def __post_init__(self) -> None:
        """Reject type substitution and revalidate all nested seals."""

        if type(self.reobservation) is not CanonicalAccountOwnershipReobservationV1:
            raise TypeError("reobservation must be an exact v1 value")
        self.reobservation.__post_init__()
        expected_record_seal = _canonical_hash(_RECORD_SEAL_DOMAIN, self.reobservation.to_payload())
        expected_ledger_seal = _canonical_hash(
            _LEDGER_SEAL_DOMAIN,
            {
                "identity_hash": self.reobservation.identity_hash,
                "content_hash": self.reobservation.content_hash,
                "record_seal": expected_record_seal,
                "binding_content_hash": self.reobservation.binding.content_hash,
                "current_physical_content_hash": (self.reobservation.current_physical.content_hash),
            },
        )
        for field_name, expected in (
            ("identity_hash", self.reobservation.identity_hash),
            ("content_hash", self.reobservation.content_hash),
            ("record_seal", expected_record_seal),
            ("ledger_seal", expected_ledger_seal),
        ):
            observed = getattr(self, field_name)
            if type(observed) is not str:
                raise TypeError(f"{field_name} must be an exact string")
            if observed == "":
                object.__setattr__(self, field_name, expected)
            elif _checked_digest(observed, field_name) != expected:
                raise ValueError(f"ownership re-observation {field_name} is invalid")


@dataclass(frozen=True, slots=True)
class RecordCanonicalAccountOwnershipReobservationV1Command:
    """Request durable first-winner recording of one already observed fact."""

    reobservation: CanonicalAccountOwnershipReobservationV1

    def __post_init__(self) -> None:
        """Require an exact, fully sealed re-observation value."""

        PersistedCanonicalAccountOwnershipReobservationV1(self.reobservation)


@dataclass(frozen=True, slots=True)
class GetExactCanonicalAccountOwnershipReobservationV1Command:
    """Select one immutable historical re-observation at a point in time."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate the exact identity, content, and PIT selectors."""

        _token(self.observation_id, "observation_id")
        _token(self.observation_version, "observation_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentCanonicalAccountOwnershipReobservationV1Command:
    """Select one exact re-observation only while its physical fact is current."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate the exact identity, content, and current-time selectors."""

        _token(self.observation_id, "observation_id")
        _token(self.observation_version, "observation_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


class CanonicalAccountOwnershipReobservationV1Repository(Protocol):
    """Persist immutable first winners and expose exact historical reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work."""
        ...

    def now(self) -> datetime:
        """Return the repository's aware server clock."""
        ...

    def get_winner(
        self, *, observation_id: str, observation_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        """Return the immutable identity winner knowable at ``as_of``."""
        ...

    def append(
        self,
        record: PersistedCanonicalAccountOwnershipReobservationV1,
        *,
        recorded_at: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        """Append or replay the exact first winner."""
        ...

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        """Return only the requested historical identity and content hash."""
        ...


class CurrentPhysicalAccountRowObservationV2Reader(Protocol):
    """Public Application port proving one exact Physical-v2 logical head."""

    def execute(
        self, command: GetCurrentPhysicalAccountRowObservationV2Command
    ) -> PhysicalAccountRowObservationV2 | None:
        """Return the exact observation only while all upstream facts are current."""
        ...


class RecordCanonicalAccountOwnershipReobservationV1:
    """Record or replay one immutable re-observation first winner."""

    def __init__(self, repository: CanonicalAccountOwnershipReobservationV1Repository) -> None:
        """Inject the durable repository boundary."""

        self._repository = repository

    def execute(
        self, command: RecordCanonicalAccountOwnershipReobservationV1Command
    ) -> CanonicalAccountOwnershipReobservationV1:
        """Append once and reject a different winner for the same identity."""

        if type(command) is not RecordCanonicalAccountOwnershipReobservationV1Command:
            raise TypeError("command must be an exact v1 record command")
        command.__post_init__()
        expected = PersistedCanonicalAccountOwnershipReobservationV1(command.reobservation)
        value = expected.reobservation
        with self._repository.atomic():
            cutoff = _repository_clock(self._repository.now())
            winner = self._repository.get_winner(
                observation_id=value.observation_id,
                observation_version=value.observation_version,
                as_of=cutoff,
            )
            if winner is not None:
                checked = _record(winner)
                if checked.reobservation.recorded_at > cutoff:
                    raise CanonicalAccountOwnershipReobservationV1Corruption(
                        "repository returned a future ownership re-observation winner"
                    )
                if checked != expected:
                    raise CanonicalAccountOwnershipReobservationV1Conflict(
                        "ownership re-observation identity has another first winner"
                    )
                return checked.reobservation
            if value.recorded_at > cutoff:
                raise CanonicalAccountOwnershipReobservationV1Corruption(
                    "ownership re-observation was recorded in the future"
                )
            persisted = _record(self._repository.append(expected, recorded_at=value.recorded_at))
            if persisted != expected:
                raise CanonicalAccountOwnershipReobservationV1Conflict(
                    "concurrent ownership re-observation first winner differs"
                )
            return persisted.reobservation


class GetExactCanonicalAccountOwnershipReobservationV1:
    """Read exact historical evidence without applying current TTL rules."""

    def __init__(self, repository: CanonicalAccountOwnershipReobservationV1Repository) -> None:
        """Inject the durable repository boundary."""

        self._repository = repository

    def execute(
        self, command: GetExactCanonicalAccountOwnershipReobservationV1Command
    ) -> CanonicalAccountOwnershipReobservationV1 | None:
        """Return an exact value whenever it was recorded by the PIT cutoff."""

        if type(command) is not GetExactCanonicalAccountOwnershipReobservationV1Command:
            raise TypeError("command must be an exact v1 historical command")
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        observation = _record(value).reobservation
        if (
            observation.observation_id != command.observation_id
            or observation.observation_version != command.observation_version
            or observation.content_hash != command.expected_content_hash
        ):
            raise CanonicalAccountOwnershipReobservationV1Corruption(
                "historical ownership re-observation selector substitution"
            )
        return observation if observation.is_knowable_at(command.as_of) else None


class GetCurrentCanonicalAccountOwnershipReobservationV1:
    """Read a re-observation only while its exact Physical-v2 fact is current."""

    def __init__(
        self,
        *,
        repository: CanonicalAccountOwnershipReobservationV1Repository,
        current_physical_reader: CurrentPhysicalAccountRowObservationV2Reader,
    ) -> None:
        """Inject historical storage and the public current-physical reader."""

        self._repository = repository
        self._current_physical_reader = current_physical_reader

    def execute(
        self, command: GetCurrentCanonicalAccountOwnershipReobservationV1Command
    ) -> CanonicalAccountOwnershipReobservationV1 | None:
        """Return only an unexpired proof whose exact physical parent is the head."""

        if type(command) is not GetCurrentCanonicalAccountOwnershipReobservationV1Command:
            raise TypeError("command must be an exact v1 current command")
        command.__post_init__()
        exact = GetExactCanonicalAccountOwnershipReobservationV1(self._repository).execute(
            GetExactCanonicalAccountOwnershipReobservationV1Command(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if exact is None or not exact.is_current_at(command.as_of):
            return None
        current = self._current_physical_reader.execute(
            GetCurrentPhysicalAccountRowObservationV2Command(
                expected_observation=exact.current_physical,
                as_of=command.as_of,
            )
        )
        if current is None:
            return None
        if type(current) is not PhysicalAccountRowObservationV2:
            raise CanonicalAccountOwnershipReobservationV1Corruption(
                "current physical reader substituted the result type"
            )
        try:
            current.__post_init__()
        except (TypeError, ValueError) as error:
            raise CanonicalAccountOwnershipReobservationV1Corruption(
                "current physical reader returned invalid evidence"
            ) from error
        if current != exact.current_physical:
            raise CanonicalAccountOwnershipReobservationV1Corruption(
                "current physical reader substituted another logical head"
            )
        return exact


def _record(value: object) -> PersistedCanonicalAccountOwnershipReobservationV1:
    if type(value) is not PersistedCanonicalAccountOwnershipReobservationV1:
        raise CanonicalAccountOwnershipReobservationV1Corruption(
            "repository substituted the ownership re-observation record type"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationV1Corruption(
            "repository returned an invalid ownership re-observation record"
        ) from error
    return value


def _repository_clock(value: object) -> datetime:
    try:
        return _aware(value, "repository clock")
    except ValueError as error:
        raise CanonicalAccountOwnershipReobservationV1Corruption(
            "repository clock is invalid"
        ) from error


def _checked_digest(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be an exact string")
    _digest(value, field_name)
    return value


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CanonicalAccountOwnershipReobservationV1Conflict",
    "CanonicalAccountOwnershipReobservationV1Corruption",
    "CanonicalAccountOwnershipReobservationV1Repository",
    "CurrentPhysicalAccountRowObservationV2Reader",
    "GetCurrentCanonicalAccountOwnershipReobservationV1",
    "GetCurrentCanonicalAccountOwnershipReobservationV1Command",
    "GetExactCanonicalAccountOwnershipReobservationV1",
    "GetExactCanonicalAccountOwnershipReobservationV1Command",
    "PersistedCanonicalAccountOwnershipReobservationV1",
    "RecordCanonicalAccountOwnershipReobservationV1",
    "RecordCanonicalAccountOwnershipReobservationV1Command",
]
