"""Persist source-exchange identity separately from the rule market."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def prevent_dropping_source_exchange_bindings(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep V2 source-exchange evidence intact when reversing this migration."""

    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely check source-exchange bindings outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(trade_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    has_source_exchange_binding = trade_model.objects.using(connection.alias).filter(
        ~Q(settlement_plan_binding_version__in=(0, 1)) | Q(settlement_exchange__isnull=False)
    )
    if has_source_exchange_binding.exists():
        raise IrreversibleError(
            "Cannot remove source-exchange binding fields while simulated trades retain them."
        )


class Migration(migrations.Migration):
    """Separate source exchange from the existing Risk/Fee market field."""

    dependencies = [
        ("simulated_trading", "0026_simulated_trade_settlement_plan_binding"),
    ]

    operations = [
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_exchange",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="simulatedtrademodel",
            name="sim_trade_plan_binding_pair_ck",
        ),
        migrations.RemoveConstraint(
            model_name="simulatedtrademodel",
            name="sim_trade_uow_binding_ck",
        ),
        migrations.AddConstraint(
            model_name="simulatedtrademodel",
            constraint=models.CheckConstraint(
                condition=Q(
                    settlement_plan_binding_version=0,
                    settlement_plan_binding_payload__isnull=True,
                    settlement_plan_binding_hash__isnull=True,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=1,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=2,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=False,
                ),
                name="sim_trade_plan_binding_pair_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="simulatedtrademodel",
            constraint=models.CheckConstraint(
                condition=Q(
                    idempotency_key__isnull=True,
                    fee_config_id__isnull=True,
                    fee_schedule_hash__isnull=True,
                    fee_schedule_snapshot__isnull=True,
                    fee_precision_basis__isnull=True,
                    fee_calculation_purpose__isnull=True,
                    fee_rounding_policy__isnull=True,
                    settlement_market_session__isnull=True,
                    settlement_security_id__isnull=True,
                    settlement_market__isnull=True,
                    settlement_exchange__isnull=True,
                    settlement_board__isnull=True,
                    settlement_lag_sessions__isnull=True,
                    settlement_bundle_id__isnull=True,
                    settlement_bundle_version__isnull=True,
                    settlement_bundle_hash__isnull=True,
                    settlement_policy_id__isnull=True,
                    settlement_policy_version__isnull=True,
                    settlement_policy_hash__isnull=True,
                    execution_rule_v2_hash__isnull=True,
                    settlement_calendar_snapshot_id__isnull=True,
                    settlement_calendar_content_hash__isnull=True,
                    settlement_calendar_record_digest__isnull=True,
                    settlement_calendar_publication_id__isnull=True,
                    settlement_calendar_publication_hash__isnull=True,
                    settlement_calendar_policy_hash__isnull=True,
                    settlement_calendar_evidence_hash__isnull=True,
                    settlement_calendar_timezone__isnull=True,
                )
                | Q(
                    idempotency_key__isnull=False,
                    fee_config_id__isnull=False,
                    fee_schedule_hash__isnull=False,
                    fee_schedule_snapshot__isnull=False,
                    fee_precision_basis__isnull=False,
                    fee_calculation_purpose__isnull=False,
                    fee_rounding_policy__isnull=False,
                    settlement_market_session__isnull=False,
                    settlement_security_id__isnull=False,
                    settlement_market__isnull=False,
                    settlement_board__isnull=False,
                    settlement_lag_sessions__isnull=False,
                    settlement_bundle_id__isnull=False,
                    settlement_bundle_version__isnull=False,
                    settlement_bundle_hash__isnull=False,
                    settlement_policy_id__isnull=False,
                    settlement_policy_version__isnull=False,
                    settlement_policy_hash__isnull=False,
                    execution_rule_v2_hash__isnull=False,
                    settlement_calendar_snapshot_id__isnull=False,
                    settlement_calendar_content_hash__isnull=False,
                    settlement_calendar_record_digest__isnull=False,
                    settlement_calendar_publication_id__isnull=False,
                    settlement_calendar_publication_hash__isnull=False,
                    settlement_calendar_policy_hash__isnull=False,
                    settlement_calendar_evidence_hash__isnull=False,
                    settlement_calendar_timezone__isnull=False,
                ),
                name="sim_trade_uow_binding_ck",
            ),
        ),
        # On reverse this guard runs before the column or constraint is removed.
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=prevent_dropping_source_exchange_bindings,
        ),
    ]
