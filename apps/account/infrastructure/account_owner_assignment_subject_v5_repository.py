"""PostgreSQL persistence for immutable Account owner Subject V5 evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    AccountOwnerAssignmentProvenanceReceiptV5Conflict,
    AccountOwnerAssignmentProvenanceReceiptV5Corruption,
    AccountOwnerAssignmentProvenanceReceiptV5Unavailable,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5Conflict,
    AccountOwnerAssignmentSubjectV5Corruption,
    AccountOwnerAssignmentSubjectV5Unavailable,
    PersistedAccountOwnerAssignmentSubjectV5,
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
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_record_codec import (
    decode_account_owner_assignment_subject_v5_record,
    encode_account_owner_assignment_subject_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
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


class AccountOwnerAssignmentSubjectV5Clock(Protocol):
    """Supply an explicit aware persistence clock."""

    def now(self) -> datetime:
        """Return the current server time."""
        ...


class DjangoAccountOwnerAssignmentSubjectV5Repository:
    """Store Subject V5 rows while leaving current authority to Application readers."""

    def __init__(
        self,
        *,
        using: str = "default",
        clock: AccountOwnerAssignmentSubjectV5Clock | None = None,
    ) -> None:
        """Bind the subject and every durable parent query to one database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using
        self._clock = clock
        self._uow: object | None = None
        self._receipts = DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(
            using=using, clock=clock
        )
        self._bindings = DjangoCanonicalAccountCreationConsumptionRepository(
            using=using, clock=clock
        )
        self._reobservations = DjangoCanonicalAccountOwnershipReobservationV1Repository(
            using=using, clock=clock
        )

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one private same-alias PostgreSQL unit of work."""

        self._postgresql()
        if self._uow is not None:
            raise AccountOwnerAssignmentSubjectV5Conflict("nested Subject V5 UOW")
        token = object()
        self._uow = token
        try:
            with transaction.atomic(using=self._using), _activate_assignment_v5_uow(token):
                yield
        except DatabaseError as error:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "Subject V5 transaction unavailable"
            ) from error
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return an aware server clock without synthesizing source observation time."""

        self._postgresql()
        return _aware(self._clock.now() if self._clock else timezone.now())

    def get_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentSubjectV5 | None:
        """Return the immutable identity winner once it was knowable."""

        cutoff = self._cutoff(as_of)
        return next(
            (
                record
                for _, record in self._world(cutoff)
                if (record.subject.subject_id, record.subject.subject_version)
                == (subject_id, subject_version)
                and record.subject.requested_at <= cutoff
            ),
            None,
        )

    def get_exact_by_hash(
        self,
        *,
        subject_id: str,
        subject_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentSubjectV5 | None:
        """Return exact historical evidence without applying current TTL rules."""

        cutoff = self._cutoff(as_of)
        anchors = tuple(
            record
            for _, record in self._world(cutoff)
            if (
                record.subject.subject_id == subject_id
                and record.subject.subject_version == subject_version
            )
            or record.subject.content_hash == expected_content_hash
        )
        matches = tuple(
            record
            for record in anchors
            if record.subject.subject_id == subject_id
            and record.subject.subject_version == subject_version
            and record.subject.content_hash == expected_content_hash
            and record.subject.requested_at <= cutoff
        )
        if anchors and (len(anchors) != 1 or len(matches) > 1):
            raise AccountOwnerAssignmentSubjectV5Corruption("Subject V5 exact anchors disagree")
        return matches[0] if matches else None

    def append(
        self,
        record: PersistedAccountOwnerAssignmentSubjectV5,
        *,
        requested_at: datetime,
    ) -> PersistedAccountOwnerAssignmentSubjectV5:
        """Lock exact parents and append or replay one Subject V5 first winner."""

        token = self._require_uow()
        try:
            record.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "invalid Subject V5 append envelope"
            ) from error
        subject = record.subject
        if _aware(requested_at) != subject.requested_at:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "Subject V5 requested_at differs from the sealed value"
            )
        existing = self._locked_identity(subject.subject_id, subject.subject_version)
        if existing is not None:
            restored = self._restore(existing)
            if restored == record:
                return restored
            raise AccountOwnerAssignmentSubjectV5Conflict(
                "Subject V5 identity has another first winner"
            )
        binding_row = self._lock_binding(record)
        reobservation_row = self._lock_reobservation(record)
        receipt_row = self._lock_receipt(record)
        self._restore_parents(record, receipt_row, binding_row, reobservation_row)
        values: dict[str, object] = {
            "receipt": receipt_row,
            "binding": binding_row,
            "reobservation": reobservation_row,
            "subject_id": subject.subject_id,
            "subject_version": subject.subject_version,
            "owner": subject.owner,
            "artifact_type": subject.artifact_type,
            "schema": subject.schema,
            "permission": subject.permission,
            "status": subject.status,
            "requested_at": subject.requested_at,
            "valid_until": subject.valid_until,
            "persisted_at": subject.requested_at,
            "identity_hash": subject.identity_hash,
            "content_hash": subject.content_hash,
            "canonical_payload": encode_account_owner_assignment_subject_v5_record(record),
            "record_seal": record.record_seal,
            "ledger_seal": record.ledger_seal,
        }
        row = AccountOwnerAssignmentSubjectV5Model(**values)
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_assignment_v5_insert(
                    token=token,
                    using=self._using,
                    model_type=AccountOwnerAssignmentSubjectV5Model,
                    values=values,
                ),
            ):
                row.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._locked_identity(subject.subject_id, subject.subject_version)
            if winner is not None:
                restored = self._restore(winner)
                if restored == record:
                    return restored
            raise AccountOwnerAssignmentSubjectV5Conflict(
                "concurrent Subject V5 first winner differs"
            ) from None
        return self._restore(row)

    def _locked_identity(
        self, subject_id: str, subject_version: str
    ) -> AccountOwnerAssignmentSubjectV5Model | None:
        return (
            AccountOwnerAssignmentSubjectV5Model._default_manager.using(self._using)
            .select_for_update()
            .select_related("receipt", "binding", "reobservation")
            .filter(subject_id=subject_id, subject_version=subject_version)
            .first()
        )

    def _lock_binding(
        self, record: PersistedAccountOwnerAssignmentSubjectV5
    ) -> CanonicalAccountCreationBindingV2Model:
        subject = record.subject
        rows = tuple(
            CanonicalAccountCreationBindingV2Model._default_manager.using(self._using)
            .select_for_update()
            .filter(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                identity_hash=subject.binding.identity_hash,
                content_hash=subject.binding.content_hash,
            )
        )
        if len(rows) != 1:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "exact Binding V2 parent is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_reobservation(
        self, record: PersistedAccountOwnerAssignmentSubjectV5
    ) -> CanonicalAccountOwnershipReobservationV1Model:
        subject = record.subject
        rows = tuple(
            CanonicalAccountOwnershipReobservationV1Model._default_manager.using(self._using)
            .select_for_update()
            .filter(
                observation_id=subject.reobservation.observation_id,
                observation_version=subject.reobservation.observation_version,
                identity_hash=subject.reobservation.identity_hash,
                content_hash=subject.reobservation.content_hash,
            )
        )
        if len(rows) != 1:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "exact Reobservation V1 parent is unavailable or ambiguous"
            )
        return rows[0]

    def _lock_receipt(
        self, record: PersistedAccountOwnerAssignmentSubjectV5
    ) -> AccountOwnerAssignmentProvenanceReceiptV5Model:
        subject = record.subject
        rows = tuple(
            AccountOwnerAssignmentProvenanceReceiptV5Model._default_manager.using(self._using)
            .select_for_update()
            .filter(
                receipt_id=subject.receipt.receipt_id,
                receipt_version=subject.receipt.receipt_version,
                identity_hash=subject.receipt.identity_hash,
                content_hash=subject.receipt.content_hash,
            )
        )
        if len(rows) != 1:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "exact Receipt V5 row is unavailable or ambiguous"
            )
        return rows[0]

    def _restore_parents(
        self,
        record: PersistedAccountOwnerAssignmentSubjectV5,
        receipt_row: AccountOwnerAssignmentProvenanceReceiptV5Model,
        binding_row: CanonicalAccountCreationBindingV2Model,
        reobservation_row: CanonicalAccountOwnershipReobservationV1Model,
    ) -> None:
        """Restore and compare the exact Receipt, Binding, and Reobservation roots."""

        subject = record.subject
        try:
            receipt = self._receipts.get_exact_by_hash(
                receipt_id=subject.receipt.receipt_id,
                receipt_version=subject.receipt.receipt_version,
                expected_content_hash=subject.receipt.content_hash,
                as_of=subject.requested_at,
            )
            binding = self._bindings.get_exact_by_hash(
                binding_id=subject.binding.binding_id,
                binding_version=subject.binding.binding_version,
                expected_content_hash=subject.binding.content_hash,
                as_of=subject.requested_at,
            )
            reobservation = self._reobservations.get_exact_by_hash(
                observation_id=subject.reobservation.observation_id,
                observation_version=subject.reobservation.observation_version,
                expected_content_hash=subject.reobservation.content_hash,
                as_of=subject.requested_at,
            )
        except (
            AccountOwnerAssignmentProvenanceReceiptV5Conflict,
            AccountOwnerAssignmentProvenanceReceiptV5Corruption,
            AccountOwnerAssignmentProvenanceReceiptV5Unavailable,
            CanonicalAccountCreationBindingV2Conflict,
            CanonicalAccountCreationBindingV2Corruption,
            CanonicalAccountCreationBindingV2Unavailable,
            CanonicalAccountOwnershipReobservationV1Conflict,
            CanonicalAccountOwnershipReobservationV1Corruption,
        ) as error:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "Subject V5 parent evidence is unavailable or corrupt"
            ) from error
        if (
            receipt is None
            or receipt.receipt != subject.receipt
            or type(binding) is not CanonicalAccountCreationBindingV2
            or binding != subject.binding
            or type(reobservation) is not PersistedCanonicalAccountOwnershipReobservationV1
            or reobservation.reobservation != subject.reobservation
            or receipt_row.identity_hash != subject.receipt.identity_hash
            or receipt_row.content_hash != subject.receipt.content_hash
            or binding_row.identity_hash != subject.binding.identity_hash
            or binding_row.content_hash != subject.binding.content_hash
            or reobservation_row.identity_hash != subject.reobservation.identity_hash
            or reobservation_row.content_hash != subject.reobservation.content_hash
        ):
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "Subject V5 parent type, FK, or identity substitution"
            )

    def _restore(
        self, row: AccountOwnerAssignmentSubjectV5Model
    ) -> PersistedAccountOwnerAssignmentSubjectV5:
        try:
            record = decode_account_owner_assignment_subject_v5_record(row.canonical_payload)
            subject = record.subject
            self._restore_parents(record, row.receipt, row.binding, row.reobservation)
            expected = (
                subject.subject_id,
                subject.subject_version,
                subject.owner,
                subject.artifact_type,
                subject.schema,
                subject.permission,
                subject.status,
                subject.requested_at,
                subject.valid_until,
                subject.requested_at,
                subject.identity_hash,
                subject.content_hash,
                record.record_seal,
                record.ledger_seal,
                subject.receipt.content_hash,
                subject.binding.content_hash,
                subject.reobservation.content_hash,
            )
            observed = (
                row.subject_id,
                row.subject_version,
                row.owner,
                row.artifact_type,
                row.schema,
                row.permission,
                row.status,
                row.requested_at,
                row.valid_until,
                row.persisted_at,
                row.identity_hash,
                row.content_hash,
                row.record_seal,
                row.ledger_seal,
                row.receipt.content_hash,
                row.binding.content_hash,
                row.reobservation.content_hash,
            )
            if observed != expected:
                raise ValueError("Subject V5 row differs from its sealed envelope")
            return record
        except (AttributeError, TypeError, ValueError) as error:
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "persisted Subject V5 row is invalid"
            ) from error

    def _world(self, as_of: datetime) -> tuple[
        tuple[AccountOwnerAssignmentSubjectV5Model, PersistedAccountOwnerAssignmentSubjectV5],
        ...,
    ]:
        self._postgresql()
        try:
            rows = tuple(
                AccountOwnerAssignmentSubjectV5Model._default_manager.using(self._using)
                .select_related("receipt", "binding", "reobservation")
                .order_by("requested_at", "pk")
            )
            world = tuple((row, self._restore(row)) for row in rows)
            _validate_world(world)
            return world
        except (ConnectionDoesNotExist, DatabaseError) as error:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "Subject V5 ledger read is unavailable"
            ) from error

    def _require_uow(self) -> object:
        if self._uow is None or not connections[self._using].in_atomic_block:
            raise AccountOwnerAssignmentSubjectV5Conflict(
                "Subject V5 append requires repository UOW"
            )
        return self._uow

    def _postgresql(self) -> None:
        try:
            connection = connections[self._using]
        except ConnectionDoesNotExist as error:
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "Subject V5 database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentSubjectV5Unavailable(
                "Subject V5 ledger requires PostgreSQL"
            )

    def _cutoff(self, as_of: datetime) -> datetime:
        """Validate an aware historical cutoff and reject future reads."""

        cutoff = _aware(as_of)
        if cutoff > self.now():
            raise AccountOwnerAssignmentSubjectV5Unavailable("future Subject V5 as_of is forbidden")
        return cutoff


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentSubjectV5Corruption("expected aware datetime")
    return value


def _validate_world(
    world: tuple[
        tuple[AccountOwnerAssignmentSubjectV5Model, PersistedAccountOwnerAssignmentSubjectV5],
        ...,
    ],
) -> None:
    """Reject repeated Subject identity/content anchors or receipt registrations."""

    identities: set[tuple[str, str]] = set()
    identity_hashes: set[str] = set()
    content_hashes: set[str] = set()
    receipts: set[str] = set()
    for _, record in world:
        subject = record.subject
        identity = (subject.subject_id, subject.subject_version)
        if (
            identity in identities
            or subject.identity_hash in identity_hashes
            or subject.content_hash in content_hashes
            or subject.receipt.content_hash in receipts
        ):
            raise AccountOwnerAssignmentSubjectV5Corruption(
                "Subject V5 world contains duplicate immutable anchors"
            )
        identities.add(identity)
        identity_hashes.add(subject.identity_hash)
        content_hashes.add(subject.content_hash)
        receipts.add(subject.receipt.content_hash)


__all__ = [
    "AccountOwnerAssignmentSubjectV5Clock",
    "DjangoAccountOwnerAssignmentSubjectV5Repository",
]
