"""Strict Django persistence for the dormant Evidence scope-source v1 ledger.

The public repository is read-only.  Its selectors restore the complete table
before applying an identity or PIT predicate, so a malformed or disconnected
row cannot be hidden by a narrow query.  The private store is the only object
that owns an Evidence insert token; callers receive it only from the explicit
test/composition builder and must enter its repository-owned transaction before
appending a root or a compare-and-swap successor.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Unavailable,
)
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    validate_evidence_scope_source_v1_successor,
)
from apps.research.infrastructure.evidence_models import (
    _ACTIVE_EVIDENCE_UOW,
    EvidenceScopeSourceV1Model,
    _activate_evidence_uow,
    _claim_evidence_insert,
)
from apps.research.infrastructure.evidence_scope_source_v1_codec import (
    EvidenceScopeSourceV1CodecError,
    decode_evidence_scope_source_v1,
    encode_evidence_scope_source_v1,
)


class EvidenceScopeSourceV1Conflict(RuntimeError):
    """An append races or forks an existing immutable scope-source winner."""


class EvidenceScopeSourceV1Clock(Protocol):
    """Authoritative clock used to reject future PIT cutoffs."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoEvidenceScopeSourceV1Clock:
    """Django timezone-backed source repository clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return timezone.now()


class DjangoEvidenceScopeSourceV1Repository:
    """Public full-world exact/PIT reader with no append capability."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceScopeSourceV1Clock | None = None,
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("Evidence scope-source database alias is invalid")
        self._using = using
        self._clock = clock or DjangoEvidenceScopeSourceV1Clock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity used by this read port."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Restore one exact source from the complete ledger at a PIT cutoff."""

        _require_selector(source_id, source_version, expected_content_hash, as_of)
        self._require_pit_cutoff(as_of)
        records = self._restore_full_world()
        matches = tuple(
            record
            for record in records
            if record.source_id == source_id
            and record.source_version == source_version
            and record.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise EvidenceScopeSourceV1Corruption(
                "scope-source exact identity has multiple matches"
            )
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Return one immutable first winner by identity at a historical PIT."""

        _require_token(source_id, "source_id")
        _require_token(source_version, "source_version")
        _require_aware(as_of, "as_of")
        self._require_pit_cutoff(as_of)
        records = self._restore_full_world()
        matches = tuple(
            record
            for record in records
            if record.source_id == source_id and record.source_version == source_version
        )
        if len(matches) > 1:
            raise EvidenceScopeSourceV1Corruption(
                "scope-source winner identity has multiple matches"
            )
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def get_current_head(
        self,
        *,
        source_id: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Return the final chain head knowable at ``as_of`` without fallback."""

        _require_token(source_id, "source_id")
        _require_aware(as_of, "as_of")
        self._require_pit_cutoff(as_of)
        records = tuple(
            record for record in self._restore_full_world() if record.source_id == source_id
        )
        known = tuple(record for record in records if record.recorded_at <= as_of)
        if not known:
            return None
        known_hashes = {record.content_hash for record in known}
        heads = tuple(
            record
            for record in known
            if not any(
                child.supersedes_content_hash == record.content_hash
                for child in known
                if child.content_hash != record.content_hash
            )
        )
        if len(heads) != 1 or heads[0].content_hash not in known_hashes:
            raise EvidenceScopeSourceV1Corruption(
                "scope-source PIT chain has no unique logical head"
            )
        return heads[0]

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        now = self._server_now()
        if as_of > now:
            raise EvidenceScopeSourceV1Unavailable(
                "future Evidence scope-source as_of is not permitted"
            )

    def _server_now(self) -> datetime:
        """Return the validated repository clock or fail closed."""

        try:
            now = self._clock.now()
            _require_aware(now, "server clock")
        except (TypeError, ValueError) as error:
            raise EvidenceScopeSourceV1Unavailable(
                "Evidence scope-source server clock is unavailable"
            ) from error
        except Exception as error:
            raise EvidenceScopeSourceV1Unavailable(
                "Evidence scope-source server clock is unavailable"
            ) from error
        return now

    def _restore_full_world(self) -> tuple[EvidenceScopeSourceV1, ...]:
        """Restore and validate every row before any caller selector runs."""

        rows = tuple(EvidenceScopeSourceV1Model._default_manager.using(self._using).order_by("pk"))
        if not rows:
            return ()
        records = tuple(_restore_row(row) for row in rows)
        by_source: dict[str, list[tuple[EvidenceScopeSourceV1, EvidenceScopeSourceV1Model]]] = {}
        for record, row in zip(records, rows, strict=True):
            by_source.setdefault(record.source_id, []).append((record, row))
        for source_rows in by_source.values():
            _validate_chain(tuple(source_rows))
        return records


class _DjangoEvidenceScopeSourceV1Store(DjangoEvidenceScopeSourceV1Repository):
    """Private append capability layered over the public full-world reader."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        token: object,
        using: str,
        clock: EvidenceScopeSourceV1Clock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = token

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one repository-owned transaction and private insert UOW."""

        with transaction.atomic(using=self._using), _activate_evidence_uow(self._token):
            yield

    def append(
        self,
        source: EvidenceScopeSourceV1,
        *,
        predecessor: EvidenceScopeSourceV1 | None = None,
    ) -> EvidenceScopeSourceV1:
        """Append one exact root/successor or replay its immutable winner."""

        if _ACTIVE_EVIDENCE_UOW.get() is not self._token:
            raise EvidenceScopeSourceV1Conflict(
                "scope-source append requires its private atomic unit"
            )
        exact = _canonical_source(source)
        self._validate_recorded_at(exact.recorded_at)
        if predecessor is not None:
            previous = _canonical_source(predecessor)
            validate_evidence_scope_source_v1_successor(previous, exact)
        else:
            previous = None
            if exact.supersedes_content_hash is not None:
                raise EvidenceScopeSourceV1Conflict(
                    "scope-source successor requires an exact predecessor"
                )

        # Restore the complete pre-append world so existing corruption cannot be
        # hidden by an idempotency lookup or an apparently unrelated append.
        records = self._restore_full_world()
        rows = tuple(EvidenceScopeSourceV1Model._default_manager.using(self._using).order_by("pk"))
        if len(records) != len(rows):
            raise EvidenceScopeSourceV1Corruption("scope-source ledger restore is unstable")
        by_hash = {
            record.content_hash: (record, row) for record, row in zip(records, rows, strict=True)
        }

        if previous is None:
            existing = tuple(
                (record, row)
                for record, row in zip(records, rows, strict=True)
                if record.source_id == exact.source_id
                and (
                    record.source_version == exact.source_version
                    or record.content_hash == exact.content_hash
                    or record.root_claim_hash == exact.root_claim_hash
                )
            )
            if existing:
                return _replay_or_conflict(existing, exact, predecessor_id=None)
        else:
            persisted_previous = by_hash.get(previous.content_hash)
            if persisted_previous is None:
                raise EvidenceScopeSourceV1Conflict(
                    "scope-source successor predecessor is not persisted"
                )
            if persisted_previous[0] != previous:
                raise EvidenceScopeSourceV1Conflict(
                    "scope-source successor predecessor content fork"
                )
            existing = tuple(
                (record, row)
                for record, row in zip(records, rows, strict=True)
                if record.source_id == exact.source_id
                and (
                    record.source_version == exact.source_version
                    or record.content_hash == exact.content_hash
                    or record.supersedes_content_hash == exact.supersedes_content_hash
                )
            )
            if existing:
                return _replay_or_conflict(
                    existing,
                    exact,
                    predecessor_id=persisted_previous[1].pk,
                )

        if previous is None and any(record.source_id == exact.source_id for record in records):
            raise EvidenceScopeSourceV1Conflict(
                "scope-source root cannot be appended after an existing chain"
            )

        predecessor_id = None if previous is None else by_hash[previous.content_hash][1].pk
        values = _source_values(exact, predecessor_id=predecessor_id)
        model = EvidenceScopeSourceV1Model(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_evidence_insert(
                    token=self._token,
                    model_type=EvidenceScopeSourceV1Model,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError, ValueError) as error:
            # Unique constraints are the database CAS.  Re-read the complete
            # world and return only a byte-for-byte canonical winner.
            records_after = self._restore_full_world()
            rows_after = tuple(
                EvidenceScopeSourceV1Model._default_manager.using(self._using).order_by("pk")
            )
            candidates = tuple(
                (record, row)
                for record, row in zip(records_after, rows_after, strict=True)
                if record.source_id == exact.source_id
                and (
                    record.source_version == exact.source_version
                    or record.content_hash == exact.content_hash
                    or record.supersedes_content_hash == exact.supersedes_content_hash
                )
            )
            if candidates:
                return _replay_or_conflict(candidates, exact, predecessor_id=predecessor_id)
            raise EvidenceScopeSourceV1Conflict(
                "scope-source append conflicted without an exact winner"
            ) from error
        return exact

    def _validate_recorded_at(self, recorded_at: datetime) -> None:
        """Reject a caller-supplied ledger timestamp beyond the server clock."""

        _require_aware(recorded_at, "recorded_at")
        if recorded_at > self._server_now():
            raise EvidenceScopeSourceV1Conflict("scope-source recorded_at cannot be in the future")

    def append_root(self, source: EvidenceScopeSourceV1) -> EvidenceScopeSourceV1:
        """Append one candidate-independent root source."""

        return self.append(source)

    def append_successor(
        self,
        predecessor: EvidenceScopeSourceV1,
        successor: EvidenceScopeSourceV1,
    ) -> EvidenceScopeSourceV1:
        """Append one compare-and-swap successor bound to ``predecessor``."""

        return self.append(successor, predecessor=predecessor)


def _build_evidence_scope_source_v1_store(
    *,
    using: str = "default",
    clock: EvidenceScopeSourceV1Clock | None = None,
) -> _DjangoEvidenceScopeSourceV1Store:
    """Build the private store without exporting its unforgeable token."""

    return _DjangoEvidenceScopeSourceV1Store(token=object(), using=using, clock=clock)


def _canonical_source(source: EvidenceScopeSourceV1) -> EvidenceScopeSourceV1:
    if type(source) is not EvidenceScopeSourceV1:
        raise TypeError("scope source must be the exact Domain type")
    try:
        return decode_evidence_scope_source_v1(encode_evidence_scope_source_v1(source))
    except EvidenceScopeSourceV1CodecError as error:
        raise EvidenceScopeSourceV1Corruption("scope source cannot be canonicalized") from error


def _restore_row(model: Model) -> EvidenceScopeSourceV1:
    if type(model) is not EvidenceScopeSourceV1Model:
        raise EvidenceScopeSourceV1Corruption("scope-source row type is substituted")
    try:
        source = decode_evidence_scope_source_v1(model.canonical_payload)
    except EvidenceScopeSourceV1CodecError as error:
        raise EvidenceScopeSourceV1Corruption("scope-source payload cannot be restored") from error
    expected = _source_values(source, predecessor_id=model.predecessor_id)
    if any(getattr(model, key) != value for key, value in expected.items()):
        raise EvidenceScopeSourceV1Corruption("scope-source headers differ from canonical payload")
    return source


def _source_values(
    source: EvidenceScopeSourceV1,
    *,
    predecessor_id: int | None,
) -> dict[str, object]:
    artifact = source.artifact
    return {
        "source_id": source.source_id,
        "source_version": source.source_version,
        "owner_id": source.owner_id,
        "tenant_id": source.tenant_id,
        "account_id": source.account_id,
        "actor_id": source.actor_id,
        "artifact_owner": artifact.owner,
        "artifact_type": artifact.artifact_type,
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "artifact_content_hash": artifact.content_hash,
        "status": source.status,
        "recorded_at": source.recorded_at,
        "valid_until": source.valid_until,
        "root_claim_hash": source.root_claim_hash,
        "supersedes_content_hash": source.supersedes_content_hash,
        "predecessor_id": predecessor_id,
        "identity_hash": source.identity_hash,
        "content_hash": source.content_hash,
        "source_owner": source.owner,
        "source_artifact_type": source.artifact_type,
        "source_schema": source.schema,
        "permission": source.permission,
        "must_not_execute": source.must_not_execute,
        "execution_allowed": source.execution_allowed,
        "canonical_payload": encode_evidence_scope_source_v1(source),
        "persisted_at": source.recorded_at,
    }


def _validate_chain(
    rows: tuple[tuple[EvidenceScopeSourceV1, EvidenceScopeSourceV1Model], ...],
) -> None:
    by_hash: dict[str, tuple[EvidenceScopeSourceV1, EvidenceScopeSourceV1Model]] = {}
    by_identity: set[tuple[str, str]] = set()
    for source, row in rows:
        if source.source_id != row.source_id:
            raise EvidenceScopeSourceV1Corruption("scope-source row source identity is substituted")
        if (
            source.content_hash in by_hash
            or (source.source_id, source.source_version) in by_identity
        ):
            raise EvidenceScopeSourceV1Corruption("scope-source ledger identity is duplicated")
        by_hash[source.content_hash] = (source, row)
        by_identity.add((source.source_id, source.source_version))

    roots = tuple(item for item in rows if item[0].root_claim_hash is not None)
    if len(roots) != 1:
        raise EvidenceScopeSourceV1Corruption("scope-source chain must have exactly one root")
    root = roots[0]
    if root[1].predecessor_id is not None:
        raise EvidenceScopeSourceV1Corruption("scope-source root has a predecessor")
    children: dict[str, tuple[EvidenceScopeSourceV1, EvidenceScopeSourceV1Model]] = {}
    for source, row in rows:
        predecessor_hash = source.supersedes_content_hash
        if predecessor_hash is None:
            if row.predecessor_id is not None:
                raise EvidenceScopeSourceV1Corruption("scope-source root FK is non-null")
            continue
        predecessor = by_hash.get(predecessor_hash)
        if predecessor is None:
            raise EvidenceScopeSourceV1Corruption("scope-source chain has an orphan successor")
        if row.predecessor_id != predecessor[1].pk:
            raise EvidenceScopeSourceV1Corruption("scope-source predecessor FK is substituted")
        if predecessor_hash in children:
            raise EvidenceScopeSourceV1Corruption("scope-source chain contains a fork")
        try:
            validate_evidence_scope_source_v1_successor(predecessor[0], source)
        except (TypeError, ValueError) as error:
            raise EvidenceScopeSourceV1Corruption(
                "scope-source successor does not bind its predecessor"
            ) from error
        children[predecessor_hash] = (source, row)

    visited = {root[0].content_hash}
    current_hash = root[0].content_hash
    while current_hash in children:
        current_hash = children[current_hash][0].content_hash
        if current_hash in visited:
            raise EvidenceScopeSourceV1Corruption("scope-source chain contains a cycle")
        visited.add(current_hash)
    if len(visited) != len(rows):
        raise EvidenceScopeSourceV1Corruption("scope-source chain is disconnected")


def _replay_or_conflict(
    candidates: tuple[tuple[EvidenceScopeSourceV1, EvidenceScopeSourceV1Model], ...],
    expected: EvidenceScopeSourceV1,
    *,
    predecessor_id: int | None,
) -> EvidenceScopeSourceV1:
    if len(candidates) != 1:
        raise EvidenceScopeSourceV1Conflict(
            "scope-source identity has multiple collision candidates"
        )
    actual, row = candidates[0]
    if actual != expected or row.predecessor_id != predecessor_id:
        raise EvidenceScopeSourceV1Conflict("scope-source identity forks to different content")
    return actual


def _require_selector(
    source_id: str,
    source_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> None:
    _require_token(source_id, "source_id")
    _require_token(source_version, "source_version")
    _require_digest(expected_content_hash, "expected_content_hash")
    _require_aware(as_of, "as_of")


def _require_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded canonical token")


def _require_digest(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "DjangoEvidenceScopeSourceV1Clock",
    "DjangoEvidenceScopeSourceV1Repository",
    "EvidenceScopeSourceV1Clock",
    "EvidenceScopeSourceV1Conflict",
]
