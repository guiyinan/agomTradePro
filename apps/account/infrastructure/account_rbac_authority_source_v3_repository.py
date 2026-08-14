"""Closed-world Django repository for Account RBAC authority source v3."""

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

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    root_claim_hash_for_account_rbac_authority_source_v3,
    validate_account_rbac_authority_source_v3_successor,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    _activate_account_actor_authority_raw_source_v3_uow,
    _claim_account_actor_authority_raw_source_v3_insert,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_codec import (
    AccountRbacAuthoritySourceV3CodecError,
    decode_account_rbac_authority_source_v3,
    encode_account_rbac_authority_source_v3,
)


class AccountRbacAuthoritySourceV3Clock(Protocol):
    """Provide the repository decision clock."""

    def now(self) -> datetime:
        """Return an aware server time."""

        ...


class DjangoAccountRbacAuthoritySourceV3Clock:
    """Use Django's timezone-aware clock."""

    def now(self) -> datetime:
        """Return the current aware server time."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    anchors: tuple[AccountRbacAuthoritySourceV3AnchorModel, ...]
    records: tuple[
        tuple[AccountRbacAuthoritySourceV3Model, PersistedAccountRbacAuthoritySourceV3], ...
    ]


_ValueT = TypeVar("_ValueT")


class DjangoAccountRbacAuthoritySourceV3Repository:
    """Persist and restore every RBAC chain before serving any selector."""

    def __init__(
        self, *, clock: AccountRbacAuthoritySourceV3Clock | None = None, using: str = "default"
    ) -> None:
        """Bind one exact database alias and authoritative server clock."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._clock = clock or DjangoAccountRbacAuthoritySourceV3Clock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open the private non-nestable write unit of work on the configured alias."""

        if self._uow is not None:
            raise AccountActorAuthorityRawSourceV3Conflict("nested RBAC authority UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_actor_authority_raw_source_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the checked repository clock."""

        value = self._clock.now()
        if not _aware(value):
            raise AccountActorAuthorityRawSourceV3Corruption("RBAC repository clock is naive")
        return value

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return the first exact logical winner recorded by the cutoff."""

        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if (record.source.identity.source_id, record.source.identity.source_version)
            == (source_id, source_version)
            and record.source.clock.recorded_at <= as_of
        )
        return _single(matches, "RBAC logical winner")

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return the final knowable head, including expired or revoked terminal heads."""

        self._cutoff(as_of)
        matches = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if record.source.identity.source_id == source_id
            and record.source.clock.recorded_at <= as_of
        )
        return max(matches, key=lambda item: item.source.clock.recorded_at) if matches else None

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        """Return permanent exact history after its recorded-at cutoff."""

        self._cutoff(as_of)
        candidates = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if (
                (record.source.identity.source_id, record.source.identity.source_version)
                == (source_id, source_version)
                or record.source.content_hash == expected_content_hash
            )
        )
        matches = tuple(
            record
            for record in candidates
            if (
                record.source.identity.source_id,
                record.source.identity.source_version,
                record.source.content_hash,
            )
            == (source_id, source_version, expected_content_hash)
            and record.source.clock.recorded_at <= as_of
        )
        if candidates and (len(candidates) != 1 or len(matches) > 1):
            raise AccountActorAuthorityRawSourceV3Corruption("RBAC exact anchors disagree")
        return matches[0] if matches else None

    def append(
        self,
        record: PersistedAccountRbacAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3:
        """Append inside one savepoint so caught failures cannot leave an empty anchor."""

        with transaction.atomic(using=self._using):
            return self._append(
                record,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )

    def _append(
        self,
        record: PersistedAccountRbacAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3:
        checked = _record(record)
        token = self._require_uow()
        source = checked.source
        if not _aware(recorded_at) or recorded_at != source.clock.recorded_at:
            raise AccountActorAuthorityRawSourceV3Conflict("RBAC persisted clock differs")
        root_hash = root_claim_hash_for_account_rbac_authority_source_v3(
            source_id=source.identity.source_id,
            user_id=source.user_id,
            actor_id=source.actor_id,
        )
        anchor = self._lock_anchor(
            source_id=source.identity.source_id,
            root_claim_hash=root_hash,
            created_at=recorded_at,
            token=token,
        )
        world = self._closed_world(lock=True, permitted_empty_anchor=_pk(anchor))
        collisions = tuple(
            existing
            for _, existing in world.records
            if (existing.source.identity.source_id, existing.source.identity.source_version)
            == (source.identity.source_id, source.identity.source_version)
            or existing.source.identity_hash == source.identity_hash
            or existing.source.record_seal == source.record_seal
            or existing.source.content_hash == source.content_hash
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return collisions[0]
            raise AccountActorAuthorityRawSourceV3Conflict("RBAC first winner differs")
        chain = tuple(
            item
            for item in world.records
            if item[1].source.identity.source_id == source.identity.source_id
        )
        previous_row: AccountRbacAuthoritySourceV3Model | None = None
        previous: PersistedAccountRbacAuthoritySourceV3 | None = None
        if chain:
            previous_row, previous = max(chain, key=lambda item: item[1].source.clock.recorded_at)
        actual_hash = previous.source.content_hash if previous is not None else None
        if expected_predecessor_hash != actual_hash:
            raise AccountActorAuthorityRawSourceV3Conflict("RBAC predecessor CAS differs")
        try:
            if previous is None:
                if (
                    source.chain.root_claim_hash != root_hash
                    or source.chain.supersedes_content_hash is not None
                ):
                    raise ValueError("RBAC root differs from its anchor")
            else:
                validate_account_rbac_authority_source_v3_successor(previous.source, source)
            values = _values(
                checked, anchor_pk=_pk(anchor), predecessor_pk=_optional_pk(previous_row)
            )
            with transaction.atomic(using=self._using):
                self._insert(AccountRbacAuthoritySourceV3Model, values, token)
        except IntegrityError as error:
            exact = tuple(
                existing
                for _, existing in self._closed_world(lock=True).records
                if existing == checked
            )
            if len(exact) == 1:
                return exact[0]
            raise AccountActorAuthorityRawSourceV3Conflict(
                "concurrent RBAC winner differs"
            ) from error
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Conflict("invalid RBAC chain append") from error
        restored = self.get_exact_by_hash(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            expected_content_hash=source.content_hash,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountActorAuthorityRawSourceV3Corruption("RBAC append restore mismatch")
        return restored

    def _lock_anchor(
        self,
        *,
        source_id: str,
        root_claim_hash: str,
        created_at: datetime,
        token: object,
    ) -> AccountRbacAuthoritySourceV3AnchorModel:
        query = AccountRbacAuthoritySourceV3AnchorModel._base_manager.using(self._using)
        if query.filter(source_id=source_id).first() is None:
            values = {
                "source_id": source_id,
                "root_claim_hash": root_claim_hash,
                "created_at": created_at,
            }
            try:
                with transaction.atomic(using=self._using):
                    self._insert(AccountRbacAuthoritySourceV3AnchorModel, values, token)
            except IntegrityError:
                pass
        anchor = query.select_for_update().filter(source_id=source_id).first()
        if anchor is None:
            raise AccountActorAuthorityRawSourceV3Conflict("RBAC anchor unavailable")
        if anchor.root_claim_hash != root_claim_hash:
            raise AccountActorAuthorityRawSourceV3Conflict("RBAC anchor claim differs")
        return anchor

    def _closed_world(self, *, lock: bool, permitted_empty_anchor: int | None = None) -> _World:
        anchor_query = AccountRbacAuthoritySourceV3AnchorModel._base_manager.using(
            self._using
        ).all()
        row_query = (
            AccountRbacAuthoritySourceV3Model._base_manager.using(self._using)
            .select_related("anchor", "predecessor")
            .all()
        )
        if lock:
            anchor_query = anchor_query.select_for_update()
            row_query = row_query.select_for_update()
        anchors = tuple(anchor_query.order_by("pk"))
        anchor_by_pk = {_pk(anchor): anchor for anchor in anchors}
        records: list[
            tuple[AccountRbacAuthoritySourceV3Model, PersistedAccountRbacAuthoritySourceV3]
        ] = []
        for row in row_query.order_by("pk"):
            anchor = anchor_by_pk.get(row.anchor_id)
            if anchor is None:
                raise AccountActorAuthorityRawSourceV3Corruption("RBAC row has no anchor")
            record = _restore(row)
            if record.source.identity.source_id != anchor.source_id:
                raise AccountActorAuthorityRawSourceV3Corruption("RBAC anchor source differs")
            records.append((row, record))
        self._validate_graph(anchors, tuple(records), permitted_empty_anchor)
        return _World(anchors, tuple(records))

    def _validate_graph(
        self,
        anchors: tuple[AccountRbacAuthoritySourceV3AnchorModel, ...],
        records: tuple[
            tuple[AccountRbacAuthoritySourceV3Model, PersistedAccountRbacAuthoritySourceV3], ...
        ],
        permitted_empty_anchor: int | None,
    ) -> None:
        for anchor in anchors:
            chain = tuple(item for item in records if item[0].anchor_id == _pk(anchor))
            if not chain:
                if permitted_empty_anchor != _pk(anchor):
                    raise AccountActorAuthorityRawSourceV3Corruption("orphan RBAC anchor")
                continue
            roots = tuple(item for item in chain if item[0].predecessor_id is None)
            if len(roots) != 1:
                raise AccountActorAuthorityRawSourceV3Corruption("RBAC chain must have one root")
            root_row, root = roots[0]
            if (
                root.source.chain.root_claim_hash != anchor.root_claim_hash
                or anchor.created_at != root.source.clock.recorded_at
            ):
                raise AccountActorAuthorityRawSourceV3Corruption("RBAC root binding differs")
            successors: dict[
                int,
                list[
                    tuple[AccountRbacAuthoritySourceV3Model, PersistedAccountRbacAuthoritySourceV3]
                ],
            ] = {}
            for item in chain:
                if item[0].predecessor_id is not None:
                    successors.setdefault(item[0].predecessor_id, []).append(item)
            visited = {_pk(root_row)}
            current_row, current = root_row, root
            while next_items := successors.get(_pk(current_row), []):
                if len(next_items) != 1:
                    raise AccountActorAuthorityRawSourceV3Corruption("RBAC chain forks")
                next_row, successor = next_items[0]
                if _pk(next_row) in visited:
                    raise AccountActorAuthorityRawSourceV3Corruption("RBAC chain cycles")
                try:
                    validate_account_rbac_authority_source_v3_successor(
                        current.source, successor.source
                    )
                except (TypeError, ValueError) as error:
                    raise AccountActorAuthorityRawSourceV3Corruption(
                        "RBAC successor is invalid"
                    ) from error
                visited.add(_pk(next_row))
                current_row, current = next_row, successor
            if len(visited) != len(chain):
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "RBAC chain has an orphan or cycle"
                )

    def _insert(
        self,
        model_type: (
            type[AccountRbacAuthoritySourceV3AnchorModel] | type[AccountRbacAuthoritySourceV3Model]
        ),
        values: dict[str, object],
        token: object,
    ) -> None:
        with _claim_account_actor_authority_raw_source_v3_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise AccountActorAuthorityRawSourceV3Conflict("append requires private RBAC UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        if not _aware(as_of) or as_of > self.now():
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "RBAC as_of must be aware and not future"
            )


def _values(
    record: PersistedAccountRbacAuthoritySourceV3,
    *,
    anchor_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    source, recorder = record.source, record.recorded_by
    payload = encode_account_rbac_authority_source_v3(source)
    values: dict[str, object] = {
        "anchor_id": anchor_pk,
        "predecessor_id": predecessor_pk,
        "owner": source.owner,
        "artifact_type": source.artifact_type,
        "schema": source.schema,
        "permission": source.permission,
        "status": source.status,
        "must_not_execute": source.must_not_execute,
        "execution_allowed": source.execution_allowed,
        "source_id": source.identity.source_id,
        "source_version": source.identity.source_version,
        "observed_at": source.clock.observed_at,
        "recorded_at": source.clock.recorded_at,
        "valid_until": source.clock.valid_until,
        "root_claim_hash": source.chain.root_claim_hash,
        "supersedes_content_hash": source.chain.supersedes_content_hash,
        "identity_hash": source.identity_hash,
        "facts_seal": source.facts_seal,
        "clock_seal": source.clock_seal,
        "chain_seal": source.chain_seal,
        "fixed_authority_seal": source.fixed_authority_seal,
        "record_seal": source.record_seal,
        "content_hash": source.content_hash,
        "user_id": source.user_id,
        "actor_id": source.actor_id,
        "rbac_role": source.rbac_role,
        "authority_state": source.authority_state,
        "rbac_seal": source.rbac_seal,
        "recorded_by_service_id": recorder.service_id,
        "recorded_by_role": recorder.role,
        "recorded_by_kind": recorder.kind,
        "recorded_by_is_automated": recorder.is_automated,
        "canonical_payload": payload,
        "persisted_at": source.clock.recorded_at,
    }
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
            "anchor_pk": anchor_pk,
            "content_hash": source.content_hash,
            "persisted_at": _time(source.clock.recorded_at),
            "predecessor_pk": predecessor_pk,
            "record_seal": source.record_seal,
            "recorder_binding_seal": values["recorder_binding_seal"],
        }
    )
    return values


def _restore(row: AccountRbacAuthoritySourceV3Model) -> PersistedAccountRbacAuthoritySourceV3:
    try:
        source = decode_account_rbac_authority_source_v3(row.canonical_payload)
        record = PersistedAccountRbacAuthoritySourceV3(
            source,
            AccountActorAuthorityRawSourceV3Recorder(
                row.recorded_by_service_id,
                row.recorded_by_role,
                row.recorded_by_kind,
                row.recorded_by_is_automated,
            ),
        )
        expected = _values(record, anchor_pk=row.anchor_id, predecessor_pk=row.predecessor_id)
    except (AccountRbacAuthoritySourceV3CodecError, TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC ledger payload is corrupt"
        ) from error
    for name, expected_value in expected.items():
        if getattr(row, name) != expected_value:
            raise AccountActorAuthorityRawSourceV3Corruption(f"RBAC ledger mismatch: {name}")
    return record


def _record(value: object) -> PersistedAccountRbacAuthoritySourceV3:
    if type(value) is not PersistedAccountRbacAuthoritySourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC record type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC record is corrupt") from error
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
        raise AccountActorAuthorityRawSourceV3Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _pk(value: AccountRbacAuthoritySourceV3AnchorModel | AccountRbacAuthoritySourceV3Model) -> int:
    if value.pk is None:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC row has no database identity")
    return int(value.pk)


def _optional_pk(value: AccountRbacAuthoritySourceV3Model | None) -> int | None:
    return None if value is None else _pk(value)


def _aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountRbacAuthoritySourceV3Clock",
    "DjangoAccountRbacAuthoritySourceV3Clock",
    "DjangoAccountRbacAuthoritySourceV3Repository",
]
