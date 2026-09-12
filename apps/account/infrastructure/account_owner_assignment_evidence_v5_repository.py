"""PostgreSQL storage for closed, policy-bound owner-assignment evidence V5."""

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

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Conflict,
    AccountOwnerAssignmentEvidenceV5Corruption,
    AccountOwnerAssignmentEvidenceV5Unavailable,
    PersistedAccountOwnerAssignmentEvidenceV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    AccountOwnerAssignmentSubjectV5Conflict,
    AccountOwnerAssignmentSubjectV5Corruption,
    AccountOwnerAssignmentSubjectV5Unavailable,
    PersistedAccountOwnerAssignmentSubjectV5,
)
from apps.account.domain.account_owner_assignment_subject_v5 import AccountOwnerAssignmentSubjectV5
from apps.account.infrastructure import account_actor_authority_raw_source_models_v3 as raw_models
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_record_codec import (
    decode_account_owner_assignment_evidence_v5_record,
    encode_account_owner_assignment_evidence_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_record_codec import (
    decode_account_owner_assignment_subject_v5_record,
    encode_account_owner_assignment_subject_v5_record,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
    _activate_assignment_v5_uow,
    _claim_assignment_v5_insert,
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
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)
from apps.account.infrastructure.immutable_read_snapshot import reuse_immutable_read
from apps.account.infrastructure.physical_account_row_observation_v2_models import (
    PhysicalAccountRowObservationV2Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)


class AccountOwnerAssignmentEvidenceV5Clock(Protocol):
    """Supply an explicit aware server clock."""

    def now(self) -> datetime:
        """Return the server's current time."""
        ...


@dataclass(frozen=True)
class _World:
    subjects: tuple[
        tuple[AccountOwnerAssignmentSubjectV5Model, AccountOwnerAssignmentSubjectV5], ...
    ]
    evidence: tuple[
        tuple[AccountOwnerAssignmentEvidenceV5Model, PersistedAccountOwnerAssignmentEvidenceV5], ...
    ]


_T = TypeVar("_T")


class DjangoAccountOwnerAssignmentEvidenceV5Repository:
    """Restore all stored evidence and parents before selecting or appending a root."""

    def __init__(
        self, *, using: str = "default", clock: AccountOwnerAssignmentEvidenceV5Clock | None = None
    ) -> None:
        """Bind the complete graph to one database alias and optional test clock."""
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be an exact database alias")
        self._using = using
        self._clock = clock
        self._uow: object | None = None
        self._subjects = DjangoAccountOwnerAssignmentSubjectV5Repository(using=using, clock=clock)
        self._actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(
            using=using, clock=clock
        )

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Allow outer same-alias transactions while rejecting private UOW reentry."""
        self._postgresql()
        if self._uow is not None:
            raise AccountOwnerAssignmentEvidenceV5Conflict("nested assignment v5 UOW")
        token = object()
        self._uow = token
        try:
            with transaction.atomic(using=self._using), _activate_assignment_v5_uow(token):
                yield
        except DatabaseError as error:
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "assignment transaction unavailable"
            ) from error
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Read the aware persistence clock without replacing source observation times."""
        self._postgresql()
        return _aware(self._clock.now() if self._clock else timezone.now())

    def get_subject_winner(
        self, *, subject_id: str, subject_version: str, as_of: datetime
    ) -> AccountOwnerAssignmentSubjectV5 | None:
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

    def get_winner(
        self, *, evidence_id: str, evidence_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
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
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
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
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
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
    ) -> PersistedAccountOwnerAssignmentEvidenceV5 | None:
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
        record: PersistedAccountOwnerAssignmentEvidenceV5,
        *,
        expected_account_head_hash: None,
        expected_underlying_head_hash: None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentEvidenceV5:
        """Append a first root with an exact subject and authenticated authority envelope."""
        checked = _record(record)
        evidence = checked.evidence
        self._require_append_clock(recorded_at, evidence.recorded_at)
        if expected_account_head_hash is not None or expected_underlying_head_hash is not None:
            raise AccountOwnerAssignmentEvidenceV5Conflict("assignment evidence v5 is root-only")
        self._lock_world(evidence.policy.policy_id)
        world = self._world(recorded_at)
        subjects = tuple(row for row, value in world.subjects if value == evidence.subject)
        if len(subjects) != 1:
            raise AccountOwnerAssignmentEvidenceV5Conflict(
                "evidence requires its exact registered subject"
            )
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
            raise AccountOwnerAssignmentEvidenceV5Conflict("assignment mapping root is occupied")
        self._subject_parent(evidence.subject, evidence.recorded_at)
        actor_pk = self._authority_parent(checked)
        self._insert(
            AccountOwnerAssignmentEvidenceV5Model,
            _evidence_values(checked, subjects[0].pk, actor_pk),
        )
        restored = self.get_winner(
            evidence_id=evidence.evidence_id,
            evidence_version=evidence.evidence_version,
            as_of=recorded_at,
        )
        if restored != checked:
            raise AccountOwnerAssignmentEvidenceV5Corruption("evidence append restore differs")
        return restored

    def _postgresql(self) -> None:
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "assignment database alias unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "assignment evidence v5 requires PostgreSQL"
            )

    def _require_append_clock(self, recorded_at: datetime, expected: datetime) -> None:
        self._postgresql()
        if self._uow is None:
            raise AccountOwnerAssignmentEvidenceV5Conflict("assignment append requires private UOW")
        if _aware(recorded_at) != expected or recorded_at > self.now():
            raise AccountOwnerAssignmentEvidenceV5Corruption("assignment persistence clock differs")

    def _lock_world(self, policy_id: str) -> None:
        lock_account_owner_assignment_evidence_v5_sources(using=self._using, policy_id=policy_id)

    @reuse_immutable_read("assignment-evidence-v5-world")
    def _world(self, as_of: datetime) -> _World:
        self._postgresql()
        cutoff = _aware(as_of)
        if cutoff > self.now():
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "future assignment Evidence V5 as_of is forbidden"
            )
        try:
            subjects = []
            for row in (
                AccountOwnerAssignmentSubjectV5Model._default_manager.using(self._using)
                .select_related("receipt", "binding", "reobservation")
                .order_by("pk")
            ):
                subject_record = _subject_record_payload(row.canonical_payload)
                value = subject_record.subject
                receipt_pk = _fk(row, "receipt_id")
                binding_pk = _fk(row, "binding_id")
                reobservation_pk = _fk(row, "reobservation_id")
                _verify(
                    row,
                    _subject_values(
                        subject_record,
                        receipt_pk,
                        binding_pk,
                        reobservation_pk,
                    ),
                )
                if (
                    row.receipt.content_hash != value.receipt.content_hash
                    or row.binding.content_hash != value.binding.content_hash
                    or row.reobservation.content_hash != value.reobservation.content_hash
                    or self._subject_parent(value, value.requested_at) != row.pk
                ):
                    raise AccountOwnerAssignmentEvidenceV5Corruption(
                        "subject durable parent substitution"
                    )
                subjects.append((row, value))
            by_pk = {row.pk: value for row, value in subjects}
            evidence = []
            account_claims: set[str] = set()
            underlying_claims: set[str] = set()
            account_scopes: set[tuple[str, str]] = set()
            underlying_scopes: set[tuple[str, int]] = set()
            for evidence_row in AccountOwnerAssignmentEvidenceV5Model._default_manager.using(
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
                    raise AccountOwnerAssignmentEvidenceV5Corruption(
                        "evidence durable parent substitution"
                    )
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
                    raise AccountOwnerAssignmentEvidenceV5Corruption(
                        "assignment mapping has multiple roots"
                    )
                account_claims.add(approved.account_claim_hash)
                underlying_claims.add(approved.underlying_claim_hash)
                account_scopes.add(account_scope)
                underlying_scopes.add(underlying_scope)
                evidence.append((evidence_row, record))
            return _World(tuple(subjects), tuple(evidence))
        except DatabaseError as error:
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "assignment ledger read unavailable"
            ) from error

    def _subject_parent(self, subject: AccountOwnerAssignmentSubjectV5, as_of: datetime) -> int:
        """Return the exact durable Subject V5 parent after full graph restoration."""

        try:
            stored = self._subjects.get_exact_by_hash(
                subject_id=subject.subject_id,
                subject_version=subject.subject_version,
                expected_content_hash=subject.content_hash,
                as_of=as_of,
            )
        except (
            AccountOwnerAssignmentSubjectV5Conflict,
            AccountOwnerAssignmentSubjectV5Corruption,
            AccountOwnerAssignmentSubjectV5Unavailable,
        ) as error:
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "subject durable graph is unavailable"
            ) from error
        if stored is None or stored.subject != subject or not subject.is_current_at(as_of):
            raise AccountOwnerAssignmentEvidenceV5Corruption("subject durable graph is unavailable")
        row = (
            AccountOwnerAssignmentSubjectV5Model._default_manager.using(self._using)
            .filter(
                subject_id=subject.subject_id,
                subject_version=subject.subject_version,
                identity_hash=subject.identity_hash,
                content_hash=subject.content_hash,
            )
            .first()
        )
        if row is None:
            raise AccountOwnerAssignmentEvidenceV5Corruption("subject durable FK unavailable")
        return row.pk

    def _authority_parent(self, record: PersistedAccountOwnerAssignmentEvidenceV5) -> int:
        authority, evidence = record.authority, record.evidence
        try:
            stored = self._actors.get_exact_by_hash(
                source_id=authority.source_id,
                source_version=authority.source_version,
                expected_content_hash=authority.source_content_hash,
                as_of=evidence.approved_at,
            )
            head = self._actors.get_current_head(
                source_id=authority.source_id, as_of=evidence.recorded_at
            )
        except (
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
        ) as error:
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "approval durable authority is unavailable"
            ) from error
        if (
            stored is None
            or head != stored
            or not stored.source.is_temporally_current_at(evidence.recorded_at)
        ):
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "approval durable authority unavailable"
            )
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
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "approval authority projection differs"
            )
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
            raise AccountOwnerAssignmentEvidenceV5Corruption("approval actor FK unavailable")
        return row.pk

    def _insert(self, model: type[Model], values: dict[str, object]) -> None:
        if self._uow is None:
            raise AccountOwnerAssignmentEvidenceV5Conflict("assignment append requires private UOW")
        try:
            with (
                transaction.atomic(using=self._using),
                _claim_assignment_v5_insert(
                    token=self._uow,
                    using=self._using,
                    model_type=model,
                    values=values,
                ),
            ):
                model._default_manager.using(self._using).create(**values)
        except IntegrityError as error:
            raise AccountOwnerAssignmentEvidenceV5Conflict(
                "assignment first winner conflict"
            ) from error


def lock_account_owner_assignment_evidence_v5_sources(*, using: str, policy_id: str) -> None:
    """Stabilize all sources before Application reads in an existing same-alias transaction.

    The original policy writer key is acquired before deterministic whole-ledger
    table locks. EXCLUSIVE excludes both mutation and competing FOR UPDATE;
    NOWAIT prevents reverse-order lock cycles with legacy writers.
    """
    _selectors(using, policy_id)
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "assignment database alias unavailable"
        ) from error
    if (
        connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
    ):
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "assignment locks require an active PostgreSQL transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise AccountOwnerAssignmentEvidenceV5Unavailable(
                    "assignment writes require READ COMMITTED"
                )
            cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [policy_id])
            if cursor.fetchone() != (True,):
                raise AccountOwnerAssignmentEvidenceV5Unavailable(
                    "assignment policy writer is busy"
                )
            tables = sorted(
                connection.ops.quote_name(model._meta.db_table) for model in _LOCK_MODELS
            )
            cursor.execute(f"LOCK TABLE {', '.join(tables)} IN EXCLUSIVE MODE NOWAIT")
    except DatabaseError as error:
        raise AccountOwnerAssignmentEvidenceV5Unavailable(
            "assignment source locks unavailable"
        ) from error


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
        raise AccountOwnerAssignmentEvidenceV5Corruption("assignment clock must be aware")
    return value


def _single(values: tuple[_T, ...]) -> _T | None:
    if len(values) > 1:
        raise AccountOwnerAssignmentEvidenceV5Corruption("multiple assignment winners")
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
        raise AccountOwnerAssignmentEvidenceV5Corruption("assignment FK is invalid")
    return value


def _subject_record_payload(payload: object) -> PersistedAccountOwnerAssignmentSubjectV5:
    try:
        return decode_account_owner_assignment_subject_v5_record(payload)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption("subject payload is invalid") from error


def _record_payload(payload: object) -> PersistedAccountOwnerAssignmentEvidenceV5:
    try:
        return decode_account_owner_assignment_evidence_v5_record(payload)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption("evidence payload is invalid") from error


def _record(
    value: PersistedAccountOwnerAssignmentEvidenceV5,
) -> PersistedAccountOwnerAssignmentEvidenceV5:
    try:
        return _record_payload(encode_account_owner_assignment_evidence_v5_record(value))
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentEvidenceV5Corruption("evidence value is invalid") from error


def _base_values(
    value: PersistedAccountOwnerAssignmentEvidenceV5,
    payload: dict[str, object],
    parents: dict[str, int],
) -> dict[str, object]:
    domain = value.evidence
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


def _subject_values(
    record: PersistedAccountOwnerAssignmentSubjectV5,
    receipt_pk: int,
    binding_pk: int,
    reobservation_pk: int,
) -> dict[str, object]:
    value = record.subject
    return {
        "owner": value.owner,
        "artifact_type": value.artifact_type,
        "schema": value.schema,
        "permission": value.permission,
        "status": value.status,
        "valid_until": value.valid_until,
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "canonical_payload": encode_account_owner_assignment_subject_v5_record(record),
        "record_seal": record.record_seal,
        "ledger_seal": record.ledger_seal,
        "receipt_id": receipt_pk,
        "binding_id": binding_pk,
        "reobservation_id": reobservation_pk,
        "subject_id": value.subject_id,
        "subject_version": value.subject_version,
        "requested_at": value.requested_at,
        "persisted_at": value.requested_at,
    }


def _evidence_values(
    record: PersistedAccountOwnerAssignmentEvidenceV5, subject_pk: int, actor_pk: int
) -> dict[str, object]:
    value = record.evidence
    binding = value.subject.binding
    parents = {"subject_id": subject_pk, "actor_source_id": actor_pk}
    return {
        **_base_values(record, encode_account_owner_assignment_evidence_v5_record(record), parents),
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
            raise AccountOwnerAssignmentEvidenceV5Corruption(
                "assignment ledger field mismatch: " + name
            )


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
    PhysicalAccountRowObservationV2Model,
    CanonicalAccountOwnershipReobservationV1Model,
    SingleOwnerAuthorityPolicyV1Model,
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
    AccountOwnerAssignmentEvidenceV5Model,
)
