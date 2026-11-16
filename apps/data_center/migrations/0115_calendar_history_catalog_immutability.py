"""Protect versioned calendar catalog content after formal publication."""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.dc_guard_calendar_contract_content()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.dc_guard_calendar_policy_content()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
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
$function$;

CREATE TRIGGER dc_calendar_contract_content_immutable_trg
BEFORE UPDATE OR DELETE ON public.data_center_dataset_contract
FOR EACH ROW EXECUTE FUNCTION public.dc_guard_calendar_contract_content();

CREATE TRIGGER dc_calendar_policy_content_immutable_trg
BEFORE UPDATE OR DELETE ON public.data_center_dataset_publication_policy
FOR EACH ROW EXECUTE FUNCTION public.dc_guard_calendar_policy_content();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS dc_calendar_policy_content_immutable_trg ON public.data_center_dataset_publication_policy;
DROP TRIGGER IF EXISTS dc_calendar_contract_content_immutable_trg ON public.data_center_dataset_contract;
DROP FUNCTION IF EXISTS public.dc_guard_calendar_policy_content();
DROP FUNCTION IF EXISTS public.dc_guard_calendar_contract_content();
"""


def install_calendar_catalog_guard(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Install PostgreSQL guards without changing catalog rows or other datasets."""

    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL, params=None)


def remove_calendar_catalog_guard(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove these guards; the historical reader falls back to strict clocks."""

    del apps
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [("data_center", "0114_financial_native_decimal_storage")]
    operations = [
        migrations.RunPython(install_calendar_catalog_guard, remove_calendar_catalog_guard)
    ]
