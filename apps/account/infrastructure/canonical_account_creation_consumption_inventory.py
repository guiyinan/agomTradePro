"""Read-only, per-database inventory for canonical creation consumption ledgers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from django.db import connections, models, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model
from django.utils.connection import ConnectionDoesNotExist

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
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)

_REQUIRED_MIGRATIONS = (
    "0045_canonical_account_creation_ledger",
    "0046_allocated_physical_account_row_observation_v3_ledger",
    "0047_canonical_account_creation_consumption_expand",
    "0048_canonical_account_creation_consumption_knowledge_clock_expand",
)


class CanonicalAccountCreationConsumptionInventoryUnavailable(RuntimeError):
    """The selected database cannot produce a trustworthy inventory snapshot."""


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationLedgerInventory:
    """Stable count, database identity range, and authoritative clock range."""

    ledger: str
    table: str
    clock_column: str
    row_count: int
    pk_min: int | None
    pk_max: int | None
    clock_min: str | None
    clock_max: str | None

    def canonical_payload(self) -> dict[str, object]:
        """Return the deterministic JSON-ready representation."""

        return {
            "clock_column": self.clock_column,
            "clock_max": self.clock_max,
            "clock_min": self.clock_min,
            "ledger": self.ledger,
            "pk_max": self.pk_max,
            "pk_min": self.pk_min,
            "row_count": self.row_count,
            "table": self.table,
        }


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationConsumptionConsistency:
    """Cross-ledger link and immutable-anchor consistency counters."""

    v1_claim_null_count: int
    v1_claim_non_null_count: int
    claim_v1_count: int
    claim_v2_count: int
    claim_knowledge_null_count: int
    claim_without_binding_count: int
    binding_without_claim_count: int
    allocation_link_mismatch_count: int
    cross_generation_allocation_anchor_count: int
    cross_generation_account_anchor_count: int
    cross_generation_underlying_anchor_count: int
    cross_generation_physical_v2_anchor_count: int
    inconsistency_count: int

    @property
    def is_consistent(self) -> bool:
        """Return whether every checked link and anchor invariant holds."""

        return self.inconsistency_count == 0

    def canonical_payload(self) -> dict[str, object]:
        """Return the deterministic JSON-ready representation."""

        return {
            "allocation_link_mismatch_count": self.allocation_link_mismatch_count,
            "binding_without_claim_count": self.binding_without_claim_count,
            "claim_v1_count": self.claim_v1_count,
            "claim_v2_count": self.claim_v2_count,
            "claim_knowledge_null_count": self.claim_knowledge_null_count,
            "claim_without_binding_count": self.claim_without_binding_count,
            "cross_generation_account_anchor_count": (self.cross_generation_account_anchor_count),
            "cross_generation_allocation_anchor_count": (
                self.cross_generation_allocation_anchor_count
            ),
            "cross_generation_physical_v2_anchor_count": (
                self.cross_generation_physical_v2_anchor_count
            ),
            "cross_generation_underlying_anchor_count": (
                self.cross_generation_underlying_anchor_count
            ),
            "inconsistency_count": self.inconsistency_count,
            "is_consistent": self.is_consistent,
            "v1_claim_non_null_count": self.v1_claim_non_null_count,
            "v1_claim_null_count": self.v1_claim_null_count,
        }


@dataclass(frozen=True, slots=True)
class CanonicalAccountCreationConsumptionInventoryReport:
    """One stable, closed-world inventory snapshot for exactly one DB alias."""

    database_alias: str
    backend: str
    snapshot_isolation: str
    applied_migrations: tuple[str, ...]
    ledgers: tuple[CanonicalAccountCreationLedgerInventory, ...]
    consistency: CanonicalAccountCreationConsumptionConsistency
    closed_world_validated: bool
    snapshot_hash: str

    def canonical_payload(self, *, include_snapshot_hash: bool = True) -> dict[str, object]:
        """Return the stable JSON payload, optionally excluding its own digest."""

        payload: dict[str, object] = {
            "applied_migrations": list(self.applied_migrations),
            "backend": self.backend,
            "closed_world_validated": self.closed_world_validated,
            "consistency": self.consistency.canonical_payload(),
            "database_alias": self.database_alias,
            "ledgers": [ledger.canonical_payload() for ledger in self.ledgers],
            "snapshot_isolation": self.snapshot_isolation,
        }
        if include_snapshot_hash:
            payload["snapshot_hash"] = self.snapshot_hash
        return payload

    def to_json(self) -> str:
        """Serialize the complete report with stable key and whitespace semantics."""

        return _stable_json(self.canonical_payload())


class CanonicalAccountCreationConsumptionInventoryService:
    """Inspect one explicit database alias without mutating application data."""

    def __init__(self, *, using: str) -> None:
        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must name one database alias")
        self._using = using

    def inspect(self) -> CanonicalAccountCreationConsumptionInventoryReport:
        """Return one validated snapshot or fail closed before publishing counts."""

        try:
            connection = connections[self._using]
        except (KeyError, ConnectionDoesNotExist) as error:
            raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                f"unknown database alias: {self._using}"
            ) from error

        try:
            with transaction.atomic(using=self._using):
                isolation = self._configure_snapshot(connection)
                migrations = self._validate_schema(connection)
                world = DjangoCanonicalAccountCreationRepository(
                    using=self._using
                )._closed_consumption_world(
                    lock=False,
                    _allow_missing_knowledge=True,
                )
                ledgers = self._ledger_inventories(connection)
                consistency = _consistency(world)
                draft = CanonicalAccountCreationConsumptionInventoryReport(
                    database_alias=self._using,
                    backend=connection.vendor,
                    snapshot_isolation=isolation,
                    applied_migrations=migrations,
                    ledgers=ledgers,
                    consistency=consistency,
                    closed_world_validated=True,
                    snapshot_hash="",
                )
                digest = hashlib.sha256(
                    _stable_json(draft.canonical_payload(include_snapshot_hash=False)).encode(
                        "utf-8"
                    )
                ).hexdigest()
                return CanonicalAccountCreationConsumptionInventoryReport(
                    database_alias=draft.database_alias,
                    backend=draft.backend,
                    snapshot_isolation=draft.snapshot_isolation,
                    applied_migrations=draft.applied_migrations,
                    ledgers=draft.ledgers,
                    consistency=draft.consistency,
                    closed_world_validated=draft.closed_world_validated,
                    snapshot_hash=digest,
                )
        except CanonicalAccountCreationConsumptionInventoryUnavailable:
            raise
        except Exception as error:
            raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                f"inventory failed closed for database alias {self._using}"
            ) from error

    def _configure_snapshot(self, connection: BaseDatabaseWrapper) -> str:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return "repeatable_read_read_only"
        if connection.vendor == "sqlite":
            return "sqlite_atomic_read_snapshot_read_only_unenforced"
        return f"{connection.vendor}_atomic_read_only_unenforced"

    def _validate_schema(self, connection: BaseDatabaseWrapper) -> tuple[str, ...]:
        with connection.cursor() as cursor:
            tables = frozenset(connection.introspection.table_names(cursor))
            if "django_migrations" not in tables:
                raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                    "django_migrations is missing"
                )
            cursor.execute(
                "SELECT name FROM django_migrations WHERE app = %s ORDER BY name",
                ["account"],
            )
            migration_names = tuple(cast(str, row[0]) for row in cursor.fetchall())

            missing_migrations = tuple(
                name for name in _REQUIRED_MIGRATIONS if name not in migration_names
            )
            if missing_migrations:
                raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                    "required account migrations are missing: " + ", ".join(missing_migrations)
                )

            for model_type in _LEDGER_MODELS:
                table = model_type._meta.db_table
                if table not in tables:
                    raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                        f"required ledger table is missing: {table}"
                    )
                description = connection.introspection.get_table_description(cursor, table)
                descriptions = {column.name: column for column in description}
                actual_columns = frozenset(descriptions)
                expected_columns = frozenset(
                    field.column for field in model_type._meta.local_concrete_fields
                )
                missing_columns = tuple(sorted(expected_columns - actual_columns))
                if missing_columns:
                    raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                        f"required columns are missing from {table}: " + ", ".join(missing_columns)
                    )
                nullability_drift = tuple(
                    sorted(
                        field.column
                        for field in model_type._meta.local_concrete_fields
                        if descriptions[field.column].null_ok is not field.null
                    )
                )
                if nullability_drift:
                    raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                        f"column nullability drift in {table}: " + ", ".join(nullability_drift)
                    )
                constraints = connection.introspection.get_constraints(cursor, table)
                for expected in model_type._meta.constraints:
                    actual = constraints.get(expected.name)
                    if actual is None:
                        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                            f"required constraint is missing from {table}: {expected.name}"
                        )
                    if isinstance(expected, models.UniqueConstraint) and not actual.get(
                        "unique", False
                    ):
                        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                            f"required unique constraint drift in {table}: {expected.name}"
                        )
                    if isinstance(expected, models.CheckConstraint) and not actual.get(
                        "check", False
                    ):
                        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                            f"required check constraint drift in {table}: {expected.name}"
                        )
                for field in model_type._meta.local_concrete_fields:
                    remote = field.remote_field
                    if remote is None:
                        continue
                    remote_model = remote.model
                    remote_pk = remote_model._meta.pk
                    expected_foreign_key = (remote_model._meta.db_table, remote_pk.column)
                    if not any(
                        detail.get("columns") == [field.column]
                        and detail.get("foreign_key") == expected_foreign_key
                        for detail in constraints.values()
                    ):
                        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                            f"required foreign key drift in {table}: {field.column}"
                        )
        return tuple(
            name
            for name in migration_names
            if name in _REQUIRED_MIGRATIONS or name.startswith(("0049_", "0050_"))
        )

    def _ledger_inventories(
        self, connection: BaseDatabaseWrapper
    ) -> tuple[CanonicalAccountCreationLedgerInventory, ...]:
        return tuple(
            _ledger_inventory(
                connection,
                ledger=ledger,
                model_type=model_type,
                clock_column=clock_column,
            )
            for ledger, model_type, clock_column in _LEDGER_SPECS
        )


def inventory_canonical_account_creation_consumption(
    *, using: str
) -> CanonicalAccountCreationConsumptionInventoryReport:
    """Inventory exactly one explicit database alias."""

    return CanonicalAccountCreationConsumptionInventoryService(using=using).inspect()


_LEDGER_SPECS: tuple[tuple[str, type[Model], str], ...] = (
    ("allocation", CanonicalAccountCreationAllocationModel, "allocated_at"),
    ("binding_v1", CanonicalAccountCreationBindingModel, "recorded_at"),
    ("consumption_claim", CanonicalAccountCreationConsumptionClaimModel, "recorded_at"),
    ("binding_v2", CanonicalAccountCreationBindingV2Model, "recorded_at"),
    ("physical_v3_root", AllocatedPhysicalAccountRowObservationV3Model, "recorded_at"),
)
_LEDGER_MODELS = tuple(spec[1] for spec in _LEDGER_SPECS)


def _ledger_inventory(
    connection: BaseDatabaseWrapper,
    *,
    ledger: str,
    model_type: type[Model],
    clock_column: str,
) -> CanonicalAccountCreationLedgerInventory:
    table = model_type._meta.db_table
    pk_column = model_type._meta.pk.column
    quote = connection.ops.quote_name
    sql = (
        f"SELECT COUNT(*), MIN({quote(pk_column)}), MAX({quote(pk_column)}), "
        f"MIN({quote(clock_column)}), MAX({quote(clock_column)}) "
        f"FROM {quote(table)}"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    if row is None:
        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
            f"ledger aggregate returned no row: {table}"
        )
    return CanonicalAccountCreationLedgerInventory(
        ledger=ledger,
        table=table,
        clock_column=clock_column,
        row_count=int(row[0]),
        pk_min=None if row[1] is None else int(row[1]),
        pk_max=None if row[2] is None else int(row[2]),
        clock_min=_clock_text(row[3]),
        clock_max=_clock_text(row[4]),
    )


class _RestoredWorld(Protocol):
    allocations: tuple[tuple[Model, object], ...]
    bindings_v1: tuple[tuple[Model, object], ...]
    bindings_v2: tuple[tuple[Model, object], ...]
    claims: tuple[tuple[Model, object], ...]


def _consistency(world: object) -> CanonicalAccountCreationConsumptionConsistency:
    restored = cast(_RestoredWorld, world)
    allocations = restored.allocations
    bindings_v1 = restored.bindings_v1
    bindings_v2 = restored.bindings_v2
    claims = restored.claims

    v1_rows = tuple(cast(CanonicalAccountCreationBindingModel, row) for row, _ in bindings_v1)
    v2_rows = tuple(cast(CanonicalAccountCreationBindingV2Model, row) for row, _ in bindings_v2)
    claim_rows = tuple(
        cast(CanonicalAccountCreationConsumptionClaimModel, row) for row, _ in claims
    )
    allocation_pks = frozenset(row.pk for row, _ in allocations)
    v1_claim_pks = frozenset(
        claim_pk
        for row in v1_rows
        if (claim_pk := _optional_positive_fk(row, "consumption_claim_id")) is not None
    )
    v2_claim_pks = frozenset(_required_positive_fk(row, "consumption_claim_id") for row in v2_rows)
    claim_pks = frozenset(row.pk for row in claim_rows)

    claim_without_binding = len(claim_pks - v1_claim_pks - v2_claim_pks)
    binding_without_claim = sum(
        _optional_positive_fk(row, "consumption_claim_id") is None for row in v1_rows
    )
    binding_without_claim += len((v1_claim_pks | v2_claim_pks) - claim_pks)
    allocation_link_mismatch = sum(
        _required_positive_fk(row, "allocation_id") not in allocation_pks for row in claim_rows
    )
    allocation_link_mismatch += sum(
        _required_positive_fk(row, "allocation_id") not in allocation_pks for row in v1_rows
    )
    allocation_link_mismatch += sum(
        _required_positive_fk(row, "allocation_id") not in allocation_pks for row in v2_rows
    )

    cross_allocation = len(
        {row.allocation_content_hash for row in v1_rows}
        & {row.allocation_content_hash for row in v2_rows}
    )
    cross_account = len(
        {(row.account_namespace_claim, row.account_id_claim) for row in v1_rows}
        & {(row.account_namespace_claim, row.account_id_claim) for row in v2_rows}
    )
    cross_underlying = len(
        {
            (
                row.underlying_unified_account_namespace_claim,
                row.underlying_unified_account_id_claim,
            )
            for row in v1_rows
        }
        & {
            (
                row.underlying_unified_account_namespace_claim,
                row.underlying_unified_account_id_claim,
            )
            for row in v2_rows
        }
    )
    cross_physical = len(
        {row.physical_content_hash for row in v1_rows}
        & {row.physical_observation_content_hash for row in v2_rows}
    )
    claim_v1 = sum(row.consumer_generation == "v1" for row in claim_rows)
    claim_v2 = sum(row.consumer_generation == "v2" for row in claim_rows)
    claim_knowledge_null = sum(row.knowledge_at is None for row in claim_rows)
    v1_null = sum(_optional_positive_fk(row, "consumption_claim_id") is None for row in v1_rows)
    v1_non_null = len(v1_rows) - v1_null
    branch_count_mismatch = abs(claim_v1 - v1_non_null) + abs(claim_v2 - len(v2_rows))
    inconsistency_count = (
        claim_without_binding
        + binding_without_claim
        + allocation_link_mismatch
        + cross_allocation
        + cross_account
        + cross_underlying
        + cross_physical
        + branch_count_mismatch
        + claim_knowledge_null
    )
    return CanonicalAccountCreationConsumptionConsistency(
        v1_claim_null_count=v1_null,
        v1_claim_non_null_count=v1_non_null,
        claim_v1_count=claim_v1,
        claim_v2_count=claim_v2,
        claim_knowledge_null_count=claim_knowledge_null,
        claim_without_binding_count=claim_without_binding,
        binding_without_claim_count=binding_without_claim,
        allocation_link_mismatch_count=allocation_link_mismatch,
        cross_generation_allocation_anchor_count=cross_allocation,
        cross_generation_account_anchor_count=cross_account,
        cross_generation_underlying_anchor_count=cross_underlying,
        cross_generation_physical_v2_anchor_count=cross_physical,
        inconsistency_count=inconsistency_count,
    )


def _clock_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalAccountCreationConsumptionInventoryUnavailable(
                "ledger aggregate returned a naive clock"
            )
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    raise CanonicalAccountCreationConsumptionInventoryUnavailable(
        "ledger aggregate returned an invalid clock type"
    )


def _optional_positive_fk(row: object, field_name: str) -> int | None:
    value = getattr(row, field_name, None)
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
            f"ledger returned an invalid {field_name}"
        )
    return value


def _required_positive_fk(row: object, field_name: str) -> int:
    value = _optional_positive_fk(row, field_name)
    if value is None:
        raise CanonicalAccountCreationConsumptionInventoryUnavailable(
            f"ledger returned a missing {field_name}"
        )
    return value


def _stable_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "CanonicalAccountCreationConsumptionConsistency",
    "CanonicalAccountCreationConsumptionInventoryReport",
    "CanonicalAccountCreationConsumptionInventoryService",
    "CanonicalAccountCreationConsumptionInventoryUnavailable",
    "CanonicalAccountCreationLedgerInventory",
    "inventory_canonical_account_creation_consumption",
]
