"""PostgreSQL persistence for inactive Account owner provenance ReceiptV5."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol, overload

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5Conflict,
    AccountOwnerAssignmentProvenanceReceiptV5Corruption,
    AccountOwnerAssignmentProvenanceReceiptV5Unavailable,
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Conflict,
    CanonicalAccountOwnershipReobservationV1Corruption,
    PersistedCanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5,
    validate_account_owner_assignment_provenance_receipt_v5_root,
    validate_account_owner_assignment_provenance_receipt_v5_successor,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_record_codec import (
    AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError,
    decode_account_owner_assignment_provenance_receipt_v5_record,
    encode_account_owner_assignment_provenance_receipt_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    _activate_assignment_v5_uow,
    _claim_assignment_v5_insert,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_Row = tuple[
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    PersistedAccountOwnerAssignmentProvenanceReceiptV5,
]


class AccountOwnerAssignmentProvenanceReceiptV5Clock(Protocol):
    """Supply one authoritative aware persistence clock."""

    def now(self) -> datetime:
        """Return the current server timestamp."""
        ...


class DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
    AccountOwnerAssignmentProvenanceReceiptV5Unavailable
):
    """The PostgreSQL ledger or a required parent is unavailable."""


class DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
    AccountOwnerAssignmentProvenanceReceiptV5Conflict
):
    """An immutable ReceiptV5 identity or logical predecessor has another winner."""


class DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
    AccountOwnerAssignmentProvenanceReceiptV5Corruption
):
    """A ReceiptV5 row, envelope, or durable parent is substituted or corrupt."""


class DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository:
    """Restore the complete ReceiptV5 world before every historical selection."""

    __slots__ = (
        "_bindings",
        "_clock",
        "_policies",
        "_reobservations",
        "_token",
        "_uow",
        "_using",
    )

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountOwnerAssignmentProvenanceReceiptV5Clock | None = None,
    ) -> None:
        """Bind the receipt and all parent repositories to one explicit alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using
        self._clock = clock
        self._token = object()
        self._uow: object | None = None
        self._bindings = DjangoCanonicalAccountCreationConsumptionRepository(
            using=using, clock=clock
        )
        self._policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using, clock=clock)
        self._reobservations = DjangoCanonicalAccountOwnershipReobservationV1Repository(
            using=using, clock=clock
        )

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nestable private UOW on the configured PostgreSQL alias."""

        self._postgresql()
        if self._uow is not None:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict("nested ReceiptV5 UOW")
        self._uow = self._token
        try:
            with transaction.atomic(using=self._using), _activate_assignment_v5_uow(self._token):
                yield
        except DatabaseError as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 transaction is unavailable"
            ) from error
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return the validated aware persistence clock."""

        self._postgresql()
        value = self._clock.now() if self._clock is not None else timezone.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 repository clock is naive"
            )
        return value

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return the immutable identity winner knowable at ``as_of``."""

        self._cutoff(as_of)
        world = self._world(as_of)
        matches = tuple(
            record
            for _, record in world
            if record.receipt.receipt_id == receipt_id
            and record.receipt.receipt_version == receipt_version
            and record.receipt.recorded_at <= as_of
        )
        return _single(matches, "ReceiptV5 identity")

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return exact historical identity/content evidence without TTL filtering."""

        self._cutoff(as_of)
        world = self._world(as_of)
        anchors = tuple(
            record
            for _, record in world
            if (
                record.receipt.receipt_id == receipt_id
                and record.receipt.receipt_version == receipt_version
            )
            or record.receipt.content_hash == expected_content_hash
        )
        matches = tuple(
            record
            for record in anchors
            if (
                record.receipt.receipt_id == receipt_id
                and record.receipt.receipt_version == receipt_version
                and record.receipt.content_hash == expected_content_hash
                and record.receipt.recorded_at <= as_of
            )
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 exact anchors disagree"
            )
        return matches[0] if matches else None

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
        """Return the final logical head visible at ``as_of``, including expiry."""

        self._cutoff(as_of)
        world = self._world(as_of)
        chain = _chain(tuple(item for item in world if item[1].receipt.receipt_id == receipt_id))
        visible = tuple(item for item in chain if item[1].receipt.recorded_at <= as_of)
        return visible[-1][1] if visible else None

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV5,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        """Append or replay one exact root/successor after ordered parent locks."""

        self._postgresql()
        self._require_uow()
        checked = _record(record)
        receipt = checked.receipt
        if not _is_aware(recorded_at) or recorded_at != receipt.recorded_at:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 recorded_at differs from the exact receipt"
            )
        cutoff = self.now()
        if recorded_at > cutoff:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 recorded_at is in the future"
            )
        if expected_predecessor_hash != receipt.supersedes_content_hash:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 predecessor selector differs"
            )

        self._lock_policy_identity(receipt.policy.policy_id)
        policy_row = self._lock_policy(receipt)
        binding_row = self._lock_binding(receipt)
        reobservation_row = self._lock_reobservation(receipt)
        self._lock_receipt_chain(receipt.receipt_id)
        self._restore_parents(receipt, policy_row, binding_row, reobservation_row)

        world = self._world(cutoff)
        anchors = tuple(
            item
            for item in world
            if (
                item[1].receipt.receipt_id == receipt.receipt_id
                and item[1].receipt.receipt_version == receipt.receipt_version
            )
            or item[1].receipt.identity_hash == receipt.identity_hash
            or item[1].receipt.content_hash == receipt.content_hash
        )
        future_identity = tuple(
            item
            for item in anchors
            if item[1].receipt.receipt_id == receipt.receipt_id
            and item[1].receipt.receipt_version == receipt.receipt_version
            and item[1].receipt.recorded_at > cutoff
        )
        if future_identity:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 repository returned a future first winner"
            )
        if anchors:
            exact = tuple(item[1] for item in anchors if item[1] == checked)
            if len(anchors) == 1 and len(exact) == 1:
                return exact[0]
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 first-winner anchors differ"
            )

        chain = _chain(
            tuple(item for item in world if item[1].receipt.receipt_id == receipt.receipt_id)
        )
        head = chain[-1] if chain else None
        if head is not None and head[1].receipt.recorded_at > cutoff:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 logical head is in the future"
            )
        actual_predecessor = head[1].receipt.content_hash if head else None
        if actual_predecessor != expected_predecessor_hash:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 predecessor compare-and-swap failed"
            )
        try:
            if head is None:
                validate_account_owner_assignment_provenance_receipt_v5_root(receipt)
            else:
                validate_account_owner_assignment_provenance_receipt_v5_successor(
                    head[1].receipt, receipt
                )
        except (TypeError, ValueError) as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 root or successor validation failed"
            ) from error
        values = _model_values(
            checked,
            policy_pk=_pk(policy_row, "PolicyV1"),
            binding_pk=_pk(binding_row, "BindingV2"),
            reobservation_pk=_pk(reobservation_row, "ReobservationV1"),
            predecessor_pk=head[0].pk if head is not None else None,
        )
        model = AccountOwnerAssignmentProvenanceReceiptV5Model(**values)
        model._state.db = self._using
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_assignment_v5_insert(
                    token=self._token,
                    using=self._using,
                    model_type=AccountOwnerAssignmentProvenanceReceiptV5Model,
                    values=values,
                ),
            ):
                model.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            after = self._world(cutoff)
            replay = tuple(
                item[1]
                for item in after
                if item[1].receipt.receipt_id == receipt.receipt_id
                and item[1].receipt.receipt_version == receipt.receipt_version
                and item[1].receipt.recorded_at <= cutoff
            )
            if len(replay) == 1 and replay[0] == checked:
                return replay[0]
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 concurrent first winner differs"
            ) from error
        restored = self._world(recorded_at)
        exact = tuple(
            item[1]
            for item in restored
            if item[1].receipt.receipt_id == receipt.receipt_id
            and item[1].receipt.receipt_version == receipt.receipt_version
            and item[1].receipt.recorded_at <= recorded_at
        )
        if len(exact) != 1 or exact[0] != checked:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 append restore mismatch"
            )
        return exact[0]

    def _postgresql(self) -> None:
        """Require the configured alias to use PostgreSQL."""

        try:
            vendor = connections[self._using].vendor
        except (ConnectionDoesNotExist, DatabaseError) as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 database alias is unavailable"
            ) from error
        if vendor != "postgresql":
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 ledger requires PostgreSQL"
            )

    def _cutoff(self, as_of: datetime) -> None:
        """Validate one historical cutoff and forbid reads from the future."""

        if not _is_aware(as_of):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 as_of must be timezone-aware"
            )
        if as_of > self.now():
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "future ReceiptV5 as_of is forbidden"
            )

    def _require_uow(self) -> object:
        """Require the repository's own private atomic context."""

        try:
            in_atomic_block = connections[self._using].in_atomic_block
        except ConnectionDoesNotExist as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 database alias is unavailable"
            ) from error
        if self._uow is None or not in_atomic_block:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict(
                "ReceiptV5 append requires private UOW"
            )
        return self._uow

    def _lock_policy_identity(self, policy_id: str) -> None:
        """Share the PolicyV1 writer's advisory identity lock before parent proof."""

        try:
            with connections[self._using].cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    [policy_id],
                )
        except (ConnectionDoesNotExist, DatabaseError) as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 PolicyV1 serialization lock is unavailable"
            ) from error

    def _lock_policy(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5
    ) -> SingleOwnerAuthorityPolicyV1Model:
        """Lock the exact PolicyV1 row first."""

        rows = list(
            SingleOwnerAuthorityPolicyV1Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                policy_id=receipt.policy.policy_id,
                policy_version=receipt.policy.policy_version,
                identity_hash=receipt.policy.identity_hash,
                content_hash=receipt.policy.content_hash,
            )
            .order_by("pk")
        )
        if len(rows) != 1:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 exact PolicyV1 parent is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_binding(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5
    ) -> CanonicalAccountCreationBindingV2Model:
        """Lock the exact permanent BindingV2 row second."""

        rows = list(
            CanonicalAccountCreationBindingV2Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                identity_hash=receipt.binding.identity_hash,
                content_hash=receipt.binding.content_hash,
            )
            .order_by("pk")
        )
        if len(rows) != 1:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 exact BindingV2 parent is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_reobservation(
        self, receipt: AccountOwnerAssignmentProvenanceReceiptV5
    ) -> CanonicalAccountOwnershipReobservationV1Model:
        """Lock the exact ReobservationV1 row third."""

        rows = list(
            CanonicalAccountOwnershipReobservationV1Model._base_manager.using(self._using)
            .select_for_update()
            .filter(
                observation_id=receipt.reobservation.observation_id,
                observation_version=receipt.reobservation.observation_version,
                identity_hash=receipt.reobservation.identity_hash,
                content_hash=receipt.reobservation.content_hash,
            )
            .order_by("pk")
        )
        if len(rows) != 1:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 exact ReobservationV1 parent is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_receipt_chain(
        self, receipt_id: str
    ) -> tuple[AccountOwnerAssignmentProvenanceReceiptV5Model, ...]:
        """Lock every predecessor/head candidate after the three parent locks."""

        return tuple(
            AccountOwnerAssignmentProvenanceReceiptV5Model._base_manager.using(self._using)
            .select_for_update()
            .filter(receipt_id=receipt_id)
            .order_by("recorded_at", "pk")
        )

    def _restore_parents(
        self,
        receipt: AccountOwnerAssignmentProvenanceReceiptV5,
        policy_row: SingleOwnerAuthorityPolicyV1Model,
        binding_row: CanonicalAccountCreationBindingV2Model,
        reobservation_row: CanonicalAccountOwnershipReobservationV1Model,
    ) -> None:
        """Restore and compare all exact parent Domain values through public repositories."""

        try:
            policy = self._policies.get_exact_current(
                policy_id=receipt.policy.policy_id,
                policy_version=receipt.policy.policy_version,
                expected_content_hash=receipt.policy.content_hash,
                as_of=receipt.recorded_at,
            )
            binding = self._bindings.get_exact_by_hash(
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                expected_content_hash=receipt.binding.content_hash,
                as_of=receipt.recorded_at,
            )
            reobservation = self._reobservations.get_exact_by_hash(
                observation_id=receipt.reobservation.observation_id,
                observation_version=receipt.reobservation.observation_version,
                expected_content_hash=receipt.reobservation.content_hash,
                as_of=receipt.recorded_at,
            )
        except (
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentUnavailable,
            CanonicalAccountCreationBindingV2Conflict,
            CanonicalAccountCreationBindingV2Corruption,
            CanonicalAccountCreationBindingV2Unavailable,
            CanonicalAccountOwnershipReobservationV1Conflict,
            CanonicalAccountOwnershipReobservationV1Corruption,
        ) as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 parent repository evidence is unavailable or corrupt"
            ) from error
        if (
            type(policy) is not SingleOwnerAuthorityPolicyV1
            or policy != receipt.policy
            or type(binding) is not CanonicalAccountCreationBindingV2
            or binding != receipt.binding
            or type(reobservation) is not PersistedCanonicalAccountOwnershipReobservationV1
        ):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 parent type or identity substitution"
            )
        if (
            policy_row.policy_id != receipt.policy.policy_id
            or policy_row.policy_version != receipt.policy.policy_version
            or policy_row.identity_hash != receipt.policy.identity_hash
            or policy_row.content_hash != receipt.policy.content_hash
            or binding_row.binding_id != receipt.binding.binding_id
            or binding_row.binding_version != receipt.binding.binding_version
            or binding_row.identity_hash != receipt.binding.identity_hash
            or binding_row.content_hash != receipt.binding.content_hash
            or reobservation_row.observation_id != receipt.reobservation.observation_id
            or reobservation_row.observation_version != receipt.reobservation.observation_version
            or reobservation_row.identity_hash != receipt.reobservation.identity_hash
            or reobservation_row.content_hash != receipt.reobservation.content_hash
        ):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 foreign-key parent anchor substitution"
            )
        if reobservation.reobservation != receipt.reobservation:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 ReobservationV1 parent identity substitution"
            )

    def _world(self, as_of: datetime) -> tuple[_Row, ...]:
        """Restore every ReceiptV5 row and validate every chain before selection."""

        self._postgresql()
        if not _is_aware(as_of):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 as_of must be timezone-aware"
            )
        try:
            rows = tuple(
                AccountOwnerAssignmentProvenanceReceiptV5Model._base_manager.using(
                    self._using
                ).order_by("recorded_at", "pk")
            )
            world = tuple((row, _restore(row, self)) for row in rows)
            _validate_world(world)
            return world
        except DatabaseError as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable(
                "ReceiptV5 ledger read is unavailable"
            ) from error


def _restore(
    row: AccountOwnerAssignmentProvenanceReceiptV5Model,
    repository: DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Decode one row and cross-check all model fields and parent FKs."""

    try:
        record = decode_account_owner_assignment_provenance_receipt_v5_record(row.canonical_payload)
        policy_row = _parent_row(
            SingleOwnerAuthorityPolicyV1Model,
            repository._using,
            row.policy_id,
            "PolicyV1",
        )
        binding_row = _parent_row(
            CanonicalAccountCreationBindingV2Model,
            repository._using,
            row.binding_id,
            "BindingV2",
        )
        reobservation_row = _parent_row(
            CanonicalAccountOwnershipReobservationV1Model,
            repository._using,
            row.reobservation_id,
            "ReobservationV1",
        )
        repository._restore_parents(record.receipt, policy_row, binding_row, reobservation_row)
        expected = _model_values(
            record,
            policy_pk=_pk(policy_row, "PolicyV1"),
            binding_pk=_pk(binding_row, "BindingV2"),
            reobservation_pk=_pk(reobservation_row, "ReobservationV1"),
            predecessor_pk=_optional_pk(row, "predecessor_id"),
        )
        _match_model(row, expected)
        return record
    except DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption:
        raise
    except (
        AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError,
        AttributeError,
        TypeError,
        ValueError,
    ) as error:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "ReceiptV5 row payload, parent, or model fields are corrupt"
        ) from error


def _model_values(
    record: PersistedAccountOwnerAssignmentProvenanceReceiptV5,
    *,
    policy_pk: int,
    binding_pk: int,
    reobservation_pk: int,
    predecessor_pk: int | None,
) -> dict[str, object]:
    """Build every ReceiptV5 model column from the exact full envelope."""

    checked = _record(record)
    receipt = checked.receipt
    if not _is_aware(receipt.recorded_at) or not _is_aware(receipt.issued_at):
        raise ValueError("ReceiptV5 clocks must be aware")
    if checked.receipt.recorded_at != receipt.recorded_at:
        raise ValueError("ReceiptV5 recorded clock differs")
    return {
        "policy_id": policy_pk,
        "binding_id": binding_pk,
        "reobservation_id": reobservation_pk,
        "predecessor_id": predecessor_pk,
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "account_namespace": receipt.account_namespace,
        "account_id": receipt.account_id,
        "underlying_unified_account_namespace": receipt.underlying_unified_account_namespace,
        "underlying_unified_account_id": receipt.underlying_unified_account_id,
        "assigned_owner_user_id": receipt.assigned_owner_user_id,
        "owner": receipt.owner,
        "artifact_type": receipt.artifact_type,
        "schema": receipt.schema,
        "permission": receipt.permission,
        "status": receipt.status,
        "issued_at": receipt.issued_at,
        "recorded_at": receipt.recorded_at,
        "valid_until": receipt.valid_until,
        "persisted_at": receipt.recorded_at,
        "supersedes_content_hash": receipt.supersedes_content_hash,
        "identity_hash": receipt.identity_hash,
        "content_hash": receipt.content_hash,
        "canonical_payload": encode_account_owner_assignment_provenance_receipt_v5_record(checked),
        "record_seal": checked.record_seal,
        "ledger_seal": checked.ledger_seal,
    }


def _match_model(
    row: AccountOwnerAssignmentProvenanceReceiptV5Model,
    expected: dict[str, object],
) -> None:
    """Reject every scalar, FK, clock, payload, and seal substitution."""

    for name, expected_value in expected.items():
        if getattr(row, name) != expected_value:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                f"ReceiptV5 model field {name} differs from canonical record"
            )


@overload
def _parent_row(
    model: type[SingleOwnerAuthorityPolicyV1Model],
    using: str,
    primary_key: object,
    label: str,
) -> SingleOwnerAuthorityPolicyV1Model: ...


@overload
def _parent_row(
    model: type[CanonicalAccountCreationBindingV2Model],
    using: str,
    primary_key: object,
    label: str,
) -> CanonicalAccountCreationBindingV2Model: ...


@overload
def _parent_row(
    model: type[CanonicalAccountOwnershipReobservationV1Model],
    using: str,
    primary_key: object,
    label: str,
) -> CanonicalAccountOwnershipReobservationV1Model: ...


def _parent_row(
    model: (
        type[SingleOwnerAuthorityPolicyV1Model]
        | type[CanonicalAccountCreationBindingV2Model]
        | type[CanonicalAccountOwnershipReobservationV1Model]
    ),
    using: str,
    primary_key: object,
    label: str,
) -> (
    SingleOwnerAuthorityPolicyV1Model
    | CanonicalAccountCreationBindingV2Model
    | CanonicalAccountOwnershipReobservationV1Model
):
    """Restore one exact foreign-key row through the configured alias."""

    if type(primary_key) is not int or primary_key <= 0:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            f"ReceiptV5 {label} FK is invalid"
        )
    try:
        return model._base_manager.using(using).get(pk=primary_key)
    except model.DoesNotExist as error:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            f"ReceiptV5 {label} FK row is unavailable"
        ) from error


def _pk(row: object, label: str) -> int:
    """Read one positive concrete parent primary key."""

    value = getattr(row, "pk", None)
    if type(value) is not int or value <= 0:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            f"ReceiptV5 {label} parent has no primary key"
        )
    return value


def _optional_pk(row: object, name: str) -> int | None:
    """Read one nullable positive predecessor primary key."""

    value = getattr(row, name, None)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            f"ReceiptV5 {name} is invalid"
        )
    return value


def _record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5:
    """Require one exact sealed persisted application envelope."""

    if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV5:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "ReceiptV5 record type substitution"
        )
    try:
        return decode_account_owner_assignment_provenance_receipt_v5_record(
            encode_account_owner_assignment_provenance_receipt_v5_record(value)
        )
    except (
        AccountOwnerAssignmentProvenanceReceiptV5RecordCodecError,
        TypeError,
        ValueError,
    ) as error:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "ReceiptV5 record envelope is corrupt"
        ) from error


def _validate_world(world: tuple[_Row, ...]) -> None:
    """Validate closed identity/content anchors and every root/successor chain."""

    identity: dict[tuple[str, str], _Row] = {}
    identity_hashes: dict[str, _Row] = {}
    content: dict[str, _Row] = {}
    receipt_ids: set[str] = set()
    for row, record in world:
        key = (record.receipt.receipt_id, record.receipt.receipt_version)
        if key in identity:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 identity anchor repeats"
            )
        if (
            record.receipt.content_hash in content
            or record.receipt.identity_hash in identity_hashes
        ):
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 identity/content anchor repeats"
            )
        identity[key] = (row, record)
        identity_hashes[record.receipt.identity_hash] = (row, record)
        content[record.receipt.content_hash] = (row, record)
        receipt_ids.add(record.receipt.receipt_id)
    for receipt_id in receipt_ids:
        _chain(tuple(item for item in world if item[1].receipt.receipt_id == receipt_id))


def _chain(rows: tuple[_Row, ...]) -> tuple[_Row, ...]:
    """Return one connected root-to-head chain and reject forks or orphans."""

    if not rows:
        return ()
    roots = tuple(item for item in rows if item[1].receipt.supersedes_content_hash is None)
    by_hash = {record.receipt.content_hash: (row, record) for row, record in rows}
    if len(roots) != 1 or len(by_hash) != len(rows):
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "ReceiptV5 chain root/content count is invalid"
        )
    children: dict[str, _Row] = {}
    for row, record in rows:
        predecessor_hash = record.receipt.supersedes_content_hash
        predecessor_id = _optional_pk(row, "predecessor_id")
        if predecessor_hash is None:
            if predecessor_id is not None:
                raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                    "ReceiptV5 root predecessor FK is not null"
                )
            continue
        previous = by_hash.get(predecessor_hash)
        if previous is None or predecessor_hash in children or predecessor_id != previous[0].pk:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 chain predecessor is not closed"
            )
        try:
            validate_account_owner_assignment_provenance_receipt_v5_successor(
                previous[1].receipt, record.receipt
            )
        except (TypeError, ValueError) as error:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
                "ReceiptV5 successor validation failed"
            ) from error
        children[predecessor_hash] = (row, record)
    ordered = [roots[0]]
    visited = {roots[0][1].receipt.content_hash}
    while ordered[-1][1].receipt.content_hash in children:
        child = children[ordered[-1][1].receipt.content_hash]
        if child[1].receipt.content_hash in visited:
            raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption("ReceiptV5 chain cycle")
        ordered.append(child)
        visited.add(child[1].receipt.content_hash)
    if len(ordered) != len(rows):
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            "ReceiptV5 chain is disconnected"
        )
    return tuple(ordered)


def _single(
    values: tuple[PersistedAccountOwnerAssignmentProvenanceReceiptV5, ...], label: str
) -> PersistedAccountOwnerAssignmentProvenanceReceiptV5 | None:
    """Return zero or one exact match and reject duplicate anchors."""

    if len(values) > 1:
        raise DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption(
            f"ReceiptV5 {label} is ambiguous"
        )
    return values[0] if values else None


def _is_aware(value: object) -> bool:
    """Return whether a value is an aware datetime."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV5Clock",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV5Conflict",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV5Corruption",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository",
    "DjangoAccountOwnerAssignmentProvenanceReceiptV5Unavailable",
]
