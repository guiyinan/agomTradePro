"""Public exact reads and private append capability for Research evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model, Q
from django.utils import timezone

from apps.research.domain.evidence_contracts import (
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)
from apps.research.infrastructure.evidence_codec import (
    EvidenceCodecError,
    decode_evidence_envelope,
    decode_evidence_operator_spec,
    decode_track_record_snapshot,
    encode_evidence_envelope,
    encode_evidence_operator_spec,
    encode_track_record_snapshot,
)
from apps.research.infrastructure.evidence_models import (
    EvidenceEnvelopeModel,
    EvidenceOperatorSpecModel,
    EvidenceTrackRecordModel,
    _activate_evidence_uow,
    _claim_evidence_insert,
)


class EvidenceRepositoryConflict(RuntimeError):
    """A stable evidence identity already has a different immutable winner."""


class EvidenceRepositoryCorruption(RuntimeError):
    """Persisted evidence headers, payload, or canonical hash disagree."""


class EvidenceRepositoryUnavailable(RuntimeError):
    """The evidence repository cannot establish an authoritative server clock."""


_EvidenceT = TypeVar("_EvidenceT", EvidenceOperatorSpec, TrackRecordSnapshot, EvidenceEnvelope)
_ModelT = TypeVar("_ModelT", bound=Model)


class EvidenceRepositoryClock(Protocol):
    """Authoritative clock used to reject impossible future PIT queries."""

    def now(self) -> datetime:
        """Return the current timezone-aware server time."""


class DjangoEvidenceRepositoryClock:
    """Django timezone-backed evidence repository clock."""

    def now(self) -> datetime:
        """Return the current server time."""

        return timezone.now()


class DjangoEvidenceRepository:
    """Public read-only exact/PIT provider; it owns no insert claim."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceRepositoryClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoEvidenceRepositoryClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity without exposing a writer token."""

        return f"django:{self._using}"

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Return one exact immutable operator version knowable at ``as_of``."""

        _query(operator_id, operator_version, expected_content_hash, as_of)
        self._require_pit_cutoff(as_of)
        rows = tuple(
            EvidenceOperatorSpecModel._default_manager.using(self._using).filter(
                Q(operator_id=operator_id, operator_version=operator_version)
                | Q(content_hash=expected_content_hash)
            )
        )
        return _exact_read(
            rows=rows,
            restore=_restore_operator,
            identity=lambda item: (
                item.operator_id,
                item.operator_version,
                item.content_hash,
            ),
            expected=(operator_id, operator_version, expected_content_hash),
            as_of=as_of,
        )

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Return one exact immutable Track Record knowable at ``as_of``."""

        _query(snapshot_id, snapshot_version, expected_content_hash, as_of)
        self._require_pit_cutoff(as_of)
        rows = tuple(
            EvidenceTrackRecordModel._default_manager.using(self._using).filter(
                Q(snapshot_id=snapshot_id, snapshot_version=snapshot_version)
                | Q(content_hash=expected_content_hash)
            )
        )
        return _exact_read(
            rows=rows,
            restore=_restore_track,
            identity=lambda item: (
                item.snapshot_id,
                item.snapshot_version,
                item.content_hash,
            ),
            expected=(snapshot_id, snapshot_version, expected_content_hash),
            as_of=as_of,
        )

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Return the exact Envelope winner for one output artifact version."""

        for token in (
            output_owner,
            output_artifact_type,
            output_artifact_id,
            output_artifact_version,
        ):
            _token(token)
        _hash(expected_content_hash)
        _aware(as_of)
        self._require_pit_cutoff(as_of)
        rows = tuple(
            EvidenceEnvelopeModel._default_manager.using(self._using).filter(
                Q(
                    output_owner=output_owner,
                    output_artifact_type=output_artifact_type,
                    output_artifact_id=output_artifact_id,
                    output_artifact_version=output_artifact_version,
                )
                | Q(content_hash=expected_content_hash)
            )
        )
        return _exact_read(
            rows=rows,
            restore=_restore_envelope,
            identity=lambda item: (
                item.output_artifact.owner,
                item.output_artifact.artifact_type,
                item.output_artifact.artifact_id,
                item.output_artifact.artifact_version,
                item.content_hash,
            ),
            expected=(
                output_owner,
                output_artifact_type,
                output_artifact_id,
                output_artifact_version,
                expected_content_hash,
            ),
            as_of=as_of,
        )

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        now = self._server_now()
        if as_of > now:
            raise ValueError("future evidence as_of is not permitted")

    def _server_now(self) -> datetime:
        """Return the validated repository clock or fail closed."""

        try:
            now = self._clock.now()
            _aware(now)
        except (TypeError, ValueError) as error:
            raise EvidenceRepositoryUnavailable(
                "evidence repository server clock is unavailable"
            ) from error
        except Exception as error:
            raise EvidenceRepositoryUnavailable(
                "evidence repository server clock is unavailable"
            ) from error
        return now


class _DjangoEvidenceStore(DjangoEvidenceRepository):
    """Private exact-append capability, intentionally absent from ``__all__``."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        token: object,
        using: str,
        clock: EvidenceRepositoryClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = token

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Activate the unforgeable insert claim inside one database transaction."""

        with transaction.atomic(using=self._using), _activate_evidence_uow(self._token):
            yield

    def append_operator_spec(
        self, spec: EvidenceOperatorSpec, *, recorded_at: datetime
    ) -> EvidenceOperatorSpec:
        """Append or replay one exact operator specification winner."""

        if type(spec) is not EvidenceOperatorSpec:
            raise TypeError("operator spec must be the exact Domain type")
        self._validate_recorded_at(recorded_at)
        payload = encode_evidence_operator_spec(spec)
        exact = decode_evidence_operator_spec(payload)
        values = _operator_values(exact, recorded_at)
        collisions = tuple(
            EvidenceOperatorSpecModel._default_manager.using(self._using).filter(
                Q(operator_id=exact.operator_id, operator_version=exact.operator_version)
                | Q(content_hash=exact.content_hash)
            )
        )
        if collisions:
            return _match(collisions, _restore_operator, exact)
        return self._insert(
            EvidenceOperatorSpecModel,
            values,
            lambda: tuple(
                EvidenceOperatorSpecModel._default_manager.using(self._using).filter(
                    Q(operator_id=exact.operator_id, operator_version=exact.operator_version)
                    | Q(content_hash=exact.content_hash)
                )
            ),
            _restore_operator,
            exact,
        )

    def append_track_record(
        self, snapshot: TrackRecordSnapshot, *, recorded_at: datetime
    ) -> TrackRecordSnapshot:
        """Append or replay one exact Track Record winner."""

        if type(snapshot) is not TrackRecordSnapshot:
            raise TypeError("Track Record must be the exact Domain type")
        self._validate_recorded_at(recorded_at)
        exact = decode_track_record_snapshot(encode_track_record_snapshot(snapshot))
        values = _track_values(exact, recorded_at)
        collisions = tuple(
            EvidenceTrackRecordModel._default_manager.using(self._using).filter(
                Q(snapshot_id=exact.snapshot_id, snapshot_version=exact.snapshot_version)
                | Q(content_hash=exact.content_hash)
            )
        )
        if collisions:
            return _match(collisions, _restore_track, exact)
        return self._insert(
            EvidenceTrackRecordModel,
            values,
            lambda: tuple(
                EvidenceTrackRecordModel._default_manager.using(self._using).filter(
                    Q(snapshot_id=exact.snapshot_id, snapshot_version=exact.snapshot_version)
                    | Q(content_hash=exact.content_hash)
                )
            ),
            _restore_track,
            exact,
        )

    def append_envelope(
        self, envelope: EvidenceEnvelope, *, recorded_at: datetime
    ) -> EvidenceEnvelope:
        """Append or replay one exact output-version Envelope winner."""

        if type(envelope) is not EvidenceEnvelope:
            raise TypeError("Envelope must be the exact Domain type")
        self._validate_recorded_at(recorded_at)
        exact = decode_evidence_envelope(encode_evidence_envelope(envelope))
        values = _envelope_values(exact, recorded_at)
        collisions = self._envelope_collisions(exact)
        if collisions:
            return _match(collisions, _restore_envelope, exact)
        return self._insert(
            EvidenceEnvelopeModel,
            values,
            lambda: self._envelope_collisions(exact),
            _restore_envelope,
            exact,
        )

    def _envelope_collisions(self, envelope: EvidenceEnvelope) -> tuple[EvidenceEnvelopeModel, ...]:
        output = envelope.output_artifact
        return tuple(
            EvidenceEnvelopeModel._default_manager.using(self._using).filter(
                Q(
                    output_owner=output.owner,
                    output_artifact_type=output.artifact_type,
                    output_artifact_id=output.artifact_id,
                    output_artifact_version=output.artifact_version,
                )
                | Q(content_hash=envelope.content_hash)
            )
        )

    def _validate_recorded_at(self, recorded_at: datetime) -> None:
        """Reject caller-supplied persistence times beyond the server clock."""

        try:
            _aware(recorded_at)
        except (TypeError, ValueError) as error:
            raise EvidenceRepositoryConflict(
                "evidence recorded_at must be timezone-aware"
            ) from error
        if recorded_at > self._server_now():
            raise EvidenceRepositoryConflict("evidence recorded_at cannot be in the future")

    def _insert(
        self,
        model_type: type[_ModelT],
        values: dict[str, object],
        collisions: Callable[[], tuple[_ModelT, ...]],
        restore: Callable[[_ModelT], _EvidenceT],
        expected: _EvidenceT,
    ) -> _EvidenceT:
        if _active_token(self._token) is False:
            raise EvidenceRepositoryConflict("evidence append requires its private atomic unit")
        model = model_type(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_evidence_insert(
                    token=self._token, model_type=model_type, expected_values=values
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = collisions()
            if not rows:
                raise EvidenceRepositoryConflict("evidence append has no exact winner") from error
            return _match(rows, restore, expected)
        return restore(model)


def _active_token(token: object) -> bool:
    """Check a claim by entering no state; actual enforcement remains model-side."""

    from apps.research.infrastructure.evidence_models import _ACTIVE_EVIDENCE_UOW

    return _ACTIVE_EVIDENCE_UOW.get() is token


def _build_evidence_store(
    *, using: str = "default", clock: EvidenceRepositoryClock | None = None
) -> _DjangoEvidenceStore:
    """Build a private store without exporting its unforgeable insert token."""

    return _DjangoEvidenceStore(token=object(), using=using, clock=clock)


def _exact_read(
    *,
    rows: tuple[_ModelT, ...],
    restore: Callable[[_ModelT], _EvidenceT],
    identity: Callable[[_EvidenceT], tuple[object, ...]],
    expected: tuple[object, ...],
    as_of: datetime,
) -> _EvidenceT | None:
    if not rows:
        return None
    restored = tuple(restore(row) for row in rows)
    matches = tuple(item for item in restored if identity(item) == expected)
    if len(rows) != 1 or len(matches) != 1:
        raise EvidenceRepositoryCorruption("evidence identity is aliased or substituted")
    row = rows[0]
    recorded_at = getattr(row, "recorded_at", None)
    if not isinstance(recorded_at, datetime):
        raise EvidenceRepositoryCorruption("evidence row has no valid recorded_at")
    return matches[0] if recorded_at <= as_of else None


def _match(
    rows: tuple[_ModelT, ...],
    restore: Callable[[_ModelT], _EvidenceT],
    expected: _EvidenceT,
) -> _EvidenceT:
    if len(rows) != 1:
        raise EvidenceRepositoryConflict("evidence identity has multiple collision candidates")
    restored = restore(rows[0])
    if restored != expected:
        raise EvidenceRepositoryConflict("evidence identity forks to different content")
    return restored


def _restore_operator(model: EvidenceOperatorSpecModel) -> EvidenceOperatorSpec:
    try:
        value = decode_evidence_operator_spec(model.canonical_payload)
    except EvidenceCodecError as error:
        raise EvidenceRepositoryCorruption("operator payload cannot be restored") from error
    _verify_headers(model, _operator_values(value, model.recorded_at))
    return value


def _restore_track(model: EvidenceTrackRecordModel) -> TrackRecordSnapshot:
    try:
        value = decode_track_record_snapshot(model.canonical_payload)
    except EvidenceCodecError as error:
        raise EvidenceRepositoryCorruption("Track Record payload cannot be restored") from error
    _verify_headers(model, _track_values(value, model.recorded_at))
    return value


def _restore_envelope(model: EvidenceEnvelopeModel) -> EvidenceEnvelope:
    try:
        value = decode_evidence_envelope(model.canonical_payload)
    except EvidenceCodecError as error:
        raise EvidenceRepositoryCorruption("Envelope payload cannot be restored") from error
    _verify_headers(model, _envelope_values(value, model.recorded_at))
    return value


def _verify_headers(model: object, expected: dict[str, object]) -> None:
    if any(getattr(model, key) != value for key, value in expected.items()):
        raise EvidenceRepositoryCorruption("evidence headers differ from canonical payload")


def _operator_values(spec: EvidenceOperatorSpec, recorded_at: datetime) -> dict[str, object]:
    _record_clock(spec.activated_at, recorded_at, spec.valid_until)
    values: dict[str, object] = {
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
        "research_family": spec.research_family,
        "output_artifact_type": spec.output_artifact_type,
        "claim_kind": spec.claim_kind.value,
        "method_kind": spec.method_kind.value,
        "activated_at": spec.activated_at,
        "valid_until": spec.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_evidence_operator_spec(spec),
        "content_hash": spec.content_hash,
    }
    values["ledger_header_hash"] = _header_hash("operator-spec.v1", values)
    return values


def _track_values(snapshot: TrackRecordSnapshot, recorded_at: datetime) -> dict[str, object]:
    _record_clock(snapshot.evaluated_at, recorded_at, snapshot.valid_until)
    artifact = snapshot.artifact
    values: dict[str, object] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "artifact_owner": artifact.owner,
        "artifact_type": artifact.artifact_type,
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "artifact_hash": artifact.content_hash,
        "target": snapshot.target,
        "horizon": snapshot.horizon,
        "sample_policy_id": snapshot.sample_policy_id,
        "sample_policy_version": snapshot.sample_policy_version,
        "evaluated_at": snapshot.evaluated_at,
        "valid_until": snapshot.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_track_record_snapshot(snapshot),
        "content_hash": snapshot.content_hash,
    }
    values["ledger_header_hash"] = _header_hash("track-record.v1", values)
    return values


def _envelope_values(envelope: EvidenceEnvelope, recorded_at: datetime) -> dict[str, object]:
    _record_clock(envelope.evaluated_at, recorded_at, envelope.valid_until)
    output = envelope.output_artifact
    operator = envelope.operator_spec_ref
    values: dict[str, object] = {
        "output_owner": output.owner,
        "output_artifact_type": output.artifact_type,
        "output_artifact_id": output.artifact_id,
        "output_artifact_version": output.artifact_version,
        "output_artifact_hash": output.content_hash,
        "operator_spec_id": operator.artifact_id,
        "operator_spec_version": operator.artifact_version,
        "operator_spec_hash": operator.content_hash,
        "claim_kind": envelope.claim_kind.value,
        "method_kind": envelope.method_kind.value,
        "research_family": envelope.research_family,
        "governance_state": envelope.governance_state.value,
        "permission": envelope.permission.value,
        "evaluated_at": envelope.evaluated_at,
        "valid_until": envelope.valid_until,
        "recorded_at": recorded_at,
        "canonical_payload": encode_evidence_envelope(envelope),
        "content_hash": envelope.content_hash,
        "must_not_use_for_decision": envelope.must_not_use_for_decision,
        "must_not_execute": envelope.must_not_execute,
    }
    values["ledger_header_hash"] = _header_hash("envelope.v1", values)
    return values


def _header_hash(schema: str, values: dict[str, object]) -> str:
    payload = {
        "schema": f"research-evidence-{schema}",
        "values": {
            key: _json_value(value)
            for key, value in values.items()
            if key not in {"canonical_payload", "ledger_header_hash"}
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if type(value) is datetime:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def _record_clock(observed_at: datetime, recorded_at: datetime, valid_until: datetime) -> None:
    for value in (observed_at, recorded_at, valid_until):
        _aware(value)
    if not observed_at <= recorded_at < valid_until:
        raise EvidenceRepositoryConflict("evidence ledger clock is invalid")


def _query(identity: str, version: str, digest: str, as_of: datetime) -> None:
    _token(identity)
    _token(version)
    _hash(digest)
    _aware(as_of)


def _token(value: object) -> None:
    if type(value) is not str or not value.strip() or any(item.isspace() for item in value):
        raise ValueError("evidence identity must be a non-blank token")


def _hash(value: object) -> None:
    _token(value)
    digest = cast(str, value)
    if len(digest) != 64 or any(item not in "0123456789abcdef" for item in digest):
        raise ValueError("evidence hash must be a lowercase SHA-256 digest")


def _aware(value: object) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamp must be timezone-aware")


__all__ = [
    "DjangoEvidenceRepository",
    "DjangoEvidenceRepositoryClock",
    "EvidenceRepositoryClock",
    "EvidenceRepositoryConflict",
    "EvidenceRepositoryCorruption",
    "EvidenceRepositoryUnavailable",
]
