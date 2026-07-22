from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_runtime", "0002_execution_record_task_optional")]
    operations = [
        migrations.AddField(model_name="agentcontextsnapshotmodel", name="decision_input_snapshot_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="actual_cost", field=models.DecimalField(decimal_places=6, default=0, max_digits=12)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="actual_tokens", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="decision_input_snapshot_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="eval_baseline_id", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="model_version", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="output_schema_version", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="agentexecutionrecordmodel", name="prompt_version_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
    ]

