"""Closed-world Django repository for actor-authority source v3 ledgers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    root_claim_hash_for_actor_authority_source_v3,
    validate_account_owner_assignment_actor_authority_source_v3_successor,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_codec import (
    AccountOwnerAssignmentActorAuthoritySourceV3CodecError,
    decode_account_owner_assignment_actor_authority_source_v3,
    encode_account_owner_assignment_actor_authority_source_v3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    _activate_account_owner_assignment_actor_authority_source_v3_uow,
    _claim_account_owner_assignment_actor_authority_source_v3_insert,
)


class AccountOwnerAssignmentActorAuthoritySourceV3Clock(Protocol):
    """Provide the repository decision clock."""

    def now(self) -> datetime: ...


class DjangoAccountOwnerAssignmentActorAuthoritySourceV3Clock:
    """Use Django's timezone-aware clock."""

    def now(self) -> datetime:
        """Return the current aware time."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    anchors: tuple[AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel, ...]
    records: tuple[
        tuple[
            AccountOwnerAssignmentActorAuthoritySourceV3Model,
            PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
        ],
        ...,
    ]


_ValueT = TypeVar("_ValueT")


class DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository:
    """Persist and replay one append-only, single-root authority chain per source."""

    def __init__(
        self,
        *,
        clock: AccountOwnerAssignmentActorAuthoritySourceV3Clock | None = None,
        using: str = "default",
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._clock = clock or DjangoAccountOwnerAssignmentActorAuthoritySourceV3Clock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open the only write-capable repository unit of work."""

        if self._uow is not None:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "nested actor-authority source v3 UOW"
            )
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_owner_assignment_actor_authority_source_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the checked repository clock."""

        value = self._clock.now()
        if not _is_aware(value):
            raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                "repository clock is naive"
            )
        return value

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Return the immutable first winner for an exact source identity."""

        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if (record.source.source_id, record.source.source_version)
            == (source_id, source_version)
            and record.source.recorded_at <= as_of
        )
        return _single(matches, "actor-authority source identity")

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Return the final logical head knowable at the cutoff, including terminal heads."""

        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if record.source.source_id == source_id and record.source.recorded_at <= as_of
        )
        if not matches:
            return None
        return max(matches, key=lambda item: item.source.recorded_at)

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Return one exact permanent version after its recorded-at cutoff."""

        self._cutoff(as_of)
        anchors = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if (record.source.source_id, record.source.source_version)
            == (source_id, source_version)
            or record.source.content_hash == expected_content_hash
        )
        matches = tuple(
            record
            for record in anchors
            if (
                record.source.source_id,
                record.source.source_version,
                record.source.content_hash,
            )
            == (source_id, source_version, expected_content_hash)
            and record.source.recorded_at <= as_of
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                "actor-authority exact anchors disagree"
            )
        return matches[0] if matches else None

    def append(
        self,
        record: PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
        """Append atomically so a caller-caught failure cannot commit an orphan anchor."""

        with transaction.atomic(using=self._using):
            return self._append_in_savepoint(
                record,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )

    def _append_in_savepoint(
        self,
        record: PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
        """Append a root or exact successor under its candidate-independent anchor lock."""

        checked = _record(record)
        token = self._require_uow()
        source = checked.source
        if recorded_at != source.recorded_at:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "actor-authority persisted_at differs"
            )
        root_claim_hash = root_claim_hash_for_actor_authority_source_v3(
            source_id=source.source_id,
            principal_id=source.principal_id,
            user_id=source.user_id,
            authentication_context_identity_hash=source.authentication_context_identity_hash,
            actor_id=source.actor_id,
        )
        anchor = self._lock_anchor(
            source_id=source.source_id,
            root_claim_hash=root_claim_hash,
            created_at=recorded_at,
            token=token,
        )
        world = self._closed_world(lock=True, permitted_empty_anchor=anchor.pk)
        collisions = tuple(
            existing
            for _, existing in world.records
            if (
                existing.source.source_id,
                existing.source.source_version,
            )
            == (source.source_id, source.source_version)
            or existing.source.identity_hash == source.identity_hash
            or existing.source.record_seal == source.record_seal
            or existing.source.content_hash == source.content_hash
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return collisions[0]
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "actor-authority first winner differs"
            )
        chain = tuple(
            (row, existing)
            for row, existing in world.records
            if existing.source.source_id == source.source_id
        )
        previous_row: AccountOwnerAssignmentActorAuthoritySourceV3Model | None = None
        previous: PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None = None
        if chain:
            previous_row, previous = max(chain, key=lambda item: item[1].source.recorded_at)
        actual_predecessor_hash = previous.source.content_hash if previous is not None else None
        if expected_predecessor_hash != actual_predecessor_hash:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "actor-authority predecessor CAS differs"
            )
        try:
            if previous is None:
                if source.root_claim_hash != root_claim_hash or source.supersedes_content_hash:
                    raise ValueError("actor-authority root differs from its root lock")
            else:
                validate_account_owner_assignment_actor_authority_source_v3_successor(
                    previous.source, source
                )
            values = _values(
                checked,
                root_lock_pk=_pk(anchor),
                predecessor_pk=_optional_pk(previous_row),
            )
            with transaction.atomic(using=self._using):
                self._insert(AccountOwnerAssignmentActorAuthoritySourceV3Model, values, token)
        except IntegrityError as error:
            exact = tuple(
                existing
                for _, existing in self._closed_world(lock=True).records
                if existing == checked
            )
            if len(exact) == 1:
                return exact[0]
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "concurrent actor-authority winner differs"
            ) from error
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "invalid actor-authority chain append"
            ) from error
        restored = self.get_exact_by_hash(
            source_id=source.source_id,
            source_version=source.source_version,
            expected_content_hash=source.content_hash,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                "actor-authority restore mismatch"
            )
        return restored

    def _lock_anchor(
        self,
        *,
        source_id: str,
        root_claim_hash: str,
        created_at: datetime,
        token: object,
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel:
        query = AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel._base_manager.using(
            self._using
        )
        anchor = query.filter(source_id=source_id).first()
        if anchor is None:
            values: dict[str, object] = {
                "source_id": source_id,
                "root_claim_hash": root_claim_hash,
                "created_at": created_at,
            }
            try:
                with transaction.atomic(using=self._using):
                    self._insert(
                        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
                        values,
                        token,
                    )
            except IntegrityError:
                pass
        anchor = query.select_for_update().filter(source_id=source_id).first()
        if anchor is None:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "actor-authority root lock unavailable"
            )
        if anchor.root_claim_hash != root_claim_hash:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "actor-authority root lock claim differs"
            )
        return anchor

    def _closed_world(self, *, lock: bool, permitted_empty_anchor: int | None = None) -> _World:
        anchor_query = (
            AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel._base_manager.using(
                self._using
            ).all()
        )
        record_query = (
            AccountOwnerAssignmentActorAuthoritySourceV3Model._base_manager.using(self._using)
            .select_related("root_lock", "predecessor")
            .all()
        )
        if lock:
            anchor_query = anchor_query.select_for_update()
            record_query = record_query.select_for_update()
        anchors = tuple(anchor_query.order_by("pk"))
        by_anchor = {_pk(anchor): anchor for anchor in anchors}
        records: list[
            tuple[
                AccountOwnerAssignmentActorAuthoritySourceV3Model,
                PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
            ]
        ] = []
        for row in record_query.order_by("pk"):
            anchor = by_anchor.get(row.root_lock_id)
            if anchor is None:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "actor-authority ledger has no root lock"
                )
            restored = _restore(row)
            if restored.source.source_id != anchor.source_id:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "actor-authority root lock source differs"
                )
            records.append((row, restored))
        self._validate_graph(anchors, tuple(records), permitted_empty_anchor)
        return _World(anchors, tuple(records))

    def _validate_graph(
        self,
        anchors: tuple[AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel, ...],
        records: tuple[
            tuple[
                AccountOwnerAssignmentActorAuthoritySourceV3Model,
                PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
            ],
            ...,
        ],
        permitted_empty_anchor: int | None,
    ) -> None:
        for anchor in anchors:
            chain = tuple(item for item in records if item[0].root_lock_id == _pk(anchor))
            if not chain:
                if permitted_empty_anchor != _pk(anchor):
                    raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                        "orphan actor-authority root lock"
                    )
                continue
            roots = tuple(item for item in chain if item[0].predecessor_id is None)
            if len(roots) != 1:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "actor-authority chain must have one root"
                )
            root_row, root = roots[0]
            if (
                root.source.root_claim_hash != anchor.root_claim_hash
                or anchor.created_at != root.source.recorded_at
            ):
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "actor-authority chain root-lock binding differs"
                )
            by_predecessor: dict[
                int,
                list[
                    tuple[
                        AccountOwnerAssignmentActorAuthoritySourceV3Model,
                        PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
                    ]
                ],
            ] = {}
            for item in chain:
                predecessor_id = item[0].predecessor_id
                if predecessor_id is not None:
                    by_predecessor.setdefault(predecessor_id, []).append(item)
            visited = {_pk(root_row)}
            current_row, current = root_row, root
            while successors := by_predecessor.get(_pk(current_row), []):
                if len(successors) != 1:
                    raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                        "actor-authority chain forks"
                    )
                next_row, successor = successors[0]
                if _pk(next_row) in visited:
                    raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                        "actor-authority chain cycles"
                    )
                try:
                    validate_account_owner_assignment_actor_authority_source_v3_successor(
                        current.source, successor.source
                    )
                except (TypeError, ValueError) as error:
                    raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                        "actor-authority successor is invalid"
                    ) from error
                visited.add(_pk(next_row))
                current_row, current = next_row, successor
            if len(visited) != len(chain):
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "actor-authority chain has an orphan or cycle"
                )

    def _insert(
        self,
        model_type: (
            type[AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel]
            | type[AccountOwnerAssignmentActorAuthoritySourceV3Model]
        ),
        values: dict[str, object],
        token: object,
    ) -> None:
        with _claim_account_owner_assignment_actor_authority_source_v3_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "append requires private UOW"
            )
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        if not _is_aware(as_of):
            raise AccountOwnerAssignmentActorAuthoritySourceV3Unavailable(
                "as_of must be timezone-aware"
            )
        if as_of > self.now():
            raise AccountOwnerAssignmentActorAuthoritySourceV3Unavailable(
                "future as_of is forbidden"
            )


def _values(
    record: PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
    *,
    root_lock_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    source, recorder = record.source, record.recorded_by
    payload = encode_account_owner_assignment_actor_authority_source_v3(source)
    values: dict[str, object] = {
        name: getattr(source, name) for name in payload if name not in _DATETIME_FIELDS
    }
    for name in _DATETIME_FIELDS:
        values[name] = getattr(source, name)
    values.update(
        {
            "root_lock_id": root_lock_pk,
            "predecessor_id": predecessor_pk,
            "recorded_by_service_id": recorder.service_id,
            "recorded_by_role": recorder.role,
            "recorded_by_kind": recorder.kind,
            "recorded_by_is_automated": recorder.is_automated,
            "canonical_payload": payload,
            "persisted_at": source.recorded_at,
        }
    )
    recorder_payload = {
        "is_automated": recorder.is_automated,
        "kind": recorder.kind,
        "role": recorder.role,
        "service_id": recorder.service_id,
    }
    values["recorder_binding_seal"] = _hash(
        {"content_hash": source.content_hash, "recorder": recorder_payload}
    )
    values["ledger_seal"] = _hash(
        {
            "content_hash": source.content_hash,
            "predecessor_pk": predecessor_pk,
            "recorder_binding_seal": values["recorder_binding_seal"],
            "record_seal": source.record_seal,
            "root_lock_pk": root_lock_pk,
            "persisted_at": _time(source.recorded_at),
        }
    )
    return values


def _restore(
    row: AccountOwnerAssignmentActorAuthoritySourceV3Model,
) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
    try:
        source = decode_account_owner_assignment_actor_authority_source_v3(row.canonical_payload)
        recorder = AccountOwnerAssignmentActorAuthoritySourceV3Recorder(
            service_id=row.recorded_by_service_id,
            role=row.recorded_by_role,
            kind=row.recorded_by_kind,
            is_automated=row.recorded_by_is_automated,
        )
        record = PersistedAccountOwnerAssignmentActorAuthoritySourceV3(
            source=source, recorded_by=recorder
        )
        expected = _values(
            record,
            root_lock_pk=row.root_lock_id,
            predecessor_pk=row.predecessor_id,
        )
    except (AccountOwnerAssignmentActorAuthoritySourceV3CodecError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "actor-authority ledger payload is corrupt"
        ) from error
    for name, value in expected.items():
        if getattr(row, name) != value:
            raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                f"actor-authority ledger seal mismatch: {name}"
            )
    return record


def _record(value: object) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
    if type(value) is not PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "actor-authority record type substitution"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "actor-authority record is corrupt"
        ) from error
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _single(values: tuple[_ValueT, ...], label: str) -> _ValueT | None:
    if len(values) > 1:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _pk(
    value: (
        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel
        | AccountOwnerAssignmentActorAuthoritySourceV3Model
    ),
) -> int:
    if value.pk is None:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "actor-authority row has no database identity"
        )
    return int(value.pk)


def _optional_pk(value: AccountOwnerAssignmentActorAuthoritySourceV3Model | None) -> int | None:
    return None if value is None else _pk(value)


def _is_aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


_DATETIME_FIELDS = frozenset(
    {
        "principal_authenticated_at",
        "principal_valid_until",
        "source_recorded_at",
        "source_valid_until",
        "issued_at",
        "recorded_at",
        "ttl_valid_until",
        "valid_until",
    }
)


__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3Clock",
    "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Clock",
    "DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository",
]
