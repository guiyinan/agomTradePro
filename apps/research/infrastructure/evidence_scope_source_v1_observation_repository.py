"""Strict read-only persistence adapter for Evidence scope observations.

This module exposes the dormant Application observation provider contract only.
It has no capture path, owner/tenant authority lookup, append capability,
session access, route, or writer.  Every query restores and verifies the full
table before applying the requested identity and point-in-time predicates, so
an unrelated malformed row cannot be hidden by a narrow selector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from django.db import DatabaseError
from django.db.models import Model
from django.utils import timezone

from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Unavailable,
)
from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1Observation,
    ExactCurrentEvidenceScopeSourceV1ObservationProvider,
)
from apps.research.infrastructure.evidence_models import (
    EvidenceScopeSourceV1ObservationModel,
)
from apps.research.infrastructure.evidence_scope_source_v1_observation_codec import (
    EvidenceScopeSourceV1ObservationCodecError,
    decode_evidence_scope_source_v1_observation,
    encode_evidence_scope_source_v1_observation,
)


class DjangoEvidenceScopeSourceV1ObservationUnavailable(EvidenceScopeSourceV1Unavailable):
    """The observation ledger or authoritative PIT clock is unavailable."""


class DjangoEvidenceScopeSourceV1ObservationCorruption(EvidenceScopeSourceV1Corruption):
    """The observation ledger contains substituted or non-canonical data."""


class EvidenceScopeSourceV1ObservationClock(Protocol):
    """Provide the authoritative server clock for PIT selectors."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoEvidenceScopeSourceV1ObservationClock:
    """Django timezone-backed observation clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoEvidenceScopeSourceV1ObservationRepository(
    ExactCurrentEvidenceScopeSourceV1ObservationProvider
):
    """Read exact current observations from a fully restored ledger.

    The provider returns only an active observation knowable at ``as_of``.
    Revoked, expired, not-yet-recorded, missing, or selector-mismatched rows
    return ``None``; no predecessor or stale-row fallback is permitted.
    """

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceScopeSourceV1ObservationClock | None = None,
    ) -> None:
        """Bind the read port to one explicit Django database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("Evidence observation database alias is invalid")
        self._using = using
        self._clock = clock or DjangoEvidenceScopeSourceV1ObservationClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity shared with a lifecycle UOW."""

        return f"django:{self._using}"

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Observation | None:
        """Return one exact active observation at a non-future PIT cutoff."""

        _require_selector(
            observation_id=observation_id,
            observation_version=observation_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )
        self._require_pit_cutoff(as_of)
        try:
            records = self._restore_full_world()
        except (
            DjangoEvidenceScopeSourceV1ObservationUnavailable,
            DjangoEvidenceScopeSourceV1ObservationCorruption,
        ):
            raise
        except DatabaseError as error:
            raise DjangoEvidenceScopeSourceV1ObservationUnavailable(
                "Evidence scope observation ledger is unavailable"
            ) from error

        matches = tuple(
            record
            for record in records
            if (
                record.observation_id == observation_id
                and record.observation_version == observation_version
                and record.content_hash == expected_content_hash
            )
        )
        if len(matches) > 1:
            raise DjangoEvidenceScopeSourceV1ObservationCorruption(
                "observation exact identity has multiple matches"
            )
        if not matches:
            return None
        observation = matches[0]
        if observation.recorded_at > as_of:
            return None
        if not observation.is_current_at(as_of):
            return None
        return observation

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        """Reject an ``as_of`` value beyond the authoritative server clock."""

        now = self._server_now()
        if as_of > now:
            raise DjangoEvidenceScopeSourceV1ObservationUnavailable(
                "future Evidence scope observation as_of is not permitted"
            )

    def _server_now(self) -> datetime:
        """Read and validate the injected authoritative server clock."""

        try:
            now = self._clock.now()
            _require_aware(now, "Evidence scope observation server clock")
        except (TypeError, ValueError) as error:
            raise DjangoEvidenceScopeSourceV1ObservationUnavailable(
                "Evidence scope observation server clock is unavailable"
            ) from error
        except Exception as error:
            raise DjangoEvidenceScopeSourceV1ObservationUnavailable(
                "Evidence scope observation server clock is unavailable"
            ) from error
        return now

    def _restore_full_world(self) -> tuple[EvidenceScopeSourceV1Observation, ...]:
        """Restore every row and verify scalar headers before selecting any row."""

        rows = tuple(
            EvidenceScopeSourceV1ObservationModel._default_manager.using(self._using).order_by("pk")
        )
        if not rows:
            return ()
        records = tuple(_restore_row(row) for row in rows)
        identities: set[tuple[str, str]] = set()
        content_hashes: set[str] = set()
        for record in records:
            identity = (record.observation_id, record.observation_version)
            if identity in identities:
                raise DjangoEvidenceScopeSourceV1ObservationCorruption(
                    "observation identity is duplicated"
                )
            if record.content_hash in content_hashes:
                raise DjangoEvidenceScopeSourceV1ObservationCorruption(
                    "observation content hash is duplicated"
                )
            identities.add(identity)
            content_hashes.add(record.content_hash)
        return records


def _restore_row(model: Model) -> EvidenceScopeSourceV1Observation:
    """Decode one model row and compare every persisted scalar to its payload."""

    if type(model) is not EvidenceScopeSourceV1ObservationModel:
        raise DjangoEvidenceScopeSourceV1ObservationCorruption(
            "observation row type is substituted"
        )
    try:
        observation = decode_evidence_scope_source_v1_observation(model.canonical_payload)
    except EvidenceScopeSourceV1ObservationCodecError as error:
        raise DjangoEvidenceScopeSourceV1ObservationCorruption(
            "observation canonical payload cannot be restored"
        ) from error
    expected = _observation_values(observation)
    if any(getattr(model, field_name) != value for field_name, value in expected.items()):
        raise DjangoEvidenceScopeSourceV1ObservationCorruption(
            "observation headers do not match canonical payload"
        )
    return observation


def _observation_values(
    observation: EvidenceScopeSourceV1Observation,
) -> dict[str, object]:
    """Project the exact DTO into the model's scalar header columns."""

    artifact = observation.artifact
    return {
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "owner_id": observation.owner_id,
        "tenant_id": observation.tenant_id,
        "account_id": observation.account_id,
        "actor_id": observation.actor_id,
        "artifact_owner": artifact.owner,
        "artifact_type": artifact.artifact_type,
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "artifact_content_hash": artifact.content_hash,
        "status": observation.status,
        "recorded_at": observation.recorded_at,
        "valid_until": observation.valid_until,
        "canonical_payload": encode_evidence_scope_source_v1_observation(observation),
        "content_hash": observation.content_hash,
    }


def _require_selector(
    *,
    observation_id: str,
    observation_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> None:
    """Validate all provider selectors before querying the ledger."""

    _require_token(observation_id, "observation_id")
    _require_token(observation_version, "observation_version")
    _require_digest(expected_content_hash, "expected_content_hash")
    _require_aware(as_of, "as_of")


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_digest(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "DjangoEvidenceScopeSourceV1ObservationClock",
    "DjangoEvidenceScopeSourceV1ObservationCorruption",
    "DjangoEvidenceScopeSourceV1ObservationRepository",
    "DjangoEvidenceScopeSourceV1ObservationUnavailable",
    "EvidenceScopeSourceV1ObservationClock",
]
