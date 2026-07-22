import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signal", "0008_add_alpha_signal_source")]
    operations = [
        migrations.CreateModel(
            name="ForecastLedgerEntry",
            fields=[
                ("entry_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("published_at", models.DateTimeField(db_index=True)),
                ("direction", models.CharField(max_length=10)),
                ("asset_code", models.CharField(db_index=True, max_length=32)),
                ("horizon_end", models.DateTimeField(db_index=True)),
                ("benchmark_asset", models.CharField(max_length=32)),
                ("probability", models.FloatField()),
                ("invalidation_rule_version", models.CharField(max_length=64)),
                ("decision_snapshot_id", models.CharField(max_length=64)),
                ("pit_manifest_id", models.CharField(max_length=64)),
                ("strategy_version", models.CharField(blank=True, max_length=64)),
                ("model_version", models.CharField(blank=True, max_length=64)),
                ("prompt_version", models.CharField(blank=True, max_length=64)),
                ("source", models.CharField(db_index=True, max_length=64)),
                ("regime", models.CharField(blank=True, db_index=True, max_length=32)),
                ("status", models.CharField(db_index=True, default="open", max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("signal", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="forecast_entry", to="signal.investmentsignalmodel")),
            ],
            options={"db_table": "signal_forecast_ledger_entry", "indexes": [models.Index(fields=["source", "published_at"], name="signal_fore_source_ce8a98_idx")]},
        ),
        migrations.CreateModel(
            name="ForecastEvaluation",
            fields=[
                ("evaluation_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("checked_at", models.DateTimeField(db_index=True)),
                ("data_version_ids", models.JSONField(default=list)),
                ("conditions", models.JSONField(default=list)),
                ("triggered", models.BooleanField(default=False)),
                ("first_triggered_at", models.DateTimeField(blank=True, null=True)),
                ("status_transition", models.CharField(blank=True, max_length=32)),
                ("missing_reason", models.TextField(blank=True)),
                ("idempotency_key", models.CharField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evaluations", to="signal.forecastledgerentry")),
            ],
            options={"db_table": "signal_forecast_evaluation", "ordering": ["checked_at"], "indexes": [models.Index(fields=["entry", "checked_at"], name="signal_fore_entry_i_d72f78_idx")]},
        ),
        migrations.CreateModel(
            name="ForecastOutcome",
            fields=[
                ("entry", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name="outcome", serialize=False, to="signal.forecastledgerentry")),
                ("outcome_type", models.CharField(max_length=24)),
                ("finalized_at", models.DateTimeField()),
                ("asset_return", models.FloatField(blank=True, null=True)),
                ("benchmark_return", models.FloatField(blank=True, null=True)),
                ("excess_return", models.FloatField(blank=True, null=True)),
                ("hit", models.BooleanField(blank=True, null=True)),
                ("brier_score", models.FloatField(blank=True, null=True)),
                ("evidence", models.JSONField(default=dict)),
            ],
            options={"db_table": "signal_forecast_outcome"},
        ),
    ]
