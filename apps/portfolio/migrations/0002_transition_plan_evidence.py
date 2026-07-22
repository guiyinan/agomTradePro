from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portfolio", "0001_transfer_transition_plan_state")]

    operations = [
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="approved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="decision_snapshot_id", field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="expires_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="idempotency_key", field=models.CharField(blank=True, max_length=128, null=True, unique=True)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="immutable_payload_hash", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="plan_version", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="portfolio_snapshot_id", field=models.CharField(blank=True, max_length=64)),
        migrations.AddField(model_name="portfoliotransitionplanmodel", name="target_portfolio_id", field=models.CharField(blank=True, max_length=64)),
    ]

