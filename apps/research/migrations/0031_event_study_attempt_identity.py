"""Keep frozen-spec final use exclusive and bound family attempts append-only."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def restore_binding_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore the 0030 binding triggers after SQLite remakes the table in either direction."""
    if schema_editor.connection.vendor == "sqlite":
        for action in ("UPDATE", "DELETE"):
            schema_editor.execute(
                f"CREATE TRIGGER IF NOT EXISTS research_event_study_binding_immutable_{action.lower()} "
                f"BEFORE {action} ON research_event_study_binding "
                "BEGIN SELECT RAISE(ABORT, 'Event-study evidence is immutable'); END"
            )


def install_attempt_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Prevent deleting or moving an attempt out of the committed family count."""
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute("""
            CREATE FUNCTION research_event_study_protect_attempt() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (SELECT 1 FROM research_event_study_binding WHERE family_id=OLD.family_id) THEN
                    IF TG_OP='DELETE' THEN
                        RAISE EXCEPTION 'Bound event-study attempts are retained' USING ERRCODE='23514';
                    ELSIF NEW.family_id IS DISTINCT FROM OLD.family_id
                       OR NEW.experiment_id IS DISTINCT FROM OLD.experiment_id
                       OR NEW.trial_id IS DISTINCT FROM OLD.trial_id
                       OR NEW.parameter_hash IS DISTINCT FROM OLD.parameter_hash THEN
                        RAISE EXCEPTION 'Bound event-study attempt identity is immutable' USING ERRCODE='23514';
                    END IF;
                END IF;
                IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER research_event_study_attempt_identity
            BEFORE UPDATE OR DELETE ON research_experiment_trial
            FOR EACH ROW EXECUTE FUNCTION research_event_study_protect_attempt();
        """)
    elif vendor == "sqlite":
        restore_binding_guards(apps, schema_editor)
        schema_editor.execute("""
            CREATE TRIGGER research_event_study_attempt_delete BEFORE DELETE ON research_experiment_trial
            WHEN EXISTS (SELECT 1 FROM research_event_study_binding WHERE family_id=OLD.family_id)
            BEGIN SELECT RAISE(ABORT, 'Bound event-study attempts are retained'); END;
        """)
        schema_editor.execute("""
            CREATE TRIGGER research_event_study_attempt_identity BEFORE UPDATE ON research_experiment_trial
            WHEN EXISTS (SELECT 1 FROM research_event_study_binding WHERE family_id=OLD.family_id)
             AND (NEW.family_id IS NOT OLD.family_id OR NEW.experiment_id IS NOT OLD.experiment_id
                  OR NEW.trial_id IS NOT OLD.trial_id OR NEW.parameter_hash IS NOT OLD.parameter_hash)
            BEGIN SELECT RAISE(ABORT, 'Bound event-study attempt identity is immutable'); END;
        """)
    else:
        raise RuntimeError("Event-study OOS controls require PostgreSQL or SQLite")


def remove_attempt_guards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Remove only the additional guards during an explicitly chosen reversal."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "DROP TRIGGER research_event_study_attempt_identity ON research_experiment_trial"
        )
        schema_editor.execute("DROP FUNCTION research_event_study_protect_attempt()")
    elif schema_editor.connection.vendor == "sqlite":
        schema_editor.execute("DROP TRIGGER research_event_study_attempt_delete")
        schema_editor.execute("DROP TRIGGER research_event_study_attempt_identity")


class Migration(migrations.Migration):
    dependencies = [("research", "0030_event_study_final_oos_control")]
    operations = [
        # On reversal this runs after RemoveConstraint has remade the SQLite table.
        migrations.RunPython(migrations.RunPython.noop, restore_binding_guards),
        migrations.AddConstraint(
            model_name="eventstudybindingmodel",
            constraint=models.UniqueConstraint(
                fields=("spec",), name="revent_study_spec_binding_uq"
            ),
        ),
        migrations.RunPython(install_attempt_guards, remove_attempt_guards),
    ]
