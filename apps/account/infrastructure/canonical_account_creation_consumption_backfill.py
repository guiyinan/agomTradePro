"""Deterministic strict backfill of Binding-v1 unified consumption claims."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from django.db import connections, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.account.application.canonical_account_creation import CanonicalAccountCreationConflict
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationBinding
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)
from apps.account.infrastructure import (
    canonical_account_creation_consumption_models as consumption_models,
)
from apps.account.infrastructure.canonical_account_creation_maintenance_lock import (
    acquire_canonical_account_creation_maintenance_lock,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationBindingModel,
    _activate_canonical_account_creation_knowledge_backfill,
    _activate_canonical_account_creation_uow,
    _compare_and_set_canonical_account_creation_binding_claim,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
    _claims_overlap,
    _consumption_claim_values,
)

_WRITE_BLOCKER = "production_postgresql_maintenance_lock_required"
_AUTHORIZATION_BLOCKER = "production_backfill_authorization_unavailable"


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationConsumptionBackfillReport:
    """Typed outcome for one all-or-nothing legacy Binding-v1 scan."""

    dry_run: bool
    scanned: int
    eligible: int
    created: int
    already_linked: int
    knowledge_updated: int
    legacy_linked: int
    write_enabled: bool
    blocker_codes: tuple[str, ...]


class CanonicalAccountCreationConsumptionBackfillPreflight(Protocol):
    """Verify that expand is applied and contract is not yet applied."""

    def verify(self, *, using: str) -> None: ...


class CanonicalAccountCreationConsumptionBackfillWriteAuthorization(Protocol):
    """Authorize one exact maintenance snapshot after exclusive lock acquisition."""

    def verify(self, *, using: str, knowledge_at: datetime) -> None: ...


class _BackfillWorld(Protocol):
    bindings_v1: tuple[
        tuple[CanonicalAccountCreationBindingModel, CanonicalAccountCreationBinding], ...
    ]
    claims: tuple[tuple[object, CanonicalAccountCreationConsumptionClaim], ...]


class DjangoMigrationConsumptionBackfillPreflight:
    """Read the target alias's authoritative Django migration ledger."""

    def verify(self, *, using: str) -> None:
        """Require the consumption and knowledge-clock expand migrations."""

        connection = connections[using]
        recorder = MigrationRecorder(connection)
        applied = set(recorder.applied_migrations())
        required = {
            ("account", "0047_canonical_account_creation_consumption_expand"),
            (
                "account",
                "0048_canonical_account_creation_consumption_knowledge_clock_expand",
            ),
        }
        if not required.issubset(applied):
            raise CanonicalAccountCreationConflict(
                "consumption backfill requires migrations 0047 and 0048 knowledge expand"
            )


class DjangoCanonicalAccountCreationConsumptionBackfill:
    """Backfill exact v1 claims while preserving every immutable binding byte."""

    def __init__(
        self,
        *,
        using: str = "default",
        preflight: CanonicalAccountCreationConsumptionBackfillPreflight | None = None,
        allow_sqlite_test_degradation: bool = False,
        write_authorization: (
            CanonicalAccountCreationConsumptionBackfillWriteAuthorization | None
        ) = None,
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must name one database alias")
        self._using = using
        self._preflight = preflight or DjangoMigrationConsumptionBackfillPreflight()
        if type(allow_sqlite_test_degradation) is not bool:
            raise TypeError("allow_sqlite_test_degradation must be an exact bool")
        self._allow_sqlite_test_degradation = allow_sqlite_test_degradation
        self._write_authorization = write_authorization

    def run(self, *, dry_run: bool = True) -> CanonicalAccountCreationConsumptionBackfillReport:
        """Validate the whole closed world and optionally link every legacy row."""

        if type(dry_run) is not bool:
            raise TypeError("dry_run must be an exact bool")
        repository = DjangoCanonicalAccountCreationRepository(using=self._using)
        connection = connections[self._using]
        if dry_run:
            with transaction.atomic(using=self._using):
                if connection.vendor == "postgresql":
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._preflight.verify(using=self._using)
                world = repository._closed_consumption_world(
                    lock=False, _allow_missing_knowledge=True
                )
                candidates, linked = self._candidates(world)
                knowledge_missing = sum(row.knowledge_at is None for row, _ in world.claims)
                return CanonicalAccountCreationConsumptionBackfillReport(
                    dry_run=True,
                    scanned=len(world.bindings_v1),
                    eligible=len(candidates) + knowledge_missing,
                    created=0,
                    already_linked=linked,
                    knowledge_updated=0,
                    legacy_linked=0,
                    write_enabled=(
                        self._write_authorization is not None
                        and (
                            connection.vendor == "postgresql" or self._allow_sqlite_test_degradation
                        )
                    ),
                    blocker_codes=(
                        ()
                        if self._write_authorization is not None
                        and (
                            connection.vendor == "postgresql" or self._allow_sqlite_test_degradation
                        )
                        else (
                            (_AUTHORIZATION_BLOCKER,)
                            if self._write_authorization is None
                            else (_WRITE_BLOCKER,)
                        )
                    ),
                )

        if self._write_authorization is None:
            raise CanonicalAccountCreationConflict(_AUTHORIZATION_BLOCKER)
        with transaction.atomic(using=self._using):
            acquire_canonical_account_creation_maintenance_lock(
                using=self._using,
                allow_sqlite_test_degradation=self._allow_sqlite_test_degradation,
            )
            self._preflight.verify(using=self._using)
            knowledge_at = _database_clock(using=self._using)
            self._write_authorization.verify(
                using=self._using,
                knowledge_at=knowledge_at,
            )
            token = object()
            repository._uow = token
            try:
                with ExitStack() as stack:
                    stack.enter_context(_activate_canonical_account_creation_uow(token))
                    stack.enter_context(
                        consumption_models._activate_canonical_account_creation_consumption_uow(
                            token
                        )
                    )
                    stack.enter_context(
                        _activate_canonical_account_creation_knowledge_backfill(token)
                    )
                    stack.enter_context(
                        consumption_models._activate_canonical_account_creation_knowledge_backfill(
                            token
                        )
                    )
                    world = repository._closed_consumption_world(
                        lock=True, _allow_missing_knowledge=True
                    )
                    candidates, linked = self._candidates(world)
                    knowledge_updated = 0
                    for row, claim in world.claims:
                        if row.knowledge_at is not None:
                            continue
                        if row.pk is None:
                            raise CanonicalAccountCreationConflict(
                                "consumption Claim has no database identity"
                            )
                        updated = consumption_models._compare_and_set_canonical_account_creation_claim_knowledge(
                            using=self._using,
                            token=token,
                            claim_pk=row.pk,
                            allocation_pk=_required_fk(row, "allocation_id"),
                            identity_hash=claim.identity_hash,
                            content_hash=claim.content_hash,
                            consumer_identity_hash=claim.consumer.identity_hash,
                            consumer_content_hash=claim.consumer.content_hash,
                            recorded_at=claim.recorded_at,
                            knowledge_at=knowledge_at,
                        )
                        if updated != 1:
                            raise CanonicalAccountCreationConflict(
                                "consumption Claim knowledge compare-and-swap lost"
                            )
                        knowledge_updated += 1

                    created = 0
                    legacy_linked = 0
                    claim_rows = list(world.claims)
                    for binding_row, claim in candidates:
                        exact = [(row, value) for row, value in claim_rows if value == claim]
                        if len(exact) > 1:
                            raise CanonicalAccountCreationConflict(
                                "legacy Binding-v1 exact consumption Claim is ambiguous"
                            )
                        if exact:
                            claim_row = exact[0][0]
                        else:
                            values = _consumption_claim_values(
                                claim,
                                allocation_pk=_required_fk(binding_row, "allocation_id"),
                                knowledge_at=knowledge_at,
                            )
                            claim_row = repository._insert_consumption_claim(values)
                            claim_rows.append((claim_row, claim))
                            created += 1
                        if binding_row.pk is None or claim_row.pk is None:
                            raise CanonicalAccountCreationConflict(
                                "legacy backfill row has no database identity"
                            )
                        linked_rows = _compare_and_set_canonical_account_creation_binding_claim(
                            using=self._using,
                            token=token,
                            binding_pk=binding_row.pk,
                            claim_pk=claim_row.pk,
                            allocation_pk=_required_fk(binding_row, "allocation_id"),
                            consumer_identity_hash=claim.consumer.identity_hash,
                            consumer_content_hash=claim.consumer.content_hash,
                            claim_content_hash=claim.content_hash,
                        )
                        if linked_rows != 1:
                            raise CanonicalAccountCreationConflict(
                                "Binding-v1 knowledge backfill compare-and-swap lost"
                            )
                        legacy_linked += 1
                    repository._closed_consumption_world(lock=True)
            finally:
                repository._uow = None

            return CanonicalAccountCreationConsumptionBackfillReport(
                dry_run=False,
                scanned=len(world.bindings_v1),
                eligible=len(candidates) + knowledge_updated,
                created=created,
                already_linked=linked,
                knowledge_updated=knowledge_updated,
                legacy_linked=legacy_linked,
                write_enabled=True,
                blocker_codes=(),
            )

    @staticmethod
    def _candidates(
        world: object,
    ) -> tuple[
        list[tuple[CanonicalAccountCreationBindingModel, CanonicalAccountCreationConsumptionClaim]],
        int,
    ]:
        """Derive exact legacy claims without treating overlapping anchors as absent."""

        restored = cast(_BackfillWorld, world)
        candidates: list[
            tuple[
                CanonicalAccountCreationBindingModel,
                CanonicalAccountCreationConsumptionClaim,
            ]
        ] = []
        linked = 0
        proposed = [claim for _, claim in restored.claims]
        for row, binding in restored.bindings_v1:
            if _optional_fk(row, "consumption_claim_id") is not None:
                linked += 1
                continue
            claim_id, claim_version = resolve_canonical_account_creation_consumption_claim_identity(
                binding.allocation, consumer_generation="v1"
            )
            claim = CanonicalAccountCreationConsumptionClaim(
                claim_id=claim_id,
                claim_version=claim_version,
                allocation=binding.allocation,
                consumer_generation="v1",
                consumer=binding,
                account_namespace=binding.account_namespace_claim,
                account_id=binding.account_id_claim,
                underlying_unified_account_namespace=(
                    binding.underlying_unified_account_namespace_claim
                ),
                underlying_unified_account_id=(binding.underlying_unified_account_id_claim),
                physical_v2_content_hash=binding.physical_observation.content_hash,
                physical_v3_root_content_hash=None,
                recorded_at=binding.recorded_at,
            )
            overlaps = [existing for existing in proposed if _claims_overlap(existing, claim)]
            if overlaps and not any(existing == claim for existing in overlaps):
                raise CanonicalAccountCreationConflict(
                    "legacy Binding-v1 consumption anchor is already occupied"
                )
            proposed.append(claim)
            candidates.append((row, claim))
        return candidates, linked


def _database_clock(*, using: str) -> datetime:
    connection = connections[using]
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
        if row is None or type(row[0]) is not datetime:
            raise CanonicalAccountCreationConflict("database knowledge clock is unavailable")
        value = row[0]
    else:
        value = timezone.now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalAccountCreationConflict("database knowledge clock must be aware")
    return value


def _optional_fk(row: object, name: str) -> int | None:
    value = getattr(row, name, None)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationConflict(f"backfill {name} is invalid")
    return value


def _required_fk(row: object, name: str) -> int:
    value = _optional_fk(row, name)
    if value is None:
        raise CanonicalAccountCreationConflict(f"backfill {name} is missing")
    return value


__all__ = [
    "CanonicalAccountCreationConsumptionBackfillPreflight",
    "CanonicalAccountCreationConsumptionBackfillReport",
    "CanonicalAccountCreationConsumptionBackfillWriteAuthorization",
    "DjangoMigrationConsumptionBackfillPreflight",
    "DjangoCanonicalAccountCreationConsumptionBackfill",
]
