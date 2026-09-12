"""Current Account owner authorization for request-only Research Evidence reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeAlias, TypeVar

from django.utils import timezone

from apps.account.application.owner_tenant_authority_v2 import (
    CurrentOwnerTenantAuthorityV2,
    GetCurrentOwnerTenantAuthorityV2Command,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Unavailable,
)
from apps.research.application.evidence_scope import (
    EvidenceScopeCorruption,
    EvidenceScopeUnavailable,
)
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)
from apps.research.evidence_composition import EvidenceReadPort

_Result = TypeVar("_Result")


@dataclass(frozen=True, slots=True)
class _RequestEvidenceScope:
    """Ephemeral sealed binding used only during one materializing callback."""

    authority_id: str
    authority_version: str
    authority_content_hash: str
    actor_id: str
    user_id: int
    authentication_context_hash: str
    source_id: str
    source_version: str
    source_content_hash: str
    artifact: ArtifactRef
    recorded_at: datetime
    valid_until: datetime
    binding_hash: str = ""

    def __post_init__(self) -> None:
        """Seal the complete request binding without exposing a reusable grant."""

        for name in (
            "authority_id",
            "authority_version",
            "actor_id",
            "source_id",
            "source_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"{name} must be a bounded canonical token")
        for name in (
            "authority_content_hash",
            "authentication_context_hash",
            "source_content_hash",
        ):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be exact ArtifactRef")
        self.artifact.__post_init__()
        for name in ("recorded_at", "valid_until"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.recorded_at >= self.valid_until:
            raise ValueError("request Evidence scope validity window is invalid")
        expected = self._compute_hash()
        if self.binding_hash not in ("", expected):
            raise ValueError("request Evidence scope binding hash is invalid")
        object.__setattr__(self, "binding_hash", expected)

    def _compute_hash(self) -> str:
        """Return the canonical in-memory binding seal."""

        payload = {
            "authority_content_hash": self.authority_content_hash,
            "authority_id": self.authority_id,
            "authority_version": self.authority_version,
            "actor_id": self.actor_id,
            "artifact": self.artifact.to_payload(),
            "authentication_context_hash": self.authentication_context_hash,
            "recorded_at": _utc_text(self.recorded_at),
            "source_content_hash": self.source_content_hash,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "user_id": self.user_id,
            "valid_until": _utc_text(self.valid_until),
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(
            b"agomtradepro:owner-tenant-evidence-scope:v2\0" + encoded
        ).hexdigest()


def _utc_text(value: datetime) -> str:
    """Return a canonical UTC timestamp for the request-local seal."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class CurrentOwnerTenantAuthorityV2Reader(Protocol):
    """Account composition port retaining current source locks through a callback."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the server-bound transaction identity."""

    def with_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV2Command,
        operation: Callable[[CurrentOwnerTenantAuthorityV2], _Result],
    ) -> _Result | None:
        """Run a synchronous materializing operation under current owner locks."""


EvidenceReadTransactionRepository: TypeAlias = EvidenceReadPort


class EvidenceScopeClock(Protocol):
    """Trusted server clock used for the short request-local scope."""

    def now(self) -> datetime:
        """Return one timezone-aware current server timestamp."""


class DjangoEvidenceScopeClock:
    """Django timezone-backed clock for the Core composition boundary."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class OwnerTenantAuthorityV2EvidenceReadFacade:
    """Read exact Research evidence under a current Account owner decision.

    The Account callback is the transaction boundary.  This facade creates no
    durable scope source and never returns a reusable authorization grant.  A
    caller may request an historical Evidence PIT cutoff, but authorization is
    always established at the current server clock first.
    """

    __slots__ = (
        "_authority_reader",
        "_evidence_reader",
        "_authority_command",
        "_server_bound_artifacts",
        "_scope_ttl",
        "_clock",
    )

    def __init__(
        self,
        *,
        authority_reader: CurrentOwnerTenantAuthorityV2Reader,
        evidence_reader: EvidenceReadTransactionRepository,
        authority_command: GetCurrentOwnerTenantAuthorityV2Command,
        server_bound_artifacts: frozenset[ArtifactRef],
        scope_ttl: timedelta,
        using: str = "default",
        clock: EvidenceScopeClock | None = None,
    ) -> None:
        """Bind one Account decision selector to exact same-alias Evidence reads."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("Evidence authority database alias is invalid")
        expected_unit = f"django:{using}"
        if authority_reader.unit_of_work_key != expected_unit:
            raise ValueError("owner authority and Evidence repositories must share an alias")
        if evidence_reader.unit_of_work_key != expected_unit:
            raise ValueError("owner authority and Evidence repositories must share an alias")
        if type(authority_command) is not GetCurrentOwnerTenantAuthorityV2Command:
            raise TypeError(
                "authority_command must be exact GetCurrentOwnerTenantAuthorityV2Command"
            )
        authority_command.__post_init__()
        if type(server_bound_artifacts) is not frozenset or not server_bound_artifacts:
            raise TypeError("server_bound_artifacts must be a nonempty frozenset")
        validated_artifacts: set[ArtifactRef] = set()
        for artifact in server_bound_artifacts:
            if type(artifact) is not ArtifactRef:
                raise TypeError("server-bound artifact must be exact ArtifactRef")
            artifact.__post_init__()
            validated_artifacts.add(
                ArtifactRef(
                    owner=artifact.owner,
                    artifact_type=artifact.artifact_type,
                    artifact_id=artifact.artifact_id,
                    artifact_version=artifact.artifact_version,
                    content_hash=artifact.content_hash,
                )
            )
        if type(scope_ttl) is not timedelta or scope_ttl <= timedelta(0):
            raise ValueError("scope_ttl must be an exact positive timedelta")
        self._authority_reader = authority_reader
        self._evidence_reader = evidence_reader
        self._authority_command = authority_command
        self._server_bound_artifacts = frozenset(validated_artifacts)
        self._scope_ttl = scope_ttl
        self._clock = clock or DjangoEvidenceScopeClock()

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        evidence_as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Authorize now, then return one exact Research Operator PIT result."""

        artifact = ArtifactRef(
            owner="research",
            artifact_type="evidence_operator_spec",
            artifact_id=operator_id,
            artifact_version=operator_version,
            content_hash=expected_content_hash,
        )
        self._validate_evidence_cutoff(evidence_as_of)
        if artifact not in self._server_bound_artifacts:
            return None

        def read(scope: _RequestEvidenceScope) -> EvidenceOperatorSpec | None:
            self._require_scope_artifact(scope, artifact)
            return self._validate_operator(
                self._evidence_reader.get_operator_spec(
                    operator_id=operator_id,
                    operator_version=operator_version,
                    expected_content_hash=expected_content_hash,
                    as_of=evidence_as_of,
                ),
                artifact=artifact,
                as_of=evidence_as_of,
            )

        return self._run_current(artifact=artifact, evidence_as_of=evidence_as_of, operation=read)

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        evidence_as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Authorize now, then return one exact Research Track Record PIT result."""

        artifact = ArtifactRef(
            owner="research",
            artifact_type="track_record_snapshot",
            artifact_id=snapshot_id,
            artifact_version=snapshot_version,
            content_hash=expected_content_hash,
        )
        self._validate_evidence_cutoff(evidence_as_of)
        if artifact not in self._server_bound_artifacts:
            return None

        def read(scope: _RequestEvidenceScope) -> TrackRecordSnapshot | None:
            self._require_scope_artifact(scope, artifact)
            return self._validate_track(
                self._evidence_reader.get_track_record(
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    expected_content_hash=expected_content_hash,
                    as_of=evidence_as_of,
                ),
                artifact=artifact,
                as_of=evidence_as_of,
            )

        return self._run_current(artifact=artifact, evidence_as_of=evidence_as_of, operation=read)

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        evidence_as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Authorize now, then return one exact output Envelope at a PIT cutoff."""

        artifact = ArtifactRef(
            owner=output_owner,
            artifact_type=output_artifact_type,
            artifact_id=output_artifact_id,
            artifact_version=output_artifact_version,
            content_hash=expected_content_hash,
        )
        self._validate_evidence_cutoff(evidence_as_of)
        if artifact not in self._server_bound_artifacts:
            return None

        def read(scope: _RequestEvidenceScope) -> EvidenceEnvelope | None:
            self._require_scope_artifact(scope, artifact)
            return self._validate_envelope(
                self._evidence_reader.get_envelope(
                    output_owner=output_owner,
                    output_artifact_type=output_artifact_type,
                    output_artifact_id=output_artifact_id,
                    output_artifact_version=output_artifact_version,
                    expected_content_hash=expected_content_hash,
                    as_of=evidence_as_of,
                ),
                artifact=artifact,
                as_of=evidence_as_of,
            )

        return self._run_current(artifact=artifact, evidence_as_of=evidence_as_of, operation=read)

    def _run_current(
        self,
        *,
        artifact: ArtifactRef,
        evidence_as_of: datetime,
        operation: Callable[[_RequestEvidenceScope], _Result | None],
    ) -> _Result | None:
        """Execute one read while translating unavailable Account state safely."""

        start = self._server_now()
        if evidence_as_of > start:
            return None
        request_scope: _RequestEvidenceScope | None = None
        callback_after: datetime | None = None

        def read(current: CurrentOwnerTenantAuthorityV2) -> _Result | None:
            nonlocal callback_after, request_scope
            request_scope = self._prepare_scope(current, artifact)
            if request_scope is None:
                return None
            before = self._server_now()
            if request_scope.recorded_at < start:
                raise EvidenceScopeCorruption("current authority clock predates request clock")
            if (
                before < start
                or before < request_scope.recorded_at
                or before >= request_scope.valid_until
            ):
                return None
            result = operation(request_scope)
            after = self._server_now()
            callback_after = after
            if after < before or after >= request_scope.valid_until or after >= current.valid_until:
                return None
            return result

        try:
            result = self._authority_reader.with_current(self._authority_command, read)
        except (OwnerTenantAuthorityV2Unavailable, OwnerTenantAuthorityV2Conflict):
            return None
        except OwnerTenantAuthorityV2Corruption as error:
            raise EvidenceScopeCorruption("current owner authority is corrupt") from error
        except EvidenceScopeUnavailable:
            return None
        except EvidenceScopeCorruption:
            raise
        except (TypeError, ValueError):
            raise EvidenceScopeUnavailable("owner-scoped Evidence read is unavailable") from None
        except Exception:
            raise EvidenceScopeUnavailable("owner-scoped Evidence read is unavailable") from None
        if result is None:
            return None
        end = self._server_now()
        if request_scope is None or callback_after is None or end < callback_after:
            raise EvidenceScopeCorruption("Evidence scope clock moved backwards")
        if end >= request_scope.valid_until:
            return None
        return result

    def _prepare_scope(
        self,
        current: CurrentOwnerTenantAuthorityV2,
        artifact: ArtifactRef,
    ) -> _RequestEvidenceScope | None:
        """Validate current Account facts and return this request's short deadline."""

        if type(current) is not CurrentOwnerTenantAuthorityV2:
            raise EvidenceScopeCorruption("current owner authority type substitution")
        try:
            current.__post_init__()
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("current owner authority is invalid") from error
        selected = self._authority_command
        authority = current.authority
        if (
            authority.authority_id,
            authority.authority_version,
            authority.content_hash,
        ) != (
            selected.authority_id,
            selected.authority_version,
            selected.expected_content_hash,
        ):
            raise EvidenceScopeCorruption("current owner authority selector substitution")
        deadline = min(
            current.valid_until,
            current.observed_at + self._scope_ttl,
        )
        authentication = current.authentication
        return _RequestEvidenceScope(
            authority_id=authority.authority_id,
            authority_version=authority.authority_version,
            authority_content_hash=authority.content_hash,
            actor_id=authentication.actor_id,
            user_id=authentication.user_id,
            authentication_context_hash=authentication.authentication_context_hash,
            source_id=authentication.source_id,
            source_version=authentication.source_version,
            source_content_hash=authentication.source_content_hash,
            artifact=artifact,
            recorded_at=current.observed_at,
            valid_until=deadline,
        )

    @staticmethod
    def _require_scope_artifact(
        scope: _RequestEvidenceScope,
        artifact: ArtifactRef,
    ) -> None:
        """Keep every Evidence call bound to the private request seal."""

        if type(scope) is not _RequestEvidenceScope or scope.artifact != artifact:
            raise EvidenceScopeCorruption("request Evidence scope artifact substitution")

    def _server_now(self) -> datetime:
        """Return one exact aware clock value or fail closed."""

        try:
            value = self._clock.now()
        except Exception as error:
            raise EvidenceScopeCorruption("Evidence scope server clock is unavailable") from error
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise EvidenceScopeCorruption("Evidence scope server clock is invalid")
        return value

    @staticmethod
    def _validate_evidence_cutoff(value: datetime) -> None:
        """Require an explicit timezone-aware historical Evidence cutoff."""

        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("evidence_as_of must be timezone-aware")

    @staticmethod
    def _validate_operator(
        value: EvidenceOperatorSpec | None,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Validate exact operator identity and reject an obviously future DTO."""

        if value is None:
            return None
        if type(value) is not EvidenceOperatorSpec:
            raise EvidenceScopeCorruption("Evidence repository returned an invalid Operator type")
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("Evidence Operator payload is invalid") from error
        if value.artifact_ref != artifact or value.activated_at > as_of:
            raise EvidenceScopeCorruption("Evidence Operator selector or PIT mismatch")
        return value

    @staticmethod
    def _validate_track(
        value: TrackRecordSnapshot | None,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Validate exact Track Record identity and reject an obviously future DTO."""

        if value is None:
            return None
        if type(value) is not TrackRecordSnapshot:
            raise EvidenceScopeCorruption("Evidence repository returned an invalid Track type")
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("Evidence Track Record payload is invalid") from error
        if value.artifact_ref != artifact or value.evaluated_at > as_of:
            raise EvidenceScopeCorruption("Evidence Track selector or PIT mismatch")
        return value

    @staticmethod
    def _validate_envelope(
        value: EvidenceEnvelope | None,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Validate output identity while preserving the envelope content-hash axis."""

        if value is None:
            return None
        if type(value) is not EvidenceEnvelope:
            raise EvidenceScopeCorruption("Evidence repository returned an invalid Envelope type")
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("Evidence Envelope payload is invalid") from error
        output = value.output_artifact
        if (
            output.owner,
            output.artifact_type,
            output.artifact_id,
            output.artifact_version,
            value.content_hash,
        ) != (
            artifact.owner,
            artifact.artifact_type,
            artifact.artifact_id,
            artifact.artifact_version,
            artifact.content_hash,
        ) or value.evaluated_at > as_of:
            raise EvidenceScopeCorruption("Evidence Envelope selector or PIT mismatch")
        return value


__all__ = [
    "CurrentOwnerTenantAuthorityV2Reader",
    "DjangoEvidenceScopeClock",
    "EvidenceReadTransactionRepository",
    "EvidenceScopeClock",
    "OwnerTenantAuthorityV2EvidenceReadFacade",
]
