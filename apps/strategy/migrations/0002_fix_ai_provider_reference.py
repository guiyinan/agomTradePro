# Migration to fix AI provider model reference
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ai_provider', '0001_initial'),
        ('strategy', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aistrategyconfigmodel',
            name='ai_provider',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ai_strategies',
                to='ai_provider.aiproviderconfig',
                verbose_name='AI服务商'
            ),
        ),
    ]
