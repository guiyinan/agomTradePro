from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("strategy", "0009_strategy_param_promotion_decision")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="OrderIntentModel")],
        )
    ]
