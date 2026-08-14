"""Closed-world repository for the dormant RBAC mutation-binding ledger.

The repository is intentionally not wired to a production role mutation path.
It only supplies the typed Application read/append boundary.  Every selector
restores the complete local world before applying a PIT filter; malformed rows,
missing Profile/raw-source links, forks, and hidden future tampering fail closed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict as AccountRbacAuthorityRawSourceV3Conflict,
)
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption as AccountRbacAuthorityRawSourceV3Corruption,
)
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Unavailable as AccountRbacAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_rbac_authority_mutation_binding_v3 import (
    PersistedAccountRbacAuthorityMutationBindingV3,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityMutationBindingV3,
    AccountRbacAuthorityProfileStateRefV3,
    AccountRbacAuthoritySourceEpochV3,
    validate_account_rbac_authority_mutation_binding_v3_successor,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    validate_account_rbac_authority_source_v3_successor,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_codec import (
    AccountRbacAuthorityMutationBindingV3CodecError,
    decode_account_rbac_authority_mutation_binding_v3,
    encode_account_rbac_authority_mutation_binding_v3,
)
from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_models import (
    AccountRbacAuthorityMutationBindingV3Model,
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
    _activate_account_rbac_authority_mutation_binding_v3_uow,
    _claim_account_rbac_authority_mutation_binding_v3_insert,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_codec import (
    AccountRbacAuthoritySourceV3CodecError,
    decode_account_rbac_authority_source_v3,
    encode_account_rbac_authority_source_v3,
)


class AccountRbacAuthorityMutationBindingV3Clock(Protocol):
    """Provide an aware repository clock."""

    def now(self) -> datetime: ...


class DjangoAccountRbacAuthorityMutationBindingV3Clock:
    """Use Django's timezone-aware clock."""

    def now(self) -> datetime:
        """Return the current aware server time."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _World:
    epochs: tuple[AccountRbacAuthorityMutationEpochV3AnchorModel, ...]
    profile_anchors: tuple[AccountRbacAuthorityProfileV3AnchorModel, ...]
    profiles: tuple[AccountRbacAuthorityProfileV3VersionModel, ...]
    records: tuple[
        tuple[
            AccountRbacAuthorityMutationBindingV3Model,
            PersistedAccountRbacAuthorityMutationBindingV3,
        ],
        ...,
    ]


_ValueT = TypeVar("_ValueT")


class DjangoAccountRbacAuthorityMutationBindingV3Repository:
    """Persist and replay one append-only mutation chain per source epoch."""

    def __init__(
        self,
        *,
        clock: AccountRbacAuthorityMutationBindingV3Clock | None = None,
        using: str = "default",
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._clock = clock or DjangoAccountRbacAuthorityMutationBindingV3Clock()
        self._using = using
        self._uow: object | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open the repository-owned non-nestable UOW on one alias."""

        if self._uow is not None:
            raise AccountRbacAuthorityRawSourceV3Conflict("nested RBAC mutation binding UOW")
        token = object()
        self._uow = token
        try:
            with (
                transaction.atomic(using=self._using),
                _activate_account_rbac_authority_mutation_binding_v3_uow(token),
            ):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the checked authoritative aware clock."""

        value = self._clock.now()
        if not _aware(value):
            raise AccountRbacAuthorityRawSourceV3Corruption("RBAC repository clock is naive")
        return value

    def get_winner(
        self, *, mutation_id: str, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return one immutable first winner knowable at the PIT cutoff."""

        self._cutoff(as_of)
        values = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if _identity(record.binding)[:3] == (mutation_id, source_id, source_version)
            and record.binding.recorded_at <= as_of
        )
        return _single(values, "RBAC mutation winner")

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the final logical head, including revoked or expired heads."""

        self._cutoff(as_of)
        values = tuple(
            record
            for _, record in self._closed_world(lock=False).records
            if record.binding.epoch.source_id == source_id and record.binding.recorded_at <= as_of
        )
        if not values:
            return None
        return max(values, key=lambda item: item.binding.recorded_at)

    def get_exact_by_hash(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return one exact historical record and never fall back to another hash."""

        self._cutoff(as_of)
        all_records = self._closed_world(lock=False).records
        candidate = tuple(
            record
            for _, record in all_records
            if _identity(record.binding)[:3] == (mutation_id, source_id, source_version)
            or record.binding.content_hash == expected_content_hash
        )
        exact = tuple(
            record
            for record in candidate
            if _identity(record.binding)
            == (mutation_id, source_id, source_version, expected_content_hash)
            and record.binding.recorded_at <= as_of
        )
        if candidate and (len(candidate) != 1 or len(exact) > 1):
            raise AccountRbacAuthorityRawSourceV3Corruption(
                "RBAC mutation exact selector anchors disagree"
            )
        return exact[0] if exact else None

    def append(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        """Append one validated binding through a predecessor CAS."""

        with transaction.atomic(using=self._using):
            return self._append_in_savepoint(
                record,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )

    def _append_in_savepoint(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        checked = _record(record)
        token = self._require_uow()
        binding = checked.binding
        if recorded_at != binding.recorded_at:
            raise AccountRbacAuthorityRawSourceV3Conflict("recorded clock differs from binding")
        if not _aware(recorded_at):
            raise AccountRbacAuthorityRawSourceV3Unavailable("recorded_at must be aware")
        epoch = self._lock_epoch(binding.epoch, token)
        world = self._closed_world(lock=True, permitted_empty_epoch=epoch.pk)
        collisions = tuple(
            existing
            for _, existing in world.records
            if _identity(existing.binding)[:3] == _identity(binding)[:3]
            or existing.binding.identity_hash == binding.identity_hash
            or existing.binding.record_seal == binding.record_seal
            or existing.binding.content_hash == binding.content_hash
        )
        if collisions:
            if len(collisions) == 1 and collisions[0] == checked:
                return collisions[0]
            raise AccountRbacAuthorityRawSourceV3Conflict("RBAC mutation first winner differs")
        chain = tuple(
            (row, existing)
            for row, existing in world.records
            if existing.binding.epoch.source_id == binding.epoch.source_id
        )
        previous_row: AccountRbacAuthorityMutationBindingV3Model | None = None
        previous: PersistedAccountRbacAuthorityMutationBindingV3 | None = None
        if chain:
            previous_row, previous = max(chain, key=lambda item: item[1].binding.recorded_at)
        actual = None if previous is None else previous.binding.content_hash
        if expected_predecessor_hash != actual:
            raise AccountRbacAuthorityRawSourceV3Conflict("RBAC mutation predecessor CAS differs")
        try:
            if previous is None:
                if binding.binding_chain.root_claim_hash is None:
                    raise ValueError("first binding must carry a binding root")
            else:
                validate_account_rbac_authority_mutation_binding_v3_successor(
                    previous.binding, binding
                )
            raw = self._raw_source(binding.authority_source_content_hash)
            if raw is None:
                raise AccountRbacAuthorityRawSourceV3Unavailable(
                    "bound raw RBAC source is unavailable"
                )
            values = _values(
                checked,
                epoch_pk=_pk(epoch),
                raw_source_pk=_pk(raw),
                predecessor_pk=_optional_pk(previous_row),
            )
            with transaction.atomic(using=self._using):
                self._insert(AccountRbacAuthorityMutationBindingV3Model, values, token)
        except IntegrityError as error:
            exact = tuple(
                existing
                for _, existing in self._closed_world(lock=True).records
                if existing == checked
            )
            if len(exact) == 1:
                return exact[0]
            raise AccountRbacAuthorityRawSourceV3Conflict(
                "concurrent RBAC mutation winner differs"
            ) from error
        except (TypeError, ValueError) as error:
            raise AccountRbacAuthorityRawSourceV3Corruption(
                "invalid RBAC mutation binding append"
            ) from error
        restored = self.get_exact_by_hash(
            mutation_id=binding.mutation_id,
            source_id=binding.epoch.source_id,
            source_version=binding.source_version,
            expected_content_hash=binding.content_hash,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation restore mismatch")
        return restored

    def _lock_epoch(
        self, epoch: AccountRbacAuthoritySourceEpochV3, token: object
    ) -> AccountRbacAuthorityMutationEpochV3AnchorModel:
        query = AccountRbacAuthorityMutationEpochV3AnchorModel._base_manager.using(self._using)
        row = query.select_for_update().filter(epoch_id=epoch.epoch_id).first()
        if row is None:
            raise AccountRbacAuthorityRawSourceV3Unavailable("RBAC source epoch is unavailable")
        if not _epoch_matches(row, epoch):
            raise AccountRbacAuthorityRawSourceV3Corruption("RBAC epoch anchor substitution")
        del token
        return row

    def _raw_source(self, content_hash: str) -> AccountRbacAuthoritySourceV3Model | None:
        rows = tuple(
            AccountRbacAuthoritySourceV3Model._base_manager.using(self._using)
            .filter(content_hash=content_hash)
            .all()
        )
        if len(rows) > 1:
            raise AccountRbacAuthorityRawSourceV3Corruption("raw RBAC source hash is ambiguous")
        return rows[0] if rows else None

    def _closed_world(self, *, lock: bool, permitted_empty_epoch: int | None = None) -> _World:
        epoch_query = AccountRbacAuthorityMutationEpochV3AnchorModel._base_manager.using(
            self._using
        ).all()
        profile_anchor_query = AccountRbacAuthorityProfileV3AnchorModel._base_manager.using(
            self._using
        ).all()
        profile_query = AccountRbacAuthorityProfileV3VersionModel._base_manager.using(
            self._using
        ).select_related("anchor", "predecessor")
        record_query = AccountRbacAuthorityMutationBindingV3Model._base_manager.using(
            self._using
        ).select_related("epoch", "authority_source", "predecessor")
        if lock:
            epoch_query = epoch_query.select_for_update()
            profile_anchor_query = profile_anchor_query.select_for_update()
            profile_query = profile_query.select_for_update()
            record_query = record_query.select_for_update()
        epochs = tuple(epoch_query.order_by("pk"))
        profile_anchors = tuple(profile_anchor_query.order_by("pk"))
        profiles = tuple(profile_query.order_by("pk"))
        raw_sources = self._validate_all_raw_sources(lock=lock)
        self._validate_all_profile_versions(profiles)
        epoch_by_pk = {_pk(item): item for item in epochs}
        profile_anchor_by_pk = {_pk(item): item for item in profile_anchors}
        profile_by_ref = {
            (row.profile_id, row.profile_version, row.profile_content_hash): row for row in profiles
        }
        restored: list[
            tuple[
                AccountRbacAuthorityMutationBindingV3Model,
                PersistedAccountRbacAuthorityMutationBindingV3,
            ]
        ] = []
        for row in record_query.order_by("pk"):
            epoch = epoch_by_pk.get(row.epoch_id)
            if epoch is None:
                raise AccountRbacAuthorityRawSourceV3Corruption("binding has no epoch anchor")
            if row.authority_source_id is None:
                raise AccountRbacAuthorityRawSourceV3Corruption("binding has no raw source")
            value = _restore(row, profile_by_ref=profile_by_ref)
            if not _epoch_matches(epoch, value.binding.epoch):
                raise AccountRbacAuthorityRawSourceV3Corruption("binding epoch differs from FK")
            try:
                raw = row.authority_source
            except ObjectDoesNotExist as error:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "binding raw RBAC source FK is missing"
                ) from error
            raw_source = raw_sources.get(raw.content_hash)
            if raw_source is None:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "binding raw RBAC source was not restored"
                )
            if (
                raw.content_hash != value.binding.authority_source_content_hash
                or raw.identity_hash != value.binding.authority_source_identity_hash
                or raw.record_seal != value.binding.authority_source_record_seal
                or raw.source_id != value.binding.epoch.source_id
                or raw.source_version != value.binding.source_version
                or raw_source.chain.root_claim_hash
                != value.binding.authority_source_chain.root_claim_hash
                or raw_source.chain.supersedes_content_hash
                != value.binding.authority_source_chain.supersedes_content_hash
            ):
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "binding raw RBAC source link differs"
                )
            for profile in (value.binding.subject, value.binding.old_subject):
                if profile is None:
                    continue
                linked = profile_by_ref.get(
                    (profile.profile_id, profile.profile_version, profile.profile_content_hash)
                )
                if linked is None or linked.anchor_id not in profile_anchor_by_pk:
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "binding Profile reference is not an exact persisted version"
                    )
                if (
                    linked.identity_hash != profile.identity_hash
                    or linked.content_hash != profile.content_hash
                    or linked.observed_at != profile.observed_at
                    or linked.user_id != profile.user_id
                    or linked.subject_actor_id != profile.subject_actor_id
                    or linked.rbac_role != profile.rbac_role
                ):
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "binding Profile version scalar substitution"
                    )
            restored.append((row, value))
        self._validate_graph(
            epochs,
            profile_anchors,
            profiles,
            tuple(restored),
            permitted_empty_epoch,
        )
        return _World(epochs, profile_anchors, profiles, tuple(restored))

    def _validate_all_profile_versions(
        self, profiles: tuple[AccountRbacAuthorityProfileV3VersionModel, ...]
    ) -> None:
        """Restore every exact Profile projection before selector filtering."""

        for row in profiles:
            try:
                state = AccountRbacAuthorityProfileStateRefV3(
                    row.profile_id,
                    row.profile_version,
                    row.profile_content_hash,
                    row.rbac_role,
                    row.user_id,
                    row.subject_actor_id,
                    row.observed_at,
                    row.identity_hash,
                    row.content_hash,
                )
                expected_payload = {
                    "state": state.to_payload(),
                    "root_claim_hash": row.root_claim_hash,
                    "supersedes_content_hash": row.supersedes_content_hash,
                    "predecessor_id": row.predecessor_id,
                    "record_seal": row.record_seal,
                }
                expected_record_seal = _hash(
                    {
                        "state": state.to_payload(),
                        "root_claim_hash": row.root_claim_hash,
                        "supersedes_content_hash": row.supersedes_content_hash,
                        "predecessor_id": row.predecessor_id,
                    }
                )
                if row.record_seal != expected_record_seal:
                    raise ValueError("Profile authority record seal mismatch")
                if row.canonical_payload != expected_payload:
                    raise ValueError("Profile authority payload is not canonical")
            except (TypeError, ValueError) as error:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "Profile authority closed-world restore failed"
                ) from error

    def _validate_all_raw_sources(self, *, lock: bool) -> dict[str, AccountRbacAuthoritySourceV3]:
        """Restore every raw RBAC row before a binding selector can hide tamper."""

        anchor_query = AccountRbacAuthoritySourceV3AnchorModel._base_manager.using(
            self._using
        ).all()
        query = AccountRbacAuthoritySourceV3Model._base_manager.using(self._using).all()
        if lock:
            anchor_query = anchor_query.select_for_update()
            query = query.select_for_update()
        anchors = tuple(anchor_query.order_by("pk"))
        anchor_by_pk = {_pk(anchor): anchor for anchor in anchors}
        raw_rows: dict[
            int, list[tuple[AccountRbacAuthoritySourceV3Model, AccountRbacAuthoritySourceV3]]
        ] = {}
        restored: dict[str, AccountRbacAuthoritySourceV3] = {}
        for row in query.order_by("pk"):
            try:
                source = decode_account_rbac_authority_source_v3(row.canonical_payload)
                if encode_account_rbac_authority_source_v3(source) != row.canonical_payload:
                    raise ValueError("raw RBAC payload is not canonical")
                projected = {
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
                    "rbac_seal": source.rbac_seal,
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
                    "persisted_at": source.clock.recorded_at,
                }
                for name, value in projected.items():
                    if getattr(row, name) != value:
                        raise ValueError(f"raw RBAC scalar mismatch: {name}")
                recorder = {
                    "is_automated": row.recorded_by_is_automated,
                    "kind": row.recorded_by_kind,
                    "role": row.recorded_by_role,
                    "service_id": row.recorded_by_service_id,
                }
                if (
                    row.recorded_by_kind != "service"
                    or row.recorded_by_role != "account_actor_authority_raw_recorder"
                    or row.recorded_by_is_automated is not True
                ):
                    raise ValueError("raw RBAC recorder fixed semantics mismatch")
                expected_recorder_seal = _hash(
                    {"content_hash": source.content_hash, "recorder": recorder}
                )
                if row.recorder_binding_seal != expected_recorder_seal:
                    raise ValueError("raw RBAC recorder binding mismatch")
                expected_ledger_seal = _hash(
                    {
                        "content_hash": source.content_hash,
                        "predecessor_pk": row.predecessor_id,
                        "recorder_binding_seal": expected_recorder_seal,
                        "record_seal": source.record_seal,
                        "root_lock_pk": row.anchor_id,
                        "persisted_at": _time(source.clock.recorded_at),
                    }
                )
                if row.ledger_seal != expected_ledger_seal:
                    raise ValueError("raw RBAC ledger seal mismatch")
                if row.anchor_id not in anchor_by_pk:
                    raise ValueError("raw RBAC source has no exact anchor")
                restored[source.content_hash] = source
                raw_rows.setdefault(int(row.anchor_id), []).append((row, source))
            except (AccountRbacAuthoritySourceV3CodecError, TypeError, ValueError) as error:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "raw RBAC source closed-world restore failed"
                ) from error
        for anchor in anchors:
            chain = raw_rows.get(_pk(anchor), [])
            if not chain:
                raise AccountRbacAuthorityRawSourceV3Corruption("orphan raw RBAC anchor")
            if any(source.identity.source_id != anchor.source_id for _, source in chain):
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "raw RBAC anchor source identity differs"
                )
            roots = tuple(item for item in chain if item[0].predecessor_id is None)
            if len(roots) != 1:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "raw RBAC source chain must have one root"
                )
            root_row, root = roots[0]
            if root.chain.root_claim_hash != anchor.root_claim_hash:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "raw RBAC anchor root claim differs"
                )
            by_predecessor: dict[
                int, list[tuple[AccountRbacAuthoritySourceV3Model, AccountRbacAuthoritySourceV3]]
            ] = {}
            for item in chain:
                if item[0].predecessor_id is not None:
                    by_predecessor.setdefault(int(item[0].predecessor_id), []).append(item)
            visited = {_pk(root_row)}
            current_row, current = root_row, root
            while successors := by_predecessor.get(_pk(current_row), []):
                if len(successors) != 1:
                    raise AccountRbacAuthorityRawSourceV3Corruption("raw RBAC source chain forks")
                next_row, successor = successors[0]
                if _pk(next_row) in visited:
                    raise AccountRbacAuthorityRawSourceV3Corruption("raw RBAC source chain cycles")
                try:
                    validate_account_rbac_authority_source_v3_successor(current, successor)
                except (TypeError, ValueError) as error:
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "raw RBAC source successor is invalid"
                    ) from error
                visited.add(_pk(next_row))
                current_row, current = next_row, successor
            if len(visited) != len(chain):
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "raw RBAC source chain disconnected"
                )
        return restored

    def _validate_graph(
        self,
        epochs: tuple[AccountRbacAuthorityMutationEpochV3AnchorModel, ...],
        profile_anchors: tuple[AccountRbacAuthorityProfileV3AnchorModel, ...],
        profiles: tuple[AccountRbacAuthorityProfileV3VersionModel, ...],
        records: tuple[
            tuple[
                AccountRbacAuthorityMutationBindingV3Model,
                PersistedAccountRbacAuthorityMutationBindingV3,
            ],
            ...,
        ],
        permitted_empty_epoch: int | None,
    ) -> None:
        for epoch in epochs:
            chain = tuple(item for item in records if item[0].epoch_id == _pk(epoch))
            if not chain:
                if permitted_empty_epoch != _pk(epoch):
                    raise AccountRbacAuthorityRawSourceV3Corruption("orphan RBAC epoch anchor")
                continue
            roots = tuple(item for item in chain if item[0].predecessor_id is None)
            if len(roots) != 1:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "RBAC mutation chain must have one root"
                )
            root_row, root = roots[0]
            if root.binding.epoch.root_claim_hash != epoch.root_claim_hash:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "RBAC epoch root differs from binding"
                )
            by_predecessor: dict[
                int,
                list[
                    tuple[
                        AccountRbacAuthorityMutationBindingV3Model,
                        PersistedAccountRbacAuthorityMutationBindingV3,
                    ]
                ],
            ] = {}
            for item in chain:
                if item[0].predecessor_id is not None:
                    by_predecessor.setdefault(item[0].predecessor_id, []).append(item)
            visited = {_pk(root_row)}
            current_row, current = root_row, root
            while successors := by_predecessor.get(_pk(current_row), []):
                if len(successors) != 1:
                    raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation chain forks")
                next_row, successor = successors[0]
                if _pk(next_row) in visited:
                    raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation chain cycles")
                try:
                    validate_account_rbac_authority_mutation_binding_v3_successor(
                        current.binding, successor.binding
                    )
                except (TypeError, ValueError) as error:
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "RBAC mutation successor is invalid"
                    ) from error
                visited.add(_pk(next_row))
                current_row, current = next_row, successor
            if len(visited) != len(chain):
                raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation chain disconnected")
        anchor_ids = {_pk(anchor) for anchor in profile_anchors}
        profiles_by_anchor: dict[int, list[AccountRbacAuthorityProfileV3VersionModel]] = {}
        for profile in profiles:
            if profile.anchor_id is None or int(profile.anchor_id) not in anchor_ids:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "Profile authority version has no exact anchor"
                )
            profiles_by_anchor.setdefault(int(profile.anchor_id), []).append(profile)
        for anchor in profile_anchors:
            profile_chain = profiles_by_anchor.get(_pk(anchor), [])
            if not profile_chain:
                raise AccountRbacAuthorityRawSourceV3Corruption("orphan Profile authority anchor")
            profile_roots = [row for row in profile_chain if row.predecessor_id is None]
            if len(profile_roots) != 1:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "Profile authority chain must have one root"
                )
            profile_root = profile_roots[0]
            for profile_row in profile_chain:
                if (
                    profile_row.profile_id != anchor.profile_id
                    or profile_row.user_id != anchor.user_id
                    or profile_row.subject_actor_id != anchor.subject_actor_id
                ):
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "Profile authority anchor identity differs from version"
                    )
            if profile_root.root_claim_hash != anchor.root_claim_hash:
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "Profile authority root claim differs from anchor"
                )
            profile_by_predecessor: dict[int, list[AccountRbacAuthorityProfileV3VersionModel]] = {}
            for row in profile_chain:
                if row.predecessor_id is not None:
                    profile_by_predecessor.setdefault(int(row.predecessor_id), []).append(row)
            visited = {_pk(profile_root)}
            profile_current = profile_root
            current_observed_at = profile_root.observed_at
            while profile_successors := profile_by_predecessor.get(_pk(profile_current), []):
                if len(profile_successors) != 1:
                    raise AccountRbacAuthorityRawSourceV3Corruption("Profile authority chain forks")
                previous_profile = profile_current
                profile_current = profile_successors[0]
                if profile_current.observed_at <= current_observed_at:
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "Profile authority clock does not advance"
                    )
                if (
                    profile_current.supersedes_content_hash != previous_profile.content_hash
                    or profile_current.profile_version == previous_profile.profile_version
                    or profile_current.content_hash == previous_profile.content_hash
                ):
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "Profile authority predecessor binding differs"
                    )
                if _pk(profile_current) in visited:
                    raise AccountRbacAuthorityRawSourceV3Corruption(
                        "Profile authority chain cycles"
                    )
                visited.add(_pk(profile_current))
                current_observed_at = profile_current.observed_at
            if len(visited) != len(profile_chain):
                raise AccountRbacAuthorityRawSourceV3Corruption(
                    "Profile authority chain disconnected"
                )

    def _insert(
        self, model_type: type[models.Model], values: dict[str, object], token: object
    ) -> None:
        with _claim_account_rbac_authority_mutation_binding_v3_insert(
            token=token, model_type=model_type, expected_values=values
        ):
            model_type._default_manager.using(self._using).create(**values)

    def _require_uow(self) -> object:
        if self._uow is None:
            raise AccountRbacAuthorityRawSourceV3Conflict("append requires private UOW")
        return self._uow

    def _cutoff(self, as_of: datetime) -> None:
        if not _aware(as_of):
            raise AccountRbacAuthorityRawSourceV3Unavailable("as_of must be timezone-aware")
        if as_of > self.now():
            raise AccountRbacAuthorityRawSourceV3Unavailable("future as_of is forbidden")


def _values(
    record: PersistedAccountRbacAuthorityMutationBindingV3,
    *,
    epoch_pk: int,
    raw_source_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    """Project the nested Domain object into every persisted scalar and seal."""

    binding = record.binding
    epoch = binding.epoch
    subject = binding.subject
    old = binding.old_subject
    operator = binding.operator
    issuer = binding.issuer
    values: dict[str, object] = {
        "epoch_id": epoch_pk,
        "authority_source_id": raw_source_pk,
        "predecessor_id": predecessor_pk,
        "mutation_id": binding.mutation_id,
        "mutation_kind": binding.mutation_kind,
        "source_id": epoch.source_id,
        "source_version": binding.source_version,
        "old_authority_state": binding.old_authority_state,
        "new_authority_state": binding.new_authority_state,
        "old_rbac_role": binding.old_rbac_role,
        "new_rbac_role": binding.new_rbac_role,
        "profile_id": subject.profile_id,
        "profile_version": subject.profile_version,
        "profile_content_hash": subject.profile_content_hash,
        "profile_identity_hash": subject.identity_hash,
        "profile_observed_at": subject.observed_at,
        "subject_actor_id": subject.subject_actor_id,
        "user_id": subject.user_id,
        "subject_seal": binding.subject_seal,
        "operator_principal_id": operator.principal_id,
        "operator_user_id": operator.user_id,
        "operator_actor_id": operator.actor_id,
        "operator_is_authenticated": operator.is_authenticated,
        "operator_is_active": operator.is_active,
        "operator_is_staff": operator.is_staff,
        "operator_is_superuser": operator.is_superuser,
        "operator_rbac_role": operator.rbac_role,
        "operator_authentication_source_id": operator.authentication_source_id,
        "operator_authentication_source_version": operator.authentication_source_version,
        "operator_authentication_source_content_hash": operator.authentication_source_content_hash,
        "operator_user_source_id": operator.user_source_id,
        "operator_user_source_version": operator.user_source_version,
        "operator_user_source_content_hash": operator.user_source_content_hash,
        "operator_rbac_source_id": operator.rbac_source_id,
        "operator_rbac_source_version": operator.rbac_source_version,
        "operator_rbac_source_content_hash": operator.rbac_source_content_hash,
        "operator_observed_at": operator.observed_at,
        "operator_valid_until": operator.valid_until,
        "operator_identity_hash": operator.identity_hash,
        "operator_authority_hash": operator.authority_hash,
        "issuer_service_id": issuer.service_id,
        "issuer_role": issuer.role,
        "issuer_kind": issuer.kind,
        "issuer_is_automated": issuer.is_automated,
        "issuer_identity_hash": issuer.identity_hash,
        "authority_source_identity_hash": binding.authority_source_identity_hash,
        "authority_source_content_hash": binding.authority_source_content_hash,
        "authority_source_record_seal": binding.authority_source_record_seal,
        "observed_at": binding.observed_at,
        "issued_at": binding.issued_at,
        "recorded_at": binding.recorded_at,
        "valid_until": binding.valid_until,
        "binding_root_claim_hash": binding.binding_chain.root_claim_hash,
        "binding_supersedes_content_hash": binding.binding_chain.supersedes_content_hash,
        "source_root_claim_hash": binding.authority_source_chain.root_claim_hash,
        "source_supersedes_content_hash": binding.authority_source_chain.supersedes_content_hash,
        "identity_hash": binding.identity_hash,
        "transition_seal": binding.transition_seal,
        "operator_seal": binding.operator_seal,
        "issuer_seal": binding.issuer_seal,
        "source_binding_seal": binding.source_binding_seal,
        "clock_seal": binding.clock_seal,
        "binding_chain_seal": binding.binding_chain_seal,
        "authority_source_chain_seal": binding.authority_source_chain_seal,
        "fixed_authority_seal": binding.fixed_authority_seal,
        "record_seal": binding.record_seal,
        "content_hash": binding.content_hash,
        "owner": binding.owner,
        "artifact_type": binding.artifact_type,
        "schema": binding.schema,
        "permission": binding.permission,
        "status": binding.status,
        "must_not_execute": binding.must_not_execute,
        "execution_allowed": binding.execution_allowed,
        "canonical_payload": encode_account_rbac_authority_mutation_binding_v3(binding),
        "persisted_at": binding.recorded_at,
    }
    if old is None:
        for name in (
            "old_profile_id",
            "old_profile_version",
            "old_profile_content_hash",
            "old_profile_identity_hash",
            "old_profile_observed_at",
            "old_subject_actor_id",
            "old_user_id",
        ):
            values[name] = None
    else:
        values.update(
            {
                "old_profile_id": old.profile_id,
                "old_profile_version": old.profile_version,
                "old_profile_content_hash": old.profile_content_hash,
                "old_profile_identity_hash": old.identity_hash,
                "old_profile_observed_at": old.observed_at,
                "old_subject_actor_id": old.subject_actor_id,
                "old_user_id": old.user_id,
            }
        )
    values["old_subject_seal"] = binding.old_subject_seal
    values["ledger_seal"] = _ledger_seal(
        content_hash=binding.content_hash,
        record_seal=binding.record_seal,
        epoch_pk=epoch_pk,
        raw_source_pk=raw_source_pk,
        predecessor_pk=predecessor_pk,
        persisted_at=binding.recorded_at,
    )
    return values


def _restore(
    row: AccountRbacAuthorityMutationBindingV3Model,
    *,
    profile_by_ref: dict[tuple[str, str, str], AccountRbacAuthorityProfileV3VersionModel],
) -> PersistedAccountRbacAuthorityMutationBindingV3:
    try:
        binding = decode_account_rbac_authority_mutation_binding_v3(row.canonical_payload)
        expected = _values(
            PersistedAccountRbacAuthorityMutationBindingV3(binding),
            epoch_pk=_pk(row.epoch),
            raw_source_pk=_pk(row.authority_source),
            predecessor_pk=None if row.predecessor_id is None else int(row.predecessor_id),
        )
        for ref in (binding.subject, binding.old_subject):
            if (
                ref is not None
                and (ref.profile_id, ref.profile_version, ref.profile_content_hash)
                not in profile_by_ref
            ):
                raise ValueError("Profile reference is not linked to a persisted version")
    except (
        AccountRbacAuthorityMutationBindingV3CodecError,
        ObjectDoesNotExist,
        TypeError,
        ValueError,
    ) as error:
        raise AccountRbacAuthorityRawSourceV3Corruption(
            "RBAC mutation payload is corrupt"
        ) from error
    for name, value in expected.items():
        if name in {"epoch_id", "authority_source_id", "predecessor_id"}:
            continue
        if getattr(row, name) != value:
            raise AccountRbacAuthorityRawSourceV3Corruption(
                f"RBAC mutation ledger mismatch: {name}"
            )
    return PersistedAccountRbacAuthorityMutationBindingV3(binding)


def _epoch_matches(
    row: AccountRbacAuthorityMutationEpochV3AnchorModel, epoch: AccountRbacAuthoritySourceEpochV3
) -> bool:
    return (
        row.epoch_id,
        row.target_user_id,
        row.subject_actor_id,
        row.source_id,
        row.epoch_sequence,
        row.opened_at,
        row.previous_epoch_content_hash,
        row.terminal_authority_source_content_hash,
        row.terminal_mutation_binding_content_hash,
        row.root_claim_hash,
        row.identity_hash,
        row.content_hash,
    ) == (
        epoch.epoch_id,
        epoch.target_user_id,
        epoch.subject_actor_id,
        epoch.source_id,
        epoch.epoch_sequence,
        epoch.opened_at,
        epoch.previous_epoch_content_hash,
        epoch.terminal_authority_source_content_hash,
        epoch.terminal_mutation_binding_content_hash,
        epoch.root_claim_hash,
        epoch.identity_hash,
        epoch.content_hash,
    )


def _identity(binding: AccountRbacAuthorityMutationBindingV3) -> tuple[str, str, str, str]:
    return (
        binding.mutation_id,
        binding.epoch.source_id,
        binding.source_version,
        binding.content_hash,
    )


def _record(value: object) -> PersistedAccountRbacAuthorityMutationBindingV3:
    if type(value) is not PersistedAccountRbacAuthorityMutationBindingV3:
        raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation record type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountRbacAuthorityRawSourceV3Corruption(
            "RBAC mutation record is corrupt"
        ) from error
    return value


def _ledger_seal(
    *,
    content_hash: str,
    record_seal: str,
    epoch_pk: int,
    raw_source_pk: int,
    predecessor_pk: int | None,
    persisted_at: datetime,
) -> str:
    return _hash(
        {
            "authority_source_pk": raw_source_pk,
            "content_hash": content_hash,
            "epoch_pk": epoch_pk,
            "persisted_at": _time(persisted_at),
            "predecessor_pk": predecessor_pk,
            "record_seal": record_seal,
        }
    )


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _single(values: tuple[_ValueT, ...], label: str) -> _ValueT | None:
    if len(values) > 1:
        raise AccountRbacAuthorityRawSourceV3Corruption(f"{label} is ambiguous")
    return values[0] if values else None


def _pk(value: models.Model) -> int:
    if value.pk is None:
        raise AccountRbacAuthorityRawSourceV3Corruption("RBAC mutation row has no primary key")
    return int(value.pk)


def _optional_pk(value: AccountRbacAuthorityMutationBindingV3Model | None) -> int | None:
    return None if value is None else _pk(value)


def _aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountRbacAuthorityMutationBindingV3Clock",
    "DjangoAccountRbacAuthorityMutationBindingV3Clock",
    "DjangoAccountRbacAuthorityMutationBindingV3Repository",
]
