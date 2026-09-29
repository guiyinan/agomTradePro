"""PostgreSQL coverage, proof, and final-fence primitives for Account authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from django.apps import apps as django_apps
from django.db import DatabaseError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model
from django.utils.connection import ConnectionDoesNotExist

from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    _LOCK_MODELS,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)

_EXPECTED_SOURCE_TABLES: frozenset[str] = frozenset(
    {
        "account_actor_authority_source_v3_ledger",
        "account_actor_authority_source_v3_root_lock",
        "account_allocated_physical_row_observation_v3_ledger",
        "account_auth_context_source_v3_anchor",
        "account_auth_context_source_v3_ledger",
        "account_owner_assignment_evidence_v5_ledger",
        "account_owner_assignment_provenance_receipt_v5_ledger",
        "account_owner_assignment_subject_v5_ledger",
        "account_owner_tenant_authority_v3_ledger",
        "account_owner_tenant_authority_v3_revocation_ledger",
        "account_physical_row_observation_v2_ledger",
        "account_rbac_authority_source_v3_anchor",
        "account_rbac_authority_source_v3_ledger",
        "account_single_owner_authority_policy_v1",
        "account_user_authority_source_v3_anchor",
        "account_user_authority_source_v3_ledger",
        "canonical_account_creation_allocation_ledger",
        "canonical_account_creation_binding_ledger",
        "canonical_account_creation_binding_v2_ledger",
        "canonical_account_creation_consumption_claim_ledger",
        "canonical_account_ownership_reobservation_v1_ledger",
        "simulated_account_row_source_v2_ledger",
    }
)
_GENERATION_TABLE = "public.account_authority_generation"
_DML_TRIGGER_NAME = "acct_auth_gen_stmt"
_TRUNCATE_TRIGGER_NAME = "acct_auth_gen_truncate"
_TRIGGER_FUNCTION_NAME = "account_authority_generation_bump"
_DML_TRIGGER_TYPE = 30
_TRUNCATE_TRIGGER_TYPE = 34
_FUNCTION_SEARCH_PATH = "search_path=pg_catalog, public"


class AccountAuthorityGenerationUnavailable(RuntimeError):
    """The generation proof or final fence cannot be trusted."""


class AccountAuthorityGenerationCoverageError(AccountAuthorityGenerationUnavailable):
    """The configured 22-table trigger coverage or singleton row is incomplete."""


class AccountAuthorityGenerationChanged(AccountAuthorityGenerationUnavailable):
    """A source-ledger statement committed after the supplied proof was read."""


@dataclass(frozen=True, slots=True)
class AccountAuthorityGenerationCoverage:
    """Verified source-table coverage and its observed committed generation."""

    source_tables: tuple[str, ...]
    generation: int


@dataclass(frozen=True, slots=True)
class AccountAuthorityGenerationProof:
    """One alias-bound high-water mark for a closed-world authority scan."""

    using: str
    generation: int


def verify_account_authority_generation_coverage(
    *, using: str = "default"
) -> AccountAuthorityGenerationCoverage:
    """Verify the exact runtime source set, ALWAYS triggers, and singleton epoch row."""

    connection = _connection(using)
    source_tables = _runtime_source_tables()
    if connection.vendor != "postgresql":
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation coverage requires PostgreSQL"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.relname, t.tgname, t.tgenabled, t.tgtype,
                       p.proname, p.prosecdef, p.proconfig
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                LEFT JOIN pg_catalog.pg_trigger AS t
                  ON t.tgrelid = c.oid
                 AND NOT t.tgisinternal
                 AND t.tgname::text = ANY(%s::text[])
                LEFT JOIN pg_catalog.pg_proc AS p ON p.oid = t.tgfoid
                WHERE n.nspname = %s
                  AND c.relname::text = ANY(%s::text[])
                  AND c.relkind = 'r'
                ORDER BY c.relname, t.tgname
                """,
                [
                    [_DML_TRIGGER_NAME, _TRUNCATE_TRIGGER_NAME],
                    "public",
                    list(source_tables),
                ],
            )
            rows = cast(list[tuple[object, ...]], cursor.fetchall())
            _validate_trigger_rows(rows, source_tables)
            cursor.execute(
                f"SELECT generation FROM {_GENERATION_TABLE} WHERE singleton = %s",
                [1],
            )
            generation_row = cast(tuple[object, ...] | None, cursor.fetchone())
    except AccountAuthorityGenerationUnavailable:
        raise
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation coverage query failed"
        ) from error
    if generation_row is None:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation singleton row is missing"
        )
    generation = generation_row[0]
    if type(generation) is not int or generation < 0:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation singleton row is invalid"
        )
    return AccountAuthorityGenerationCoverage(source_tables, generation)


def read_account_authority_generation_proof(
    *, using: str = "default"
) -> AccountAuthorityGenerationProof:
    """Read a high-water proof inside the authority scan's RR read-only snapshot."""

    connection = _connection(using)
    _require_transaction_mode(
        connection,
        isolation="repeatable read",
        read_only=True,
    )
    coverage = verify_account_authority_generation_coverage(using=using)
    return AccountAuthorityGenerationProof(using=using, generation=coverage.generation)


def lock_account_authority_generation_fence(
    proof: AccountAuthorityGenerationProof,
    *,
    using: str = "default",
) -> int:
    """Lock the singleton in READ COMMITTED and reject any changed generation."""

    if type(proof) is not AccountAuthorityGenerationProof:
        raise TypeError("proof must be an exact AccountAuthorityGenerationProof")
    if type(using) is not str or not using or using.strip() != using:
        raise ValueError("using must be an exact database alias")
    if proof.using != using:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation proof belongs to another database alias"
        )
    connection = _connection(using)
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation fence requires an active PostgreSQL transaction"
        )
    if connection.get_autocommit():
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation fence requires an active transaction"
        )
    _require_transaction_mode(
        connection,
        isolation="read committed",
        read_only=False,
    )
    verify_account_authority_generation_coverage(using=using)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT generation FROM {_GENERATION_TABLE} WHERE singleton = %s FOR UPDATE",
                [1],
            )
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except AccountAuthorityGenerationUnavailable:
        raise
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation fence query failed"
        ) from error
    if row is None or type(row[0]) is not int or row[0] < 0:
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation singleton row is missing or invalid"
        )
    current_generation = row[0]
    if current_generation != proof.generation:
        raise AccountAuthorityGenerationChanged(
            "account authority source generation changed before final fence"
        )
    return current_generation


def _runtime_source_tables() -> tuple[str, ...]:
    """Resolve the source tables actually composed by Evidence V5, V3, and row V2."""

    try:
        physical_source_model = django_apps.get_model(
            "simulated_trading",
            "SimulatedAccountRowSourceV2Model",
            require_ready=True,
        )
    except LookupError as error:
        raise AccountAuthorityGenerationCoverageError(
            "account authority physical source model is unavailable"
        ) from error
    source_models = cast(
        tuple[type[Model], ...],
        (
            *_LOCK_MODELS,
            OwnerTenantAuthorityV3Model,
            OwnerTenantAuthorityV3RevocationModel,
            physical_source_model,
        ),
    )
    runtime_tables = frozenset(model._meta.db_table for model in source_models)
    if len(runtime_tables) != 22 or runtime_tables != _EXPECTED_SOURCE_TABLES:
        raise AccountAuthorityGenerationCoverageError(
            "account authority runtime source set differs from its 22-table contract"
        )
    return tuple(sorted(runtime_tables))


def _validate_trigger_rows(
    rows: list[tuple[object, ...]],
    source_tables: tuple[str, ...],
) -> None:
    """Fail closed unless each source has both exact enabled trigger definitions."""

    seen_tables: set[str] = set()
    seen_triggers: dict[str, set[str]] = {table: set() for table in source_tables}
    for row in rows:
        if len(row) != 7:
            raise AccountAuthorityGenerationCoverageError(
                "account authority generation catalog row is malformed"
            )
        table_name, trigger_name, enabled, trigger_type, function_name, security_definer, config = (
            row
        )
        if type(table_name) is not str or table_name not in seen_triggers:
            raise AccountAuthorityGenerationCoverageError(
                "account authority generation catalog contains an unexpected source"
            )
        seen_tables.add(table_name)
        if trigger_name is None:
            continue
        if (
            type(trigger_name) is not str
            or type(enabled) is not str
            or type(trigger_type) is not int
            or type(function_name) is not str
            or type(security_definer) is not bool
            or not isinstance(config, list)
            or any(type(value) is not str for value in config)
        ):
            raise AccountAuthorityGenerationCoverageError(
                "account authority generation trigger catalog row is malformed"
            )
        if trigger_name == _DML_TRIGGER_NAME:
            valid_trigger = trigger_type == _DML_TRIGGER_TYPE
        elif trigger_name == _TRUNCATE_TRIGGER_NAME:
            valid_trigger = trigger_type == _TRUNCATE_TRIGGER_TYPE
        else:
            raise AccountAuthorityGenerationCoverageError(
                "account authority source has an unexpected user trigger"
            )
        if (
            not valid_trigger
            or enabled != "A"
            or function_name != _TRIGGER_FUNCTION_NAME
            or not security_definer
            or _FUNCTION_SEARCH_PATH not in config
        ):
            raise AccountAuthorityGenerationCoverageError(
                "account authority generation trigger definition is not trusted"
            )
        if trigger_name in seen_triggers[table_name]:
            raise AccountAuthorityGenerationCoverageError(
                "account authority generation trigger is duplicated"
            )
        seen_triggers[table_name].add(trigger_name)
    if seen_tables != set(source_tables) or any(
        trigger_names != {_DML_TRIGGER_NAME, _TRUNCATE_TRIGGER_NAME}
        for trigger_names in seen_triggers.values()
    ):
        raise AccountAuthorityGenerationCoverageError(
            "account authority generation trigger coverage is incomplete"
        )


def _connection(using: str) -> BaseDatabaseWrapper:
    """Return one validated connection or a fail-closed typed error."""

    if type(using) is not str or not using or using.strip() != using:
        raise ValueError("using must be an exact database alias")
    try:
        return connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation database alias is unavailable"
        ) from error


def _require_transaction_mode(
    connection: BaseDatabaseWrapper,
    *,
    isolation: str,
    read_only: bool,
) -> None:
    """Require one active PostgreSQL transaction with the exact snapshot mode."""

    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation requires an active PostgreSQL transaction"
        )
    if connection.get_autocommit():
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation requires an active transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_isolation'), "
                "current_setting('transaction_read_only')"
            )
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation transaction mode is unavailable"
        ) from error
    expected_read_only = "on" if read_only else "off"
    if row != (isolation, expected_read_only):
        raise AccountAuthorityGenerationUnavailable(
            "account authority generation transaction mode is invalid"
        )


__all__ = [
    "AccountAuthorityGenerationChanged",
    "AccountAuthorityGenerationCoverage",
    "AccountAuthorityGenerationCoverageError",
    "AccountAuthorityGenerationProof",
    "AccountAuthorityGenerationUnavailable",
    "lock_account_authority_generation_fence",
    "read_account_authority_generation_proof",
    "verify_account_authority_generation_coverage",
]
