"""Candidate-bound audit archive and memory-only restore contracts.

The use cases in this module are deliberately inert without both a provider-
issued reader context and an exact deployed-candidate provider.  Building an
archive only reads one bounded ledger window; restoring it creates an isolated
in-memory namespace and never deletes source rows, writes a database, changes
runtime state, or claims production acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.system_audit_event import AuditScopeRef, JSONValue, SystemAuditEvent

AUDIT_ARCHIVE_SCHEMA_VERSION: Final[str] = "system-audit-archive.v1"
AUDIT_ARCHIVE_RESTORE_SCHEMA_VERSION: Final[str] = "system-audit-archive-isolated-restore.v1"
AUDIT_ARCHIVE_MAX_MEMBERS: Final[int] = 10_000

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_OCI_REVISION_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")


class SystemAuditArchiveError(ValueError):
    """Base error for archive validation and rehearsal operations."""


class SystemAuditArchiveUnavailable(SystemAuditArchiveError):
    """The requested scoped archive or restore is not currently available."""


class SystemAuditArchiveCorruption(SystemAuditArchiveError):
    """Archive source data or encoded content violated the closed contract."""


def _require_token(value: object, field: str) -> None:
    if type(value) is not str or _TOKEN_RE.fullmatch(value) is None:
        raise SystemAuditArchiveCorruption(f"{field}_invalid")


def _require_digest(value: object, field: str) -> None:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise SystemAuditArchiveCorruption(f"{field}_invalid")


def _require_aware(value: object, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SystemAuditArchiveCorruption(f"{field}_must_be_timezone_aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "archive_datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_value(value: JSONValue) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SystemAuditArchiveCorruption("archive_non_finite_number")
        return value
    if isinstance(value, Mapping):
        return {key: _json_value(child) for key, child in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    raise SystemAuditArchiveCorruption("archive_json_value_invalid")


def _canonical_bytes(value: JSONValue) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(domain: str, value: JSONValue) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\0" + _canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class SystemAuditArchiveCandidate:
    """Exact immutable deployment identity bound to an archive."""

    commit: str
    version: str
    oci_revision: str
    matrix_sha256: str

    def __post_init__(self) -> None:
        if _COMMIT_RE.fullmatch(self.commit) is None:
            raise SystemAuditArchiveCorruption("archive_candidate_commit_invalid")
        _require_token(self.version, "archive_candidate_version")
        if _OCI_REVISION_RE.fullmatch(self.oci_revision) is None:
            raise SystemAuditArchiveCorruption("archive_candidate_oci_revision_invalid")
        _require_digest(self.matrix_sha256, "archive_candidate_matrix_sha256")

    def to_payload(self) -> Mapping[str, JSONValue]:
        """Return the exact candidate JSON projection."""

        return {
            "commit": self.commit,
            "matrix_sha256": self.matrix_sha256,
            "oci_revision": self.oci_revision,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class SystemAuditArchiveStreamAnchor:
    """Closed predecessor and replay summary for one archived stream slice."""

    stream_id: str
    first_sequence_no: int
    first_predecessor_hash: str | None
    last_sequence_no: int
    last_content_hash: str
    member_count: int
    replay_sha256: str

    def __post_init__(self) -> None:
        _require_token(self.stream_id, "archive_stream_id")
        if (
            type(self.first_sequence_no) is not int
            or type(self.last_sequence_no) is not int
            or type(self.member_count) is not int
            or self.first_sequence_no < 1
            or self.last_sequence_no < self.first_sequence_no
            or self.member_count != self.last_sequence_no - self.first_sequence_no + 1
        ):
            raise SystemAuditArchiveCorruption("archive_stream_sequence_invalid")
        if self.first_sequence_no == 1:
            if self.first_predecessor_hash is not None:
                raise SystemAuditArchiveCorruption("archive_root_predecessor_invalid")
        else:
            _require_digest(
                self.first_predecessor_hash,
                "archive_external_predecessor_hash",
            )
        _require_digest(self.last_content_hash, "archive_last_content_hash")
        _require_digest(self.replay_sha256, "archive_stream_replay_sha256")

    def to_payload(self) -> Mapping[str, JSONValue]:
        """Return the exact stream-anchor JSON projection."""

        return {
            "first_predecessor_hash": self.first_predecessor_hash,
            "first_sequence_no": self.first_sequence_no,
            "last_content_hash": self.last_content_hash,
            "last_sequence_no": self.last_sequence_no,
            "member_count": self.member_count,
            "replay_sha256": self.replay_sha256,
            "stream_id": self.stream_id,
        }


@dataclass(frozen=True, slots=True)
class SystemAuditArchiveManifest:
    """Immutable candidate, scope, window and chain summary."""

    schema_version: str
    candidate: SystemAuditArchiveCandidate
    scope: AuditScopeRef
    window_started_at: datetime
    window_ended_at: datetime
    created_at: datetime
    member_count: int
    source_sha256: str
    streams: tuple[SystemAuditArchiveStreamAnchor, ...]
    manifest_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != AUDIT_ARCHIVE_SCHEMA_VERSION:
            raise SystemAuditArchiveCorruption("archive_schema_version_invalid")
        if not isinstance(self.candidate, SystemAuditArchiveCandidate):
            raise SystemAuditArchiveCorruption("archive_candidate_type_invalid")
        if not isinstance(self.scope, AuditScopeRef):
            raise SystemAuditArchiveCorruption("archive_scope_type_invalid")
        for field, value in (
            ("window_started_at", self.window_started_at),
            ("window_ended_at", self.window_ended_at),
            ("created_at", self.created_at),
        ):
            _require_aware(value, f"archive_{field}")
        if not self.window_started_at < self.window_ended_at <= self.created_at:
            raise SystemAuditArchiveCorruption("archive_window_order_invalid")
        if (
            type(self.member_count) is not int
            or not 1 <= self.member_count <= AUDIT_ARCHIVE_MAX_MEMBERS
        ):
            raise SystemAuditArchiveCorruption("archive_member_count_invalid")
        if type(self.streams) is not tuple or not self.streams:
            raise SystemAuditArchiveCorruption("archive_streams_invalid")
        if any(not isinstance(anchor, SystemAuditArchiveStreamAnchor) for anchor in self.streams):
            raise SystemAuditArchiveCorruption("archive_stream_anchor_type_invalid")
        stream_ids = tuple(anchor.stream_id for anchor in self.streams)
        if stream_ids != tuple(sorted(stream_ids)) or len(stream_ids) != len(set(stream_ids)):
            raise SystemAuditArchiveCorruption("archive_stream_order_invalid")
        if sum(anchor.member_count for anchor in self.streams) != self.member_count:
            raise SystemAuditArchiveCorruption("archive_stream_member_count_mismatch")
        _require_digest(self.source_sha256, "archive_source_sha256")
        _require_digest(self.manifest_sha256, "archive_manifest_sha256")

    @property
    def archive_id(self) -> str:
        """Return the content-derived archive identity."""

        return f"audit-archive:{self.manifest_sha256}"

    def hash_payload(self) -> Mapping[str, JSONValue]:
        """Return the manifest body used to derive ``manifest_sha256``."""

        return {
            "candidate": self.candidate.to_payload(),
            "created_at": _utc_text(self.created_at),
            "member_count": self.member_count,
            "schema_version": self.schema_version,
            "scope": self.scope.to_payload(),
            "source_sha256": self.source_sha256,
            "streams": [anchor.to_payload() for anchor in self.streams],
            "window_ended_at": _utc_text(self.window_ended_at),
            "window_started_at": _utc_text(self.window_started_at),
        }

    def to_payload(self) -> Mapping[str, JSONValue]:
        """Return the complete manifest including its digest."""

        return {**self.hash_payload(), "manifest_sha256": self.manifest_sha256}


@dataclass(frozen=True, slots=True)
class SystemAuditArchiveBundle:
    """Canonical manifest and ordered immutable event members."""

    manifest: SystemAuditArchiveManifest
    events: tuple[SystemAuditEvent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SystemAuditArchiveManifest):
            raise SystemAuditArchiveCorruption("archive_manifest_type_invalid")
        if type(self.events) is not tuple or not self.events:
            raise SystemAuditArchiveCorruption("archive_events_invalid")
        expected = _build_manifest(
            candidate=self.manifest.candidate,
            scope=self.manifest.scope,
            window_started_at=self.manifest.window_started_at,
            window_ended_at=self.manifest.window_ended_at,
            created_at=self.manifest.created_at,
            events=self.events,
        )
        if expected != self.manifest:
            raise SystemAuditArchiveCorruption("archive_manifest_content_mismatch")

    def to_payload(self) -> Mapping[str, JSONValue]:
        """Return the exact archive JSON projection."""

        return {
            "events": [event.to_payload() for event in self.events],
            "manifest": self.manifest.to_payload(),
            "schema_version": AUDIT_ARCHIVE_SCHEMA_VERSION,
        }


class SystemAuditArchiveSource(Protocol):
    """Read one bounded scoped ledger window for archive construction."""

    def list_archive_window(
        self,
        *,
        window_started_at: datetime,
        window_ended_at: datetime,
        as_of: datetime,
        scope: AuditScopeRef,
        limit: int,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return globally ordered events, fetching at most ``limit`` members."""


class SystemAuditArchiveCandidateProvider(Protocol):
    """Resolve the deployed immutable candidate outside caller-controlled input."""

    def get_current_candidate(self, *, as_of: datetime) -> SystemAuditArchiveCandidate | None:
        """Return the exact active candidate or ``None`` without fallback."""


class SystemAuditArchiveCodec(Protocol):
    """Strict byte codec used by the isolated restore use case."""

    def encode(self, bundle: SystemAuditArchiveBundle) -> bytes:
        """Encode one canonical bundle."""

    def decode(self, payload: bytes) -> SystemAuditArchiveBundle:
        """Decode one exact canonical bundle or fail closed."""


@dataclass(frozen=True, slots=True)
class BuildSystemAuditArchiveCommand:
    """Exact authority, candidate and time window for one archive read."""

    expected_candidate: SystemAuditArchiveCandidate
    window_started_at: datetime
    window_ended_at: datetime
    as_of: datetime
    reader: SystemAuditReaderContext
    max_members: int = 1_000

    def __post_init__(self) -> None:
        if not isinstance(self.expected_candidate, SystemAuditArchiveCandidate):
            raise SystemAuditArchiveCorruption("archive_expected_candidate_invalid")
        if not isinstance(self.reader, SystemAuditReaderContext):
            raise SystemAuditArchiveCorruption("archive_reader_invalid")
        for field, value in (
            ("window_started_at", self.window_started_at),
            ("window_ended_at", self.window_ended_at),
            ("as_of", self.as_of),
        ):
            _require_aware(value, f"archive_command_{field}")
        if not self.window_started_at < self.window_ended_at <= self.as_of:
            raise SystemAuditArchiveCorruption("archive_command_window_order_invalid")
        if (
            type(self.max_members) is not int
            or not 1 <= self.max_members <= AUDIT_ARCHIVE_MAX_MEMBERS
        ):
            raise SystemAuditArchiveCorruption("archive_command_member_limit_invalid")


class BuildSystemAuditArchiveUseCase:
    """Build one deterministic archive without writing or deleting ledger rows."""

    def __init__(
        self,
        *,
        source: SystemAuditArchiveSource,
        candidate_provider: SystemAuditArchiveCandidateProvider,
    ) -> None:
        self._source = source
        self._candidate_provider = candidate_provider

    def execute(self, command: BuildSystemAuditArchiveCommand) -> SystemAuditArchiveBundle:
        """Read and validate an exact candidate-bound archive window."""

        if not command.reader.can_read_at(command.as_of):
            raise SystemAuditArchiveUnavailable("archive_authority_unavailable")
        _require_current_candidate(
            provider=self._candidate_provider,
            expected=command.expected_candidate,
            as_of=command.as_of,
        )
        try:
            events = self._source.list_archive_window(
                window_started_at=command.window_started_at,
                window_ended_at=command.window_ended_at,
                as_of=command.as_of,
                scope=command.reader.scope,
                limit=command.max_members + 1,
            )
        except SystemAuditArchiveError:
            raise
        except Exception:
            raise SystemAuditArchiveUnavailable("archive_source_unavailable") from None
        if type(events) is not tuple:
            raise SystemAuditArchiveCorruption("archive_source_type_invalid")
        if not events:
            raise SystemAuditArchiveUnavailable("archive_window_empty")
        if len(events) > command.max_members:
            raise SystemAuditArchiveUnavailable("archive_member_limit_exceeded")
        _require_current_candidate(
            provider=self._candidate_provider,
            expected=command.expected_candidate,
            as_of=command.as_of,
        )
        manifest = _build_manifest(
            candidate=command.expected_candidate,
            scope=command.reader.scope,
            window_started_at=command.window_started_at,
            window_ended_at=command.window_ended_at,
            created_at=command.as_of,
            events=events,
        )
        return SystemAuditArchiveBundle(manifest=manifest, events=events)


@dataclass(frozen=True, slots=True)
class RestoreSystemAuditArchiveCommand:
    """Authorized memory-only restore and exact stream replay request."""

    payload: bytes
    expected_candidate: SystemAuditArchiveCandidate
    reader: SystemAuditReaderContext
    as_of: datetime
    replay_stream_id: str

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes or not self.payload:
            raise SystemAuditArchiveCorruption("archive_restore_payload_invalid")
        if not isinstance(self.expected_candidate, SystemAuditArchiveCandidate):
            raise SystemAuditArchiveCorruption("archive_restore_candidate_invalid")
        if not isinstance(self.reader, SystemAuditReaderContext):
            raise SystemAuditArchiveCorruption("archive_restore_reader_invalid")
        _require_aware(self.as_of, "archive_restore_as_of")
        _require_token(self.replay_stream_id, "archive_restore_stream_id")


@dataclass(frozen=True, slots=True)
class RestoreSystemAuditArchiveResult:
    """Secret-free hashes and counts from one isolated replay."""

    archive_id: str
    artifact_sha256: str
    manifest_sha256: str
    source_sha256: str
    restored_sha256: str
    member_count: int
    replay_stream_id: str
    replay_member_count: int
    replay_sha256: str
    outcome: str = "success"
    isolation_mode: str = "memory_only"
    production_claim: bool = False
    production_ready: bool = False

    def __post_init__(self) -> None:
        _require_token(self.archive_id, "archive_restore_archive_id")
        for field, value in (
            ("artifact_sha256", self.artifact_sha256),
            ("manifest_sha256", self.manifest_sha256),
            ("source_sha256", self.source_sha256),
            ("restored_sha256", self.restored_sha256),
            ("replay_sha256", self.replay_sha256),
        ):
            _require_digest(value, f"archive_restore_{field}")
        if self.source_sha256 != self.restored_sha256:
            raise SystemAuditArchiveCorruption("archive_restore_hash_mismatch")
        if type(self.member_count) is not int or self.member_count < 1:
            raise SystemAuditArchiveCorruption("archive_restore_member_count_invalid")
        if type(self.replay_member_count) is not int or self.replay_member_count < 1:
            raise SystemAuditArchiveCorruption("archive_restore_replay_count_invalid")
        _require_token(self.replay_stream_id, "archive_restore_result_stream_id")
        if (
            self.outcome != "success"
            or self.isolation_mode != "memory_only"
            or self.production_claim
            or self.production_ready
        ):
            raise SystemAuditArchiveCorruption("archive_restore_claim_invalid")

    def to_dict(self) -> dict[str, object]:
        """Return the bounded report projection used by later evidence tooling."""

        return {
            "archive_id": self.archive_id,
            "artifact_sha256": self.artifact_sha256,
            "isolation_mode": self.isolation_mode,
            "manifest_sha256": self.manifest_sha256,
            "member_count": self.member_count,
            "outcome": self.outcome,
            "production_claim": self.production_claim,
            "production_ready": self.production_ready,
            "replay_member_count": self.replay_member_count,
            "replay_sha256": self.replay_sha256,
            "replay_stream_id": self.replay_stream_id,
            "restored_sha256": self.restored_sha256,
            "schema_version": AUDIT_ARCHIVE_RESTORE_SCHEMA_VERSION,
            "source_sha256": self.source_sha256,
        }


class RestoreSystemAuditArchiveUseCase:
    """Decode and replay an archive inside a disposable in-memory namespace."""

    def __init__(
        self,
        *,
        codec: SystemAuditArchiveCodec,
        candidate_provider: SystemAuditArchiveCandidateProvider,
    ) -> None:
        self._codec = codec
        self._candidate_provider = candidate_provider

    def execute(self, command: RestoreSystemAuditArchiveCommand) -> RestoreSystemAuditArchiveResult:
        """Verify all bytes and replay one exact stream without external writes."""

        if not command.reader.can_read_at(command.as_of):
            raise SystemAuditArchiveUnavailable("archive_restore_authority_unavailable")
        _require_current_candidate(
            provider=self._candidate_provider,
            expected=command.expected_candidate,
            as_of=command.as_of,
        )
        try:
            bundle = self._codec.decode(command.payload)
        except SystemAuditArchiveError:
            raise
        except Exception:
            raise SystemAuditArchiveCorruption("archive_restore_payload_invalid") from None
        _require_current_candidate(
            provider=self._candidate_provider,
            expected=command.expected_candidate,
            as_of=command.as_of,
        )
        if bundle.manifest.candidate != command.expected_candidate:
            raise SystemAuditArchiveUnavailable("archive_restore_candidate_substitution")
        if bundle.manifest.scope != command.reader.scope:
            raise SystemAuditArchiveUnavailable("archive_restore_scope_substitution")
        if bundle.manifest.created_at > command.as_of:
            raise SystemAuditArchiveUnavailable("archive_restore_future_archive")

        namespace = {
            anchor.stream_id: tuple(
                event for event in bundle.events if event.stream_id == anchor.stream_id
            )
            for anchor in bundle.manifest.streams
        }
        replay = namespace.get(command.replay_stream_id)
        if not replay:
            raise SystemAuditArchiveUnavailable("archive_replay_stream_unavailable")
        restored_sha256 = _events_digest(bundle.events)
        replay_sha256 = _replay_digest(replay)
        return RestoreSystemAuditArchiveResult(
            archive_id=bundle.manifest.archive_id,
            artifact_sha256=hashlib.sha256(command.payload).hexdigest(),
            manifest_sha256=bundle.manifest.manifest_sha256,
            source_sha256=bundle.manifest.source_sha256,
            restored_sha256=restored_sha256,
            member_count=len(bundle.events),
            replay_stream_id=command.replay_stream_id,
            replay_member_count=len(replay),
            replay_sha256=replay_sha256,
        )


def _require_current_candidate(
    *,
    provider: SystemAuditArchiveCandidateProvider,
    expected: SystemAuditArchiveCandidate,
    as_of: datetime,
) -> None:
    try:
        current = provider.get_current_candidate(as_of=as_of)
    except Exception:
        raise SystemAuditArchiveUnavailable("archive_candidate_identity_unavailable") from None
    if current is None:
        raise SystemAuditArchiveUnavailable("archive_candidate_identity_unavailable")
    if not isinstance(current, SystemAuditArchiveCandidate):
        raise SystemAuditArchiveCorruption("archive_candidate_provider_substitution")
    if current != expected:
        raise SystemAuditArchiveUnavailable("archive_candidate_drift")


def _event_key(event: SystemAuditEvent) -> tuple[datetime, str, int, str, str]:
    return (
        event.recorded_at,
        event.stream_id,
        event.sequence_no,
        event.event_id,
        event.event_version,
    )


def _validate_events(
    events: tuple[SystemAuditEvent, ...],
    *,
    scope: AuditScopeRef,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> None:
    identities: set[tuple[str, str]] = set()
    content_hashes: set[str] = set()
    ordering: list[tuple[datetime, str, int, str, str]] = []
    for event in events:
        if not isinstance(event, SystemAuditEvent):
            raise SystemAuditArchiveCorruption("archive_event_type_invalid")
        if event.scope != scope:
            raise SystemAuditArchiveCorruption("archive_scope_substitution")
        if not window_started_at <= event.recorded_at < window_ended_at:
            raise SystemAuditArchiveCorruption("archive_window_substitution")
        try:
            event.validate_hashes()
        except (TypeError, ValueError):
            raise SystemAuditArchiveCorruption("archive_event_invalid") from None
        identity = (event.event_id, event.event_version)
        if identity in identities or event.content_hash in content_hashes:
            raise SystemAuditArchiveCorruption("archive_duplicate_event")
        identities.add(identity)
        content_hashes.add(event.content_hash)
        ordering.append(_event_key(event))
    if ordering != sorted(ordering):
        raise SystemAuditArchiveCorruption("archive_source_order_invalid")


def _events_digest(events: tuple[SystemAuditEvent, ...]) -> str:
    return _digest(
        "audit.system-audit-archive.source.v1",
        [event.to_payload() for event in events],
    )


def _replay_digest(events: tuple[SystemAuditEvent, ...]) -> str:
    return _digest(
        "audit.system-audit-archive.replay.v1",
        [event.to_payload() for event in events],
    )


def _stream_anchors(
    events: tuple[SystemAuditEvent, ...],
) -> tuple[SystemAuditArchiveStreamAnchor, ...]:
    grouped: dict[str, list[SystemAuditEvent]] = {}
    for event in events:
        grouped.setdefault(event.stream_id, []).append(event)
    anchors: list[SystemAuditArchiveStreamAnchor] = []
    for stream_id in sorted(grouped):
        stream = tuple(sorted(grouped[stream_id], key=lambda event: event.sequence_no))
        expected_sequences = tuple(range(stream[0].sequence_no, stream[-1].sequence_no + 1))
        if tuple(event.sequence_no for event in stream) != expected_sequences:
            raise SystemAuditArchiveCorruption("archive_stream_sequence_gap")
        for previous, current in zip(stream, stream[1:], strict=False):
            if current.predecessor_hash != previous.content_hash:
                raise SystemAuditArchiveCorruption("archive_stream_predecessor_mismatch")
            if current.recorded_at < previous.recorded_at:
                raise SystemAuditArchiveCorruption("archive_stream_clock_moved_backwards")
        anchors.append(
            SystemAuditArchiveStreamAnchor(
                stream_id=stream_id,
                first_sequence_no=stream[0].sequence_no,
                first_predecessor_hash=stream[0].predecessor_hash,
                last_sequence_no=stream[-1].sequence_no,
                last_content_hash=stream[-1].content_hash,
                member_count=len(stream),
                replay_sha256=_replay_digest(stream),
            )
        )
    return tuple(anchors)


def _build_manifest(
    *,
    candidate: SystemAuditArchiveCandidate,
    scope: AuditScopeRef,
    window_started_at: datetime,
    window_ended_at: datetime,
    created_at: datetime,
    events: tuple[SystemAuditEvent, ...],
) -> SystemAuditArchiveManifest:
    _validate_events(
        events,
        scope=scope,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
    )
    source_sha256 = _events_digest(events)
    anchors = _stream_anchors(events)
    provisional = SystemAuditArchiveManifest(
        schema_version=AUDIT_ARCHIVE_SCHEMA_VERSION,
        candidate=candidate,
        scope=scope,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        created_at=created_at,
        member_count=len(events),
        source_sha256=source_sha256,
        streams=anchors,
        manifest_sha256="0" * 64,
    )
    manifest_sha256 = _digest(
        "audit.system-audit-archive.manifest.v1",
        provisional.hash_payload(),
    )
    return SystemAuditArchiveManifest(
        schema_version=provisional.schema_version,
        candidate=provisional.candidate,
        scope=provisional.scope,
        window_started_at=provisional.window_started_at,
        window_ended_at=provisional.window_ended_at,
        created_at=provisional.created_at,
        member_count=provisional.member_count,
        source_sha256=provisional.source_sha256,
        streams=provisional.streams,
        manifest_sha256=manifest_sha256,
    )


__all__ = [
    "AUDIT_ARCHIVE_MAX_MEMBERS",
    "AUDIT_ARCHIVE_RESTORE_SCHEMA_VERSION",
    "AUDIT_ARCHIVE_SCHEMA_VERSION",
    "BuildSystemAuditArchiveCommand",
    "BuildSystemAuditArchiveUseCase",
    "RestoreSystemAuditArchiveCommand",
    "RestoreSystemAuditArchiveResult",
    "RestoreSystemAuditArchiveUseCase",
    "SystemAuditArchiveBundle",
    "SystemAuditArchiveCandidate",
    "SystemAuditArchiveCandidateProvider",
    "SystemAuditArchiveCodec",
    "SystemAuditArchiveCorruption",
    "SystemAuditArchiveError",
    "SystemAuditArchiveManifest",
    "SystemAuditArchiveSource",
    "SystemAuditArchiveStreamAnchor",
    "SystemAuditArchiveUnavailable",
]
