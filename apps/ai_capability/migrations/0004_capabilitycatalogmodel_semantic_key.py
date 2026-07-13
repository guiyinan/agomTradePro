from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_capability", "0003_seed_market_temperature_capability"),
    ]

    operations = [
        migrations.AddField(
            model_name="capabilitycatalogmodel",
            name="semantic_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Optional semantic key for API/MCP capability de-duplication",
                max_length=255,
            ),
        ),
    ]
