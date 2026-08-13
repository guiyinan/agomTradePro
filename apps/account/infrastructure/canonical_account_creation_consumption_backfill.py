"""Deterministic strict backfill of Binding-v1 unified consumption claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.db import connections
from django.db.migrations.recorder import MigrationRecorder

from apps.account.application.canonical_account_creation import CanonicalAccountCreationConflict
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
    _claims_overlap,
)

_WRITE_BLOCKER = "consumption_claim_backfill_provenance_clock_not_integrated"


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationConsumptionBackfillReport:
    """Typed outcome for one all-or-nothing legacy Binding-v1 scan."""

    dry_run: bool
    scanned: int
    eligible: int
    created: int
    already_linked: int
    write_enabled: bool
    blocker_codes: tuple[str, ...]


class CanonicalAccountCreationConsumptionBackfillPreflight(Protocol):
    """Verify that expand is applied and contract is not yet applied."""

    def verify(self, *, using: str) -> None: ...


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
    ) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must name one database alias")
        self._using = using
        self._preflight = preflight or DjangoMigrationConsumptionBackfillPreflight()

    def run(self, *, dry_run: bool = True) -> CanonicalAccountCreationConsumptionBackfillReport:
        """Validate the whole closed world and optionally link every legacy row."""

        if type(dry_run) is not bool:
            raise TypeError("dry_run must be an exact bool")
        if not dry_run:
            raise CanonicalAccountCreationConflict(_WRITE_BLOCKER)
        repository = DjangoCanonicalAccountCreationRepository(using=self._using)
        with repository.atomic():
            connection = connections[self._using]
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self._preflight.verify(using=self._using)
            world = repository._closed_consumption_world(lock=False)
            candidates: list[
                tuple[
                    CanonicalAccountCreationBindingModel,
                    CanonicalAccountCreationConsumptionClaim,
                ]
            ] = []
            linked = 0
            proposed = [claim for _, claim in world.claims]
            for row, binding in world.bindings_v1:
                if row.consumption_claim_id is not None:
                    linked += 1
                    continue
                claim_id, claim_version = (
                    resolve_canonical_account_creation_consumption_claim_identity(
                        binding.allocation, consumer_generation="v1"
                    )
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
                if any(_claims_overlap(existing, claim) for existing in proposed):
                    raise CanonicalAccountCreationConflict(
                        "legacy Binding-v1 consumption anchor is already occupied"
                    )
                proposed.append(claim)
                candidates.append((row, claim))

            return CanonicalAccountCreationConsumptionBackfillReport(
                dry_run=dry_run,
                scanned=len(world.bindings_v1),
                eligible=len(candidates),
                created=0,
                already_linked=linked,
                write_enabled=False,
                blocker_codes=(_WRITE_BLOCKER,),
            )


__all__ = [
    "CanonicalAccountCreationConsumptionBackfillPreflight",
    "CanonicalAccountCreationConsumptionBackfillReport",
    "DjangoMigrationConsumptionBackfillPreflight",
    "DjangoCanonicalAccountCreationConsumptionBackfill",
]
