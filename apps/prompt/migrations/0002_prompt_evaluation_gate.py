import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("prompt", "0001_initial")]
    operations = [
        migrations.AddField(model_name="promptexecutionlogorm", name="decision_snapshot_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="promptexecutionlogorm", name="eval_baseline_id", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="promptexecutionlogorm", name="output_schema_version", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="promptexecutionlogorm", name="prompt_version_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.CreateModel(
            name="PromptEvalDataset",
            fields=[
                ("dataset_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=128)),
                ("version", models.CharField(max_length=32)),
                ("content_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "prompt_eval_dataset", "constraints": [models.UniqueConstraint(fields=("name", "version"), name="prompt_eval_dataset_version_uniq")]},
        ),
        migrations.CreateModel(
            name="PromptVersion",
            fields=[
                ("version_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("version", models.CharField(max_length=32)),
                ("content", models.TextField()),
                ("system_prompt", models.TextField(blank=True)),
                ("required_variables", models.JSONField(default=list)),
                ("output_schema", models.JSONField(default=dict)),
                ("allowed_tools", models.JSONField(default=list)),
                ("content_hash", models.CharField(max_length=64, unique=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("candidate", "Candidate"), ("evaluated", "Evaluated"), ("active", "Active"), ("retired", "Retired")], db_index=True, default="draft", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="immutable_versions", to="prompt.prompttemplateorm")),
            ],
            options={"db_table": "prompt_version", "constraints": [models.UniqueConstraint(fields=("template", "version"), name="prompt_template_version_uniq")]},
        ),
        migrations.CreateModel(
            name="PromptEvalCase",
            fields=[
                ("case_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("input_variables", models.JSONField(default=dict)),
                ("expected_schema", models.JSONField(default=dict)),
                ("allowed_tools", models.JSONField(default=list)),
                ("assertions", models.JSONField(default=list)),
                ("dataset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cases", to="prompt.promptevaldataset")),
            ],
            options={"db_table": "prompt_eval_case"},
        ),
        migrations.CreateModel(
            name="PromptEvalRun",
            fields=[
                ("run_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("evaluation_type", models.CharField(max_length=16)),
                ("provider", models.CharField(blank=True, max_length=64)),
                ("model", models.CharField(blank=True, max_length=64)),
                ("temperature", models.FloatField(default=0.0)),
                ("status", models.CharField(db_index=True, default="running", max_length=24)),
                ("max_cost", models.DecimalField(decimal_places=6, max_digits=12)),
                ("actual_cost", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("max_tokens", models.PositiveIntegerField()),
                ("actual_tokens", models.PositiveIntegerField(default=0)),
                ("max_cases", models.PositiveIntegerField()),
                ("executed_cases", models.PositiveIntegerField(default=0)),
                ("failure_summary", models.JSONField(default=list)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("dataset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="prompt.promptevaldataset")),
                ("prompt_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="eval_runs", to="prompt.promptversion")),
            ],
            options={"db_table": "prompt_eval_run"},
        ),
        migrations.CreateModel(
            name="PromptEvalAssertion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assertion_type", models.CharField(max_length=32)),
                ("passed", models.BooleanField()),
                ("critical", models.BooleanField(default=True)),
                ("details", models.JSONField(default=dict)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("tokens", models.PositiveIntegerField(default=0)),
                ("cost", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="prompt.promptevalcase")),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assertion_results", to="prompt.promptevalrun")),
            ],
            options={"db_table": "prompt_eval_assertion"},
        ),
        migrations.CreateModel(
            name="PromptPromotionDecision",
            fields=[
                ("decision_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("decision", models.CharField(max_length=16)),
                ("evidence", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("eval_run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="prompt.promptevalrun")),
                ("prompt_version", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="promotion_decision", to="prompt.promptversion")),
            ],
            options={"db_table": "prompt_promotion_decision"},
        ),
    ]
