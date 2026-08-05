from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fixed_income", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="fixedincomeresearchresultmodel",
            name="publication_evidence",
            field=models.JSONField(default=list),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="fixedincomeresearchresultmodel",
            name="must_not_use_for_decision",
            field=models.BooleanField(default=True, editable=False),
        ),
        migrations.AddConstraint(
            model_name="fixedincomeresearchresultmodel",
            constraint=models.CheckConstraint(
                condition=models.Q(("must_not_use_for_decision", True)),
                name="fixed_income_result_no_decision",
            ),
        ),
    ]
