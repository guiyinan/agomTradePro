"""PostgreSQL receipt-v4 persistence with exact durable evidence parents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    validate_account_owner_assignment_provenance_receipt_v4_root,
    validate_account_owner_assignment_provenance_receipt_v4_successor,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_models import (
    AccountOwnerAssignmentProvenanceReceiptV4Model,
    _activate_receipt_v4_uow,
    _claim_receipt_v4_insert,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_record_codec import (
    decode_account_owner_assignment_provenance_receipt_v4_record,
    encode_account_owner_assignment_provenance_receipt_v4_record,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_Row = tuple[
    AccountOwnerAssignmentProvenanceReceiptV4Model,
    PersistedAccountOwnerAssignmentProvenanceReceiptV4,
]


class AccountOwnerAssignmentProvenanceReceiptV4Clock(Protocol):
    """Supply an explicit aware persistence clock."""

    def now(self) -> datetime:
        """Return the current server time."""
        ...


class DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository:
    """Store immutable evidence; current authorization requires the Application reader."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountOwnerAssignmentProvenanceReceiptV4Clock | None = None,
    ) -> None:
        """Bind every parent and receipt query to one explicit database alias."""
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using
        self._clock = clock
        self._uow: object | None = None
        self._bindings = DjangoCanonicalAccountCreationConsumptionRepository(using=using)
        self._policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using)
        self._actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=using)

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Allow an outer same-alias transaction, but reject private UOW reentry."""
        self._postgresql()
        if self._uow is not None:
            raise AccountOwnerAssignmentConflict("nested receipt v4 UOW")
        token = object()
        self._uow = token
        try:
            with transaction.atomic(using=self._using), _activate_receipt_v4_uow(token):
                yield
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable("receipt v4 transaction unavailable") from error
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return a validated aware clock without deriving any source observation time."""
        self._postgresql()
        return _aware(self._clock.now() if self._clock else timezone.now())

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Restore the entire receipt ledger before selecting a historical first winner."""
        return next(
            (
                record
                for _, record in self._world(as_of)
                if (record.receipt.receipt_id, record.receipt.receipt_version)
                == (receipt_id, receipt_version)
                and record.receipt.recorded_at <= as_of
            ),
            None,
        )

    def get_exact_by_hash(
        self, *, receipt_id: str, receipt_version: str, expected_content_hash: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return only the exact historical identity/hash, without fallback."""
        record = self.get_winner(
            receipt_id=receipt_id, receipt_version=receipt_version, as_of=as_of
        )
        return (
            record
            if record is not None and record.receipt.content_hash == expected_content_hash
            else None
        )

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return the knowable logical head, including an expired head, for current checks."""
        chain = tuple(
            item for item in self._world(as_of) if item[1].receipt.receipt_id == receipt_id
        )
        visible = tuple(item for item in _chain(chain) if item[1].receipt.recorded_at <= as_of)
        return visible[-1][1] if visible else None

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
        """Append an exact first winner or compare-and-swap successor with durable parents."""
        self._postgresql()
        if self._uow is None:
            raise AccountOwnerAssignmentConflict("receipt append requires private UOW")
        checked = _record(record)
        receipt = checked.receipt
        if _aware(recorded_at) != receipt.recorded_at or recorded_at > self.now():
            raise AccountOwnerAssignmentCorruption("receipt persistence clock mismatch")
        if expected_predecessor_hash != receipt.supersedes_content_hash:
            raise AccountOwnerAssignmentConflict("receipt predecessor selector mismatch")
        with connections[self._using].cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ["receipt-v4:" + receipt.receipt_id],
            )
            # Share the policy writer's exact key before taking any parent row
            # locks. A successor may already hold this advisory lock while its
            # FK waits for the predecessor row, so reversing this order deadlocks.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [receipt.policy.policy_id],
            )
        world = self._world(recorded_at)
        winner = next(
            (
                item
                for _, item in world
                if (item.receipt.receipt_id, item.receipt.receipt_version)
                == (receipt.receipt_id, receipt.receipt_version)
            ),
            None,
        )
        if winner is not None:
            if winner != checked:
                raise AccountOwnerAssignmentConflict("receipt identity first winner differs")
            return winner
        chain = _chain(
            tuple(item for item in world if item[1].receipt.receipt_id == receipt.receipt_id)
        )
        head = chain[-1] if chain else None
        if (head[1].receipt.content_hash if head else None) != expected_predecessor_hash:
            raise AccountOwnerAssignmentConflict("receipt predecessor CAS failed")
        try:
            if head is None:
                validate_account_owner_assignment_provenance_receipt_v4_root(receipt)
            else:
                validate_account_owner_assignment_provenance_receipt_v4_successor(
                    head[1].receipt, receipt
                )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentConflict("invalid receipt chain append") from error
        binding_pk, policy_pk, actor_pk = self._parents(checked, lock=True)
        values = _values(checked, binding_pk, policy_pk, actor_pk, head[0].pk if head else None)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_receipt_v4_insert(token=self._uow, using=self._using, values=values),
            ):
                AccountOwnerAssignmentProvenanceReceiptV4Model._default_manager.using(
                    self._using
                ).create(**values)
        except IntegrityError as error:
            winner = self.get_winner(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                as_of=recorded_at,
            )
            if winner == checked:
                return winner
            raise AccountOwnerAssignmentConflict(
                "receipt first winner or successor conflict"
            ) from error
        restored = self.get_winner(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentCorruption("receipt append restore mismatch")
        return restored

    def _postgresql(self) -> None:
        if connections[self._using].vendor != "postgresql":
            raise AccountOwnerAssignmentUnavailable("receipt v4 requires PostgreSQL")

    def _world(self, as_of: datetime) -> tuple[_Row, ...]:
        self._postgresql()
        _aware(as_of)
        try:
            rows = tuple(
                AccountOwnerAssignmentProvenanceReceiptV4Model._default_manager.using(
                    self._using
                ).order_by("pk")
            )
            world = tuple((row, _restore(row)) for row in rows)
            for row, record in world:
                parents = self._parents(record, lock=False)
                if parents != (
                    _fk(row, "binding_id"),
                    _fk(row, "policy_id"),
                    _fk(row, "actor_source_id"),
                ):
                    raise AccountOwnerAssignmentCorruption("receipt parent FK substitution")
            for receipt_id in {record.receipt.receipt_id for _, record in world}:
                _chain(tuple(item for item in world if item[1].receipt.receipt_id == receipt_id))
            return world
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable("receipt ledger read unavailable") from error

    def _parents(
        self, record: PersistedAccountOwnerAssignmentProvenanceReceiptV4, *, lock: bool
    ) -> tuple[int, int, int]:
        receipt, authority = record.receipt, record.authority
        binding = receipt.binding
        binding_rows = CanonicalAccountCreationBindingV2Model.objects.using(self._using)
        policy_rows = SingleOwnerAuthorityPolicyV1Model._default_manager.using(self._using)
        actor_rows = AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.using(self._using)
        if lock:
            binding_rows, policy_rows, actor_rows = (
                binding_rows.select_for_update(),
                policy_rows.select_for_update(),
                actor_rows.select_for_update(),
            )
        binding_row = binding_rows.filter(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            content_hash=binding.content_hash,
        ).first()
        policy_row = policy_rows.filter(
            policy_id=receipt.policy.policy_id,
            policy_version=receipt.policy.policy_version,
            content_hash=receipt.policy_content_hash,
        ).first()
        actor_row = actor_rows.filter(
            source_id=authority.source_id,
            source_version=authority.source_version,
            content_hash=authority.source_content_hash,
        ).first()
        if binding_row is None or policy_row is None or actor_row is None:
            raise AccountOwnerAssignmentCorruption("receipt durable parent unavailable")
        stored_binding = self._bindings.get_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=receipt.issued_at,
        )
        stored_policy = self._policies.get_exact_current(
            policy_id=receipt.policy.policy_id,
            policy_version=receipt.policy.policy_version,
            expected_content_hash=receipt.policy_content_hash,
            as_of=receipt.recorded_at,
        )
        stored_actor = self._actors.get_exact_by_hash(
            source_id=authority.source_id,
            source_version=authority.source_version,
            expected_content_hash=authority.source_content_hash,
            as_of=receipt.issued_at,
        )
        actor_head = self._actors.get_current_head(
            source_id=authority.source_id, as_of=receipt.recorded_at
        )
        if (
            stored_binding is None
            or stored_binding.binding != binding
            or stored_policy != receipt.policy
            or stored_actor is None
            or actor_head != stored_actor
        ):
            raise AccountOwnerAssignmentCorruption("receipt durable parent seal mismatch")
        source = stored_actor.source
        projected = CurrentAccountActorAuthorityV3(
            source.principal_id,
            source.user_id,
            source.authentication_context_content_hash,
            source.actor_id,
            source.is_authenticated,
            source.is_active,
            source.is_staff,
            source.is_superuser,
            source.rbac_role,
            source.source_id,
            source.source_version,
            source.content_hash,
            source.recorded_at,
            source.valid_until,
        )
        if projected != authority or not source.is_temporally_current_at(receipt.issued_at):
            raise AccountOwnerAssignmentCorruption("receipt actor projection substitution")
        return binding_row.pk, policy_row.pk, actor_row.pk


def _record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    try:
        if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV4:
            raise TypeError("expected exact receipt v4 record")
        return decode_account_owner_assignment_provenance_receipt_v4_record(
            encode_account_owner_assignment_provenance_receipt_v4_record(value)
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("invalid receipt v4 record") from error


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentCorruption("receipt clock must be aware")
    return value


def _fk(row: AccountOwnerAssignmentProvenanceReceiptV4Model, name: str) -> int | None:
    value = row.__dict__.get(name)
    if value is not None and (type(value) is not int or value <= 0):
        raise AccountOwnerAssignmentCorruption("receipt FK is invalid")
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _values(
    record: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
    binding_pk: int,
    policy_pk: int,
    actor_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    receipt = record.receipt
    payload = encode_account_owner_assignment_provenance_receipt_v4_record(record)
    return {
        "binding_id": binding_pk,
        "policy_id": policy_pk,
        "actor_source_id": actor_pk,
        "predecessor_id": predecessor_pk,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "owner": receipt.owner,
        "artifact_type": receipt.artifact_type,
        "schema": receipt.schema,
        "permission": receipt.permission,
        "status": receipt.status,
        "issued_at": receipt.issued_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": receipt.valid_until,
        "persisted_at": receipt.recorded_at,
        "identity_hash": receipt.identity_hash,
        "content_hash": receipt.content_hash,
        "supersedes_content_hash": receipt.supersedes_content_hash,
        "canonical_payload": payload,
        "record_seal": _hash(payload),
        "ledger_seal": _hash(
            {
                "domain": "account.receipt.v4/ledger",
                "record": payload,
                "binding_pk": binding_pk,
                "policy_pk": policy_pk,
                "actor_pk": actor_pk,
                "predecessor_pk": predecessor_pk,
            }
        ),
    }


def _restore(
    row: AccountOwnerAssignmentProvenanceReceiptV4Model,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    try:
        record = decode_account_owner_assignment_provenance_receipt_v4_record(row.canonical_payload)
        binding_pk, policy_pk, actor_pk = (
            _fk(row, "binding_id"),
            _fk(row, "policy_id"),
            _fk(row, "actor_source_id"),
        )
        if binding_pk is None or policy_pk is None or actor_pk is None:
            raise ValueError("receipt has missing parents")
        for name, value in _values(
            record, binding_pk, policy_pk, actor_pk, _fk(row, "predecessor_id")
        ).items():
            if getattr(row, name) != value:
                raise ValueError("receipt ledger field mismatch: " + name)
        return record
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("receipt ledger payload/seal mismatch") from error


def _chain(rows: tuple[_Row, ...]) -> tuple[_Row, ...]:
    if not rows:
        return ()
    roots = tuple(item for item in rows if item[1].receipt.supersedes_content_hash is None)
    by_hash = {record.receipt.content_hash: (row, record) for row, record in rows}
    if len(roots) != 1 or len(by_hash) != len(rows):
        raise AccountOwnerAssignmentCorruption("receipt chain root/hash count")
    children: dict[str, _Row] = {}
    for row, record in rows:
        previous_hash = record.receipt.supersedes_content_hash
        if previous_hash is None:
            if _fk(row, "predecessor_id") is not None:
                raise AccountOwnerAssignmentCorruption("receipt root predecessor FK mismatch")
            continue
        previous = by_hash.get(previous_hash)
        if (
            previous is None
            or previous_hash in children
            or _fk(row, "predecessor_id") != previous[0].pk
        ):
            raise AccountOwnerAssignmentCorruption("receipt chain is not closed")
        try:
            validate_account_owner_assignment_provenance_receipt_v4_successor(
                previous[1].receipt, record.receipt
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("invalid receipt successor") from error
        children[previous_hash] = (row, record)
    ordered = [roots[0]]
    visited = {roots[0][1].receipt.content_hash}
    while ordered[-1][1].receipt.content_hash in children:
        child = children[ordered[-1][1].receipt.content_hash]
        if child[1].receipt.content_hash in visited:
            raise AccountOwnerAssignmentCorruption("receipt chain cycle")
        ordered.append(child)
        visited.add(child[1].receipt.content_hash)
    if len(ordered) != len(rows):
        raise AccountOwnerAssignmentCorruption("receipt chain disconnected")
    return tuple(ordered)
