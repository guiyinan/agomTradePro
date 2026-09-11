"""PostgreSQL storage for closed, policy-bound owner-assignment evidence V4."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models import Model
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    PersistedAccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import AccountOwnerAssignmentSubjectV4
from apps.account.infrastructure import account_actor_authority_raw_source_models_v3 as raw_models
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_codec import (
    decode_account_owner_assignment_subject_v4,
    encode_account_owner_assignment_subject_v4,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
    AccountOwnerAssignmentSubjectV4Model,
    _activate_assignment_v4_uow,
    _claim_assignment_v4_insert,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_record_codec import (
    decode_account_owner_assignment_evidence_v4_record,
    encode_account_owner_assignment_evidence_v4_record,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_models import (
    AccountOwnerAssignmentProvenanceReceiptV4Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


class AccountOwnerAssignmentEvidenceV4Clock(Protocol):
    """Supply an explicit aware server clock."""

    def now(self) -> datetime:
        """Return the server's current time."""
        ...


@dataclass(frozen=True)
class _World:
    subjects: tuple[
        tuple[AccountOwnerAssignmentSubjectV4Model, AccountOwnerAssignmentSubjectV4], ...
    ]
    evidence: tuple[
        tuple[AccountOwnerAssignmentEvidenceV4Model, PersistedAccountOwnerAssignmentEvidenceV4], ...
    ]


_T = TypeVar("_T")


class DjangoAccountOwnerAssignmentEvidenceV4Repository:
    """Restore all stored evidence and parents before selecting or appending a root."""

    def __init__(
        self, *, using: str = "default", clock: AccountOwnerAssignmentEvidenceV4Clock | None = None
    ) -> None:
        """Bind the complete graph to one database alias and optional test clock."""
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using
        self._clock = clock
        self._uow: object | None = None
        self._receipts = DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=using)
        self._policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=using)
        self._actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=using)

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Allow outer same-alias transactions while rejecting private UOW reentry."""
        self._postgresql()
        if self._uow is not None:
            raise AccountOwnerAssignmentConflict("nested assignment v4 UOW")
        token = object()
        self._uow = token
        try:
            with transaction.atomic(using=self._using), _activate_assignment_v4_uow(token):
                yield
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable("assignment transaction unavailable") from error
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Read the aware persistence clock without replacing source observation times."""
        self._postgresql()
        return _aware(self._clock.now() if self._clock else timezone.now())

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV4 | None:
        """Return the exact subject first winner knowable by the cutoff."""
        _selectors(subject_id, subject_version)
        return _single(
            tuple(
                value
                for _, value in self._world(as_of).subjects
                if (value.subject_id, value.subject_version) == (subject_id, subject_version)
                and value.requested_at <= as_of
            )
        )

    def append_subject(
        self, subject: AccountOwnerAssignmentSubjectV4, *, recorded_at: datetime
    ) -> AccountOwnerAssignmentSubjectV4:
        """Append an exact first subject only after current durable parent validation."""
        checked = _subject(subject)
        self._require_append_clock(recorded_at, checked.requested_at)
        self._lock_world(checked.policy.policy_id)
        world = self._world(recorded_at)
        receipt_pk = self._subject_parent(checked, checked.requested_at)
        anchors = tuple(
            value
            for row, value in world.subjects
            if (value.subject_id, value.subject_version)
            == (checked.subject_id, checked.subject_version)
            or value.identity_hash == checked.identity_hash
            or value.content_hash == checked.content_hash
            or _fk(row, "receipt_id") == receipt_pk
        )
        if anchors:
            if anchors == (checked,):
                return checked
            raise AccountOwnerAssignmentConflict("subject first winner differs")
        self._insert(AccountOwnerAssignmentSubjectV4Model, _subject_values(checked, receipt_pk))
        restored = self.get_subject_winner(
            subject_id=checked.subject_id,
            subject_version=checked.subject_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentCorruption("subject append restore differs")
        return restored

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the immutable evidence first winner after full-world verification."""
        _selectors(evidence_id, evidence_version)
        return _single(
            tuple(
                record
                for _, record in self._world(as_of).evidence
                if (record.evidence.evidence_id, record.evidence.evidence_version)
                == (evidence_id, evidence_version)
                and record.evidence.recorded_at <= as_of
            )
        )

    def get_exact_by_hash(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return only the selected historical evidence seal."""
        _digest(expected_content_hash)
        record = self.get_winner(
            evidence_id=evidence_id, evidence_version=evidence_version, as_of=as_of
        )
        return (
            record
            if record is not None and record.evidence.content_hash == expected_content_hash
            else None
        )

    def get_account_head(
        self, *, account_namespace: str, account_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the account root even if expired; never make an expired slot reusable."""
        _selectors(account_namespace, account_id)
        return _single(
            tuple(
                record
                for _, record in self._world(as_of).evidence
                if record.evidence.recorded_at <= as_of
                and (
                    record.evidence.subject.binding.account_namespace_claim,
                    record.evidence.subject.binding.account_id_claim,
                )
                == (account_namespace, account_id)
            )
        )

    def get_underlying_head(
        self,
        *,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4 | None:
        """Return the immutable underlying root including its expired state."""
        _selectors(underlying_unified_account_namespace)
        if type(underlying_unified_account_id) is not int or underlying_unified_account_id <= 0:
            raise ValueError("underlying account id must be a positive integer")
        return _single(
            tuple(
                record
                for _, record in self._world(as_of).evidence
                if record.evidence.recorded_at <= as_of
                and (
                    record.evidence.subject.binding.underlying_unified_account_namespace_claim,
                    record.evidence.subject.binding.underlying_unified_account_id_claim,
                )
                == (underlying_unified_account_namespace, underlying_unified_account_id)
            )
        )

    def append_root(
        self,
        record: PersistedAccountOwnerAssignmentEvidenceV4,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV4:
        """Append a first root with an exact subject and authenticated authority envelope."""
        checked = _record(record)
        evidence = checked.evidence
        self._require_append_clock(recorded_at, evidence.recorded_at)
        if expected_account_head_hash is not None or expected_underlying_head_hash is not None:
            raise AccountOwnerAssignmentConflict("assignment evidence v4 is root-only")
        self._lock_world(evidence.policy.policy_id)
        world = self._world(recorded_at)
        subjects = tuple(row for row, value in world.subjects if value == evidence.subject)
        if len(subjects) != 1:
            raise AccountOwnerAssignmentConflict("evidence requires its exact registered subject")
        anchors = tuple(
            value
            for row, value in world.evidence
            if (value.evidence.evidence_id, value.evidence.evidence_version)
            == (evidence.evidence_id, evidence.evidence_version)
            or _fk(row, "subject_id") == subjects[0].pk
            or value.evidence.account_claim_hash == evidence.account_claim_hash
            or value.evidence.underlying_claim_hash == evidence.underlying_claim_hash
        )
        if anchors:
            if anchors == (checked,):
                return checked
            raise AccountOwnerAssignmentConflict("assignment mapping root is occupied")
        self._subject_parent(evidence.subject, evidence.recorded_at)
        actor_pk = self._authority_parent(checked)
        self._insert(
            AccountOwnerAssignmentEvidenceV4Model,
            _evidence_values(checked, subjects[0].pk, actor_pk),
        )
        restored = self.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentCorruption("evidence append restore differs")
        return restored

    def _postgresql(self) -> None:
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "assignment database alias unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentUnavailable("assignment evidence v4 requires PostgreSQL")

    def _require_append_clock(self, recorded_at: datetime, expected: datetime) -> None:
        self._postgresql()
        if self._uow is None:
            raise AccountOwnerAssignmentConflict("assignment append requires private UOW")
        if _aware(recorded_at) != expected or recorded_at > self.now():
            raise AccountOwnerAssignmentCorruption("assignment persistence clock differs")

    def _lock_world(self, policy_id: str) -> None:
        lock_account_owner_assignment_evidence_v4_sources(using=self._using, policy_id=policy_id)

    def _world(self, as_of: datetime) -> _World:
        self._postgresql()
        _aware(as_of)
        try:
            subjects = []
            for row in AccountOwnerAssignmentSubjectV4Model._default_manager.using(
                self._using
            ).order_by("pk"):
                value = _subject_payload(row.canonical_payload)
                receipt_pk = _fk(row, "receipt_id")
                _verify(row, _subject_values(value, receipt_pk))
                if self._subject_parent(value, value.requested_at) != receipt_pk:
                    raise AccountOwnerAssignmentCorruption("subject receipt FK differs")
                subjects.append((row, value))
            by_pk = {row.pk: value for row, value in subjects}
            evidence = []
            account_claims: set[str] = set()
            underlying_claims: set[str] = set()
            account_scopes: set[tuple[str, str]] = set()
            underlying_scopes: set[tuple[str, int]] = set()
            for evidence_row in AccountOwnerAssignmentEvidenceV4Model._default_manager.using(
                self._using
            ).order_by("pk"):
                record = _record_payload(evidence_row.canonical_payload)
                subject_pk, actor_pk = _fk(evidence_row, "subject_id"), _fk(
                    evidence_row, "actor_source_id"
                )
                _verify(evidence_row, _evidence_values(record, subject_pk, actor_pk))
                approved = record.evidence
                if (
                    by_pk.get(subject_pk) != approved.subject
                    or self._authority_parent(record) != actor_pk
                ):
                    raise AccountOwnerAssignmentCorruption("evidence durable parent substitution")
                self._subject_parent(approved.subject, approved.recorded_at)
                binding = approved.subject.binding
                account_scope = (binding.account_namespace_claim, binding.account_id_claim)
                underlying_scope = (
                    binding.underlying_unified_account_namespace_claim,
                    binding.underlying_unified_account_id_claim,
                )
                if (
                    approved.account_claim_hash in account_claims
                    or approved.underlying_claim_hash in underlying_claims
                    or account_scope in account_scopes
                    or underlying_scope in underlying_scopes
                ):
                    raise AccountOwnerAssignmentCorruption("assignment mapping has multiple roots")
                account_claims.add(approved.account_claim_hash)
                underlying_claims.add(approved.underlying_claim_hash)
                account_scopes.add(account_scope)
                underlying_scopes.add(underlying_scope)
                evidence.append((evidence_row, record))
            return _World(tuple(subjects), tuple(evidence))
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable("assignment ledger read unavailable") from error

    def _subject_parent(self, subject: AccountOwnerAssignmentSubjectV4, as_of: datetime) -> int:
        receipt = subject.receipt
        stored = self._receipts.get_current_head(receipt_id=receipt.receipt_id, as_of=as_of)
        policy = self._policies.get_exact_current(
            policy_id=subject.policy.policy_id,
            policy_version=subject.policy.policy_version,
            expected_content_hash=subject.policy.content_hash,
            as_of=as_of,
        )
        if (
            stored is None
            or stored.receipt != receipt
            or policy != subject.policy
            or not receipt.is_current_at(as_of)
        ):
            raise AccountOwnerAssignmentCorruption("subject durable receipt or policy unavailable")
        row = (
            AccountOwnerAssignmentProvenanceReceiptV4Model._default_manager.using(self._using)
            .filter(
                receipt_id=receipt.receipt_id,
                receipt_version=receipt.receipt_version,
                content_hash=receipt.content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentCorruption("subject durable receipt FK unavailable")
        return row.pk

    def _authority_parent(self, record: PersistedAccountOwnerAssignmentEvidenceV4) -> int:
        authority, evidence = record.authority, record.evidence
        stored = self._actors.get_exact_by_hash(
            source_id=authority.source_id,
            source_version=authority.source_version,
            expected_content_hash=authority.source_content_hash,
            as_of=evidence.approved_at,
        )
        head = self._actors.get_current_head(
            source_id=authority.source_id, as_of=evidence.recorded_at
        )
        if (
            stored is None
            or head != stored
            or not stored.source.is_temporally_current_at(evidence.recorded_at)
        ):
            raise AccountOwnerAssignmentCorruption("approval durable authority unavailable")
        source = stored.source
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
        if projected != authority:
            raise AccountOwnerAssignmentCorruption("approval authority projection differs")
        row = (
            AccountOwnerAssignmentActorAuthoritySourceV3Model._default_manager.using(self._using)
            .filter(
                source_id=authority.source_id,
                source_version=authority.source_version,
                content_hash=authority.source_content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentCorruption("approval actor FK unavailable")
        return row.pk

    def _insert(self, model: type[Model], values: dict[str, object]) -> None:
        if self._uow is None:
            raise AccountOwnerAssignmentConflict("assignment append requires private UOW")
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_assignment_v4_insert(
                    token=self._uow,
                    using=self._using,
                    model_type=model,
                    values=values,
                ),
            ):
                model._default_manager.using(self._using).create(**values)
        except IntegrityError as error:
            raise AccountOwnerAssignmentConflict("assignment first winner conflict") from error


def lock_account_owner_assignment_evidence_v4_sources(*, using: str, policy_id: str) -> None:
    """Stabilize all sources before Application reads in an existing same-alias transaction.

    The original policy writer key is acquired before deterministic whole-ledger
    table locks. EXCLUSIVE excludes both mutation and competing FOR UPDATE;
    NOWAIT prevents reverse-order lock cycles with legacy writers.
    """
    _selectors(using, policy_id)
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise AccountOwnerAssignmentUnavailable("assignment database alias unavailable") from error
    if (
        connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
    ):
        raise AccountOwnerAssignmentUnavailable(
            "assignment locks require an active PostgreSQL transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise AccountOwnerAssignmentUnavailable("assignment writes require READ COMMITTED")
            cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [policy_id])
            if cursor.fetchone() != (True,):
                raise AccountOwnerAssignmentUnavailable("assignment policy writer is busy")
            tables = sorted(
                connection.ops.quote_name(model._meta.db_table) for model in _LOCK_MODELS
            )
            cursor.execute(f"LOCK TABLE {', '.join(tables)} IN EXCLUSIVE MODE NOWAIT")
    except DatabaseError as error:
        raise AccountOwnerAssignmentUnavailable("assignment source locks unavailable") from error


def _selectors(*values: str) -> None:
    for value in values:
        if (
            type(value) is not str
            or not value
            or value.strip() != value
            or len(value) > 192
            or any(c.isspace() for c in value)
        ):
            raise ValueError("selector must be a canonical token")


def _digest(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("selector must be a lowercase SHA-256 digest")


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountOwnerAssignmentCorruption("assignment clock must be aware")
    return value


def _single(values: tuple[_T, ...]) -> _T | None:
    if len(values) > 1:
        raise AccountOwnerAssignmentCorruption("multiple assignment winners")
    return values[0] if values else None


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _fk(row: Model, name: str) -> int:
    value = row.__dict__.get(name)
    if type(value) is not int or value <= 0:
        raise AccountOwnerAssignmentCorruption("assignment FK is invalid")
    return value


def _subject_payload(payload: object) -> AccountOwnerAssignmentSubjectV4:
    try:
        return decode_account_owner_assignment_subject_v4(payload)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("subject payload is invalid") from error


def _subject(value: AccountOwnerAssignmentSubjectV4) -> AccountOwnerAssignmentSubjectV4:
    try:
        return _subject_payload(encode_account_owner_assignment_subject_v4(value))
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("subject value is invalid") from error


def _record_payload(payload: object) -> PersistedAccountOwnerAssignmentEvidenceV4:
    try:
        return decode_account_owner_assignment_evidence_v4_record(payload)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("evidence payload is invalid") from error


def _record(
    value: PersistedAccountOwnerAssignmentEvidenceV4,
) -> PersistedAccountOwnerAssignmentEvidenceV4:
    try:
        return _record_payload(encode_account_owner_assignment_evidence_v4_record(value))
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("evidence value is invalid") from error


def _base_values(
    value: AccountOwnerAssignmentSubjectV4 | PersistedAccountOwnerAssignmentEvidenceV4,
    payload: dict[str, object],
    parents: dict[str, int],
) -> dict[str, object]:
    domain = value if isinstance(value, AccountOwnerAssignmentSubjectV4) else value.evidence
    return {
        "owner": domain.owner,
        "artifact_type": domain.artifact_type,
        "schema": domain.schema,
        "permission": domain.permission,
        "status": domain.status,
        "valid_until": domain.valid_until,
        "identity_hash": domain.identity_hash,
        "content_hash": domain.content_hash,
        "canonical_payload": payload,
        "record_seal": _hash(payload),
        "ledger_seal": _hash(
            {"domain": domain.artifact_type + "/ledger", "record": payload, "parents": parents}
        ),
    }


def _subject_values(value: AccountOwnerAssignmentSubjectV4, receipt_pk: int) -> dict[str, object]:
    parents = {"receipt_id": receipt_pk}
    return {
        **_base_values(value, encode_account_owner_assignment_subject_v4(value), parents),
        **parents,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "requested_at": value.requested_at,
        "persisted_at": value.requested_at,
    }


def _evidence_values(
    record: PersistedAccountOwnerAssignmentEvidenceV4, subject_pk: int, actor_pk: int
) -> dict[str, object]:
    value = record.evidence
    binding = value.subject.binding
    parents = {"subject_id": subject_pk, "actor_source_id": actor_pk}
    return {
        **_base_values(record, encode_account_owner_assignment_evidence_v4_record(record), parents),
        **parents,
        "evidence_id": value.evidence_id,
        "evidence_version": value.evidence_version,
        "assignment_state": value.assignment_state,
        "account_namespace": binding.account_namespace_claim,
        "account_id": binding.account_id_claim,
        "underlying_unified_account_namespace": binding.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id": binding.underlying_unified_account_id_claim,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "approved_at": value.approved_at,
        "recorded_at": value.recorded_at,
        "approval_valid_until": value.approval_valid_until,
        "persisted_at": value.recorded_at,
    }


def _verify(row: Model, values: dict[str, object]) -> None:
    for name, value in values.items():
        if getattr(row, name) != value:
            raise AccountOwnerAssignmentCorruption("assignment ledger field mismatch: " + name)


_LOCK_MODELS: tuple[type[Model], ...] = (
    raw_models.AccountAuthenticationContextSourceV3AnchorModel,
    raw_models.AccountAuthenticationContextSourceV3Model,
    raw_models.AccountUserAuthoritySourceV3AnchorModel,
    raw_models.AccountUserAuthoritySourceV3Model,
    raw_models.AccountRbacAuthoritySourceV3AnchorModel,
    raw_models.AccountRbacAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
    SingleOwnerAuthorityPolicyV1Model,
    AccountOwnerAssignmentProvenanceReceiptV4Model,
    AccountOwnerAssignmentSubjectV4Model,
    AccountOwnerAssignmentEvidenceV4Model,
)
