import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="ResearchExperiment",
            fields=[
                ("experiment_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("question", models.TextField()),
                ("hypothesis", models.TextField()),
                ("status", models.CharField(db_index=True, default="draft", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "research_experiment"},
        ),
        migrations.CreateModel(
            name="MultipleTestFamily",
            fields=[
                ("family_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("planned_trial_count", models.PositiveIntegerField()),
                ("fdr_threshold", models.FloatField(default=0.05)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("experiment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="families", to="research.researchexperiment")),
            ],
            options={"db_table": "research_multiple_test_family"},
        ),
        migrations.CreateModel(
            name="ExperimentTrial",
            fields=[
                ("trial_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("status", models.CharField(db_index=True, default="draft", max_length=32)),
                ("pit_manifest_id", models.CharField(db_index=True, max_length=64)),
                ("backtest_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("backtest_trust_status", models.CharField(default="exploratory", max_length=24)),
                ("code_commit", models.CharField(max_length=64)),
                ("dependency_lock_hash", models.CharField(max_length=64)),
                ("engine_version", models.CharField(max_length=64)),
                ("parameters", models.JSONField(default=dict)),
                ("parameter_hash", models.CharField(max_length=64)),
                ("random_seed", models.BigIntegerField()),
                ("benchmark_spec", models.JSONField(default=dict)),
                ("cost_spec", models.JSONField(default=dict)),
                ("slippage_spec", models.JSONField(default=dict)),
                ("universe_spec", models.JSONField(default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("experiment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trials", to="research.researchexperiment")),
                ("family", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="trials", to="research.multipletestfamily")),
            ],
            options={"db_table": "research_experiment_trial", "indexes": [models.Index(fields=["family", "status"], name="research_ex_family__5d4ad9_idx")]},
        ),
        migrations.CreateModel(
            name="DatasetSplitSpec",
            fields=[
                ("trial", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="split_spec", serialize=False, to="research.experimenttrial")),
                ("training_window", models.JSONField(default=dict)),
                ("validation_window", models.JSONField(default=dict)),
                ("out_of_sample_window", models.JSONField(default=dict)),
                ("walk_forward_windows", models.JSONField(default=list)),
                ("embargo_days", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "research_dataset_split_spec"},
        ),
        migrations.CreateModel(
            name="MetricObservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("metric_name", models.CharField(max_length=64)),
                ("value", models.FloatField()),
                ("sample_count", models.PositiveIntegerField()),
                ("confidence_interval_low", models.FloatField(blank=True, null=True)),
                ("confidence_interval_high", models.FloatField(blank=True, null=True)),
                ("p_value", models.FloatField(blank=True, null=True)),
                ("q_value", models.FloatField(blank=True, null=True)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("trial", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metrics", to="research.experimenttrial")),
            ],
            options={"db_table": "research_metric_observation", "constraints": [models.UniqueConstraint(fields=("trial", "metric_name"), name="research_trial_metric_uniq")]},
        ),
        migrations.CreateModel(
            name="PromotionDecision",
            fields=[
                ("decision_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("decision", models.CharField(max_length=16)),
                ("evidence", models.JSONField(default=dict)),
                ("decided_at", models.DateTimeField(auto_now_add=True)),
                ("trial", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="promotion_decision", to="research.experimenttrial")),
            ],
            options={"db_table": "research_promotion_decision"},
        ),
    ]
