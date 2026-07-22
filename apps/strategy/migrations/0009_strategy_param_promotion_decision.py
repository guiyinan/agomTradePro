from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("strategy", "0008_alter_scriptconfigmodel_script_hash")]

    operations = [
        migrations.AddField(
            model_name="strategyparamversionmodel",
            name="promotion_decision_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="启用研究门禁后必须引用已批准的 research PromotionDecision",
                max_length=64,
                null=True,
                verbose_name="研究晋级决策 ID",
            ),
        )
    ]
