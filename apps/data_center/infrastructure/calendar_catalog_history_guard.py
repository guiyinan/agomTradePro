"""Verify the narrow PostgreSQL catalog-history immutability guard."""

from __future__ import annotations

import re
from datetime import datetime

from django.db import DatabaseError
from django.db.backends.base.base import BaseDatabaseWrapper

from core.exceptions import DataFetchError

_MIGRATION_NAME = "0115_calendar_history_catalog_immutability"
_ENABLED_TRIGGER_STATES = frozenset({"O", "A"})
_BEFORE_ROW_UPDATE_DELETE = 27
_CONTRACT_TRIGGER = "dc_calendar_contract_content_immutable_trg"
_POLICY_TRIGGER = "dc_calendar_policy_content_immutable_trg"
_CONTRACT_FUNCTION = "dc_guard_calendar_contract_content"
_POLICY_FUNCTION = "dc_guard_calendar_policy_content"

_CONTRACT_SOURCE = """
BEGIN
    IF OLD.dataset_key = 'data_center.exchange_calendar_snapshot'
       AND EXISTS (
            SELECT 1
            FROM public.data_center_canonical_publication AS p
            JOIN public.data_center_dataset_publication_policy AS pol
              ON pol.dataset_key = p.dataset_key
             AND pol.policy_version = p.policy_version
            WHERE p.dataset_key = OLD.dataset_key
              AND p.publication_key LIKE 'exchange-calendar:%'
              AND p.state IN ('published', 'superseded')
              AND pol.contract_version = OLD.contract_version
              AND pol.schema_version = OLD.schema_version
       ) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'published calendar contract is immutable';
        END IF;
        IF (to_jsonb(NEW) - 'active' - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'active' - 'updated_at') THEN
            RAISE EXCEPTION 'published calendar contract content is immutable';
        END IF;
        IF NEW.active IS NOT DISTINCT FROM OLD.active THEN
            IF NEW.updated_at IS DISTINCT FROM OLD.updated_at THEN
                RAISE EXCEPTION 'published calendar contract updated_at requires active transition';
            END IF;
        ELSIF NEW.updated_at <= OLD.updated_at OR NEW.updated_at > statement_timestamp() THEN
            RAISE EXCEPTION 'published calendar contract active clock is invalid';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
"""

_POLICY_SOURCE = """
BEGIN
    IF OLD.dataset_key = 'data_center.exchange_calendar_snapshot'
       AND EXISTS (
            SELECT 1
            FROM public.data_center_canonical_publication AS p
            WHERE p.dataset_key = OLD.dataset_key
              AND p.publication_key LIKE 'exchange-calendar:%'
              AND p.policy_version = OLD.policy_version
              AND p.state IN ('published', 'superseded')
       ) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'published calendar policy is immutable';
        END IF;
        IF (to_jsonb(NEW) - 'active' - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'active' - 'updated_at') THEN
            RAISE EXCEPTION 'published calendar policy content is immutable';
        END IF;
        IF NEW.active IS NOT DISTINCT FROM OLD.active THEN
            IF NEW.updated_at IS DISTINCT FROM OLD.updated_at THEN
                RAISE EXCEPTION 'published calendar policy updated_at requires active transition';
            END IF;
        ELSIF NEW.updated_at <= OLD.updated_at OR NEW.updated_at > statement_timestamp() THEN
            RAISE EXCEPTION 'published calendar policy active clock is invalid';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
"""


def calendar_catalog_history_guard_applied_at(
    connection: BaseDatabaseWrapper,
    *,
    server_now: datetime,
) -> datetime | None:
    """Return the trusted guard start only when migration and exact triggers match.

    ``None`` selects the legacy strict-``updated_at`` read path. No historic
    row may use the guarded relaxation unless its publication creation and
    publication clocks are strictly after this returned migration timestamp.
    """

    if connection.vendor != "postgresql":
        return None
    _require_utc(server_now)
    migration_rows: list[tuple[object, ...]]
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, applied FROM django_migrations WHERE app = %s AND name = %s",
                ["data_center", _MIGRATION_NAME],
            )
            migration_rows = list(cursor.fetchall())
            migration_rows = [
                row
                for row in migration_rows
                if len(row) == 2 and type(row[0]) is str and row[0] == _MIGRATION_NAME
            ]
            if len(migration_rows) != 1:
                return None
            applied = migration_rows[0][1]
            if type(applied) is not datetime:
                return None
            applied_offset = applied.utcoffset()
            if (
                applied.tzinfo is None
                or applied_offset is None
                or applied_offset.total_seconds() != 0
            ):
                return None
            if applied >= server_now:
                return None
            expected = (
                (
                    "data_center_dataset_contract",
                    _CONTRACT_TRIGGER,
                    _CONTRACT_FUNCTION,
                    _CONTRACT_SOURCE,
                ),
                (
                    "data_center_dataset_publication_policy",
                    _POLICY_TRIGGER,
                    _POLICY_FUNCTION,
                    _POLICY_SOURCE,
                ),
            )
            for table_name, trigger_name, function_name, function_source in expected:
                cursor.execute(
                    """
                    SELECT
                        t.tgenabled,
                        t.tgtype,
                        t.tgqual,
                        t.tgattr::text,
                        octet_length(t.tgargs),
                        p.proname,
                        pns.nspname,
                        lang.lanname,
                        p.prosecdef,
                        p.prosrc,
                        relns.nspname,
                        c.relname,
                        c.relkind,
                        t.tgconstraint
                    FROM pg_trigger AS t
                    JOIN pg_class AS c ON c.oid = t.tgrelid
                    JOIN pg_namespace AS relns ON relns.oid = c.relnamespace
                    JOIN pg_proc AS p ON p.oid = t.tgfoid
                    JOIN pg_namespace AS pns ON pns.oid = p.pronamespace
                    JOIN pg_language AS lang ON lang.oid = p.prolang
                    WHERE relns.nspname = 'public'
                      AND c.relname = %s
                      AND t.tgname = %s
                      AND t.tgqual IS NULL
                      AND t.tgattr::text = ''
                      AND octet_length(t.tgargs) = 0
                      AND t.tgconstraint = 0
                      AND pns.nspname = 'public'
                      AND c.relkind = 'r'
                      AND NOT t.tgisinternal
                    """,
                    [table_name, trigger_name],
                )
                triggers = cursor.fetchall()
                if len(triggers) != 1:
                    return None
                (
                    enabled,
                    trigger_type,
                    trigger_qual,
                    trigger_columns,
                    trigger_arg_bytes,
                    actual_function,
                    function_schema,
                    function_language,
                    security_definer,
                    actual_source,
                    relation_schema,
                    relation_name,
                    relation_kind,
                    constraint_id,
                ) = triggers[0]
                if (
                    enabled not in _ENABLED_TRIGGER_STATES
                    or trigger_type != _BEFORE_ROW_UPDATE_DELETE
                    or trigger_qual is not None
                    or trigger_columns != ""
                    or trigger_arg_bytes != 0
                    or constraint_id != 0
                    or actual_function != function_name
                    or function_schema != "public"
                    or function_language != "plpgsql"
                    or security_definer is not False
                    or relation_schema != "public"
                    or relation_name != table_name
                    or relation_kind != "r"
                    or type(actual_source) is not str
                    or _normalize_sql(actual_source) != _normalize_sql(function_source)
                ):
                    return None
            return applied
    except DatabaseError as error:
        raise DataFetchError(
            "Calendar catalog history guard state is unavailable",
            code="CALENDAR_HISTORY_GUARD_UNAVAILABLE",
        ) from error


def _normalize_sql(value: str) -> str:
    """Normalize only insignificant whitespace for exact function-body checks."""

    return re.sub(r"\s+", " ", value).strip()


def _require_utc(value: datetime) -> None:
    """Require an exact aware zero-offset database clock."""

    offset = value.utcoffset() if type(value) is datetime and value.tzinfo is not None else None
    if offset is None or offset.total_seconds() != 0:
        raise DataFetchError(
            "Calendar catalog guard cutoff must be UTC",
            code="CALENDAR_HISTORY_GUARD_UNAVAILABLE",
        )


__all__ = ["calendar_catalog_history_guard_applied_at"]
