"""Raw SQL contracts for the M1 revision database guards."""

from __future__ import annotations

import importlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.utils import timezone

from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)

_migration = importlib.import_module(
    "apps.risk_center.migrations.0012_m1_rebalance_risk_policy_immutable"
)


class _SchemaEditorRollbackSentinel(Exception):
    """Roll back one schema-editor probe without weakening production guards."""


def _create_actor() -> int:
    """Create a real actor row for the revision's protected foreign key."""

    user = get_user_model().objects.create_user(
        username=f"m1-db-immutability-{uuid4().hex}",
        password="unused",
    )
    return cast(int, user.pk)


def _insert_revision_with_raw_sql(
    *, actor_id: int, overrides: dict[str, object] | None = None
) -> str:
    """Insert one valid revision directly to bypass every ORM write guard."""

    now = timezone.now()
    values: dict[str, object] = {
        # UUIDField 在 SQLite 以 32 位无连字符 hex 存储；raw SQL 必须使用同一形态，
        # 否则 ORM 按规范化 hex 查询时无法命中带连字符的行。
        "risk_policy_version": uuid4().hex,
        "account_id": 987654321,
        "actor_id": actor_id,
        "effective_from": now + timedelta(minutes=5),
        "effective_until": now + timedelta(days=1),
        "known_at": now,
        "reason": "Owner approved this explicit M1 risk version.",
        "max_single_position_state": "applicable",
        "max_single_position_pct": Decimal("19.000"),
        "max_single_position_reason": None,
        "max_total_position_state": "applicable",
        "max_total_position_pct": Decimal("90.000"),
        "max_total_position_reason": None,
        "max_stop_loss_state": "applicable",
        "max_stop_loss_pct": Decimal("7.000"),
        "max_stop_loss_reason": None,
        "source_snapshot_schema_version": "m1-risk-source-v1",
        "source_snapshot": json.dumps({"account_id": 987654321}),
        "risk_falsification_schema_version": "m1-risk-falsification-v1",
        "risk_falsification_rules": json.dumps({"status": "not_evaluated"}),
    }
    if overrides is not None:
        values.update(overrides)

    quote = connection.ops.quote_name
    table = quote(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
    columns = ", ".join(quote(column) for column in values)
    placeholders = ", ".join(
        (
            "%s::jsonb"
            if connection.vendor == "postgresql"
            and column
            in {
                "source_snapshot",
                "risk_falsification_rules",
            }
            else "%s"
        )
        for column in values
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
    return str(values["risk_policy_version"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_case",
    (
        "zero_account",
        "unknown_state",
        "missing_applicable_limit",
        "limit_above_100",
        "empty_not_applicable_reason",
        "space_only_not_applicable_reason",
        "empty_owner_reason",
        "space_only_owner_reason",
        "invalid_window",
    ),
)
def test_database_rejects_raw_invalid_revision_shapes(invalid_case: str) -> None:
    """Check constraints reject invalid values even when ORM validation is bypassed."""

    actor_id = _create_actor()
    now = timezone.now()
    invalid_values: dict[str, dict[str, object]] = {
        "zero_account": {"account_id": 0},
        "unknown_state": {"max_single_position_state": "not_a_state"},
        "missing_applicable_limit": {"max_single_position_pct": None},
        "limit_above_100": {"max_single_position_pct": Decimal("100.001")},
        "empty_not_applicable_reason": {
            "max_single_position_state": "not_applicable",
            "max_single_position_pct": None,
            "max_single_position_reason": "",
        },
        "space_only_not_applicable_reason": {
            "max_single_position_state": "not_applicable",
            "max_single_position_pct": None,
            "max_single_position_reason": "   ",
        },
        "empty_owner_reason": {"reason": ""},
        "space_only_owner_reason": {"reason": "   "},
        "invalid_window": {
            "effective_from": now,
            "effective_until": now,
        },
    }

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _insert_revision_with_raw_sql(
                actor_id=actor_id,
                overrides=invalid_values[invalid_case],
            )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dimension",
    ("max_single_position", "max_total_position", "max_stop_loss"),
)
def test_database_rejects_missing_not_applicable_reason_for_each_dimension(
    dimension: str,
) -> None:
    """Nullable conditions cannot use SQL NULL to pass a check as UNKNOWN."""

    overrides = {
        f"{dimension}_state": "not_applicable",
        f"{dimension}_pct": None,
        f"{dimension}_reason": None,
    }
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _insert_revision_with_raw_sql(
                actor_id=_create_actor(),
                overrides=overrides,
            )


@pytest.mark.django_db
def test_raw_sql_update_and_delete_cannot_rewrite_or_erase_revision() -> None:
    """Database triggers reject direct DML and leave the original row intact."""

    version = _insert_revision_with_raw_sql(actor_id=_create_actor())
    table = connection.ops.quote_name(M1RebalanceRiskPolicyRevisionModel._meta.db_table)

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET reason = %s WHERE risk_policy_version = %s",
                    ["Raw SQL changed the immutable history.", version],
                )
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {table} WHERE risk_policy_version = %s",
                    [version],
                )

    row = M1RebalanceRiskPolicyRevisionModel.objects.get(pk=version)
    assert row.reason == "Owner approved this explicit M1 risk version."


@pytest.mark.django_db
def test_raw_sql_cannot_delete_protected_actor_or_require_an_account_foreign_key() -> None:
    """The actor remains protected while account identity stays an explicit scalar."""

    actor_id = _create_actor()
    version = _insert_revision_with_raw_sql(actor_id=actor_id)
    user_table = connection.ops.quote_name(get_user_model()._meta.db_table)
    user_pk_column = connection.ops.quote_name(get_user_model()._meta.pk.column)

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {user_table} WHERE {user_pk_column} = %s",
                    [actor_id],
                )
            connection.check_constraints(
                table_names=[M1RebalanceRiskPolicyRevisionModel._meta.db_table]
            )

    row = M1RebalanceRiskPolicyRevisionModel.objects.get(pk=version)
    assert row.actor_id == actor_id
    assert row.account_id == 987654321
    assert M1RebalanceRiskPolicyRevisionModel._meta.get_field("account_id").remote_field is None


@pytest.mark.django_db
def test_postgres_truncate_rejects_nonempty_revision_history() -> None:
    """The PostgreSQL statement trigger protects TRUNCATE as well as row DML."""

    if connection.vendor != "postgresql":
        pytest.skip("TRUNCATE is a PostgreSQL-specific guard")

    version = _insert_revision_with_raw_sql(actor_id=_create_actor())
    table = connection.ops.quote_name(M1RebalanceRiskPolicyRevisionModel._meta.db_table)

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"TRUNCATE TABLE {table} CASCADE")

    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(pk=version).exists()


@pytest.mark.django_db
def test_postgres_truncate_allows_an_empty_revision_table() -> None:
    """An empty table has no evidence to erase, so Django flush remains safe."""

    if connection.vendor != "postgresql":
        pytest.skip("TRUNCATE is a PostgreSQL-specific guard")

    assert not M1RebalanceRiskPolicyRevisionModel.objects.exists()
    table = connection.ops.quote_name(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table} CASCADE")

    assert not M1RebalanceRiskPolicyRevisionModel.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_refuses_rows_before_removing_any_guard() -> None:
    """A nonempty table blocks reversal while its database triggers remain active."""

    with pytest.raises(_SchemaEditorRollbackSentinel):
        with connection.schema_editor() as schema_editor:
            version = _insert_revision_with_raw_sql(actor_id=_create_actor())
            with pytest.raises(IrreversibleError, match="audit history"):
                _migration.remove_revision_immutability(django_apps, schema_editor)

            table = connection.ops.quote_name(M1RebalanceRiskPolicyRevisionModel._meta.db_table)
            with pytest.raises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"UPDATE {table} SET reason = %s WHERE risk_policy_version = %s",
                            ["A failed reverse removed a guard.", version],
                        )
            row = M1RebalanceRiskPolicyRevisionModel.objects.get(pk=version)
            assert row.reason == "Owner approved this explicit M1 risk version."
            raise _SchemaEditorRollbackSentinel


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_removes_guards_only_when_table_is_empty() -> None:
    """The empty-table branch drops only its triggers inside a rollback-only probe."""

    with pytest.raises(_SchemaEditorRollbackSentinel):
        with connection.schema_editor() as schema_editor:
            assert not M1RebalanceRiskPolicyRevisionModel.objects.exists()
            _migration.remove_revision_immutability(django_apps, schema_editor)

            table_name = M1RebalanceRiskPolicyRevisionModel._meta.db_table
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type = %s AND tbl_name = %s",
                        ["trigger", table_name],
                    )
                    assert cursor.fetchall() == []
            else:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT tgname
                          FROM pg_catalog.pg_trigger
                         WHERE tgrelid = %s::regclass
                           AND NOT tgisinternal
                           AND tgname IN (%s, %s)
                        """,
                        [
                            table_name,
                            "risk_m1_revision_immutable_dml",
                            "risk_m1_revision_immutable_truncate",
                        ],
                    )
                    assert cursor.fetchall() == []
            raise _SchemaEditorRollbackSentinel
