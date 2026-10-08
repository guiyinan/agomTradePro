from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0093_financial_capacity_slice_ledger"),
    ]

    operations = [
        migrations.AlterField(
            model_name="financialcapacitygovernancerecordmodel",
            name="stage",
            field=models.CharField(
                choices=[
                    ("qualification", "Isolated qualification"),
                    ("capacity_rehearsal", "Isolated full-scope capacity rehearsal"),
                    ("production", "Formal production"),
                    ("scope_discovery", "Isolated financial scope discovery"),
                    ("scope_manifest_review", "Independent financial scope manifest review"),
                ],
                max_length=32,
            ),
        ),
    ]
