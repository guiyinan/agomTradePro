from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("sector", "0003_industry_operating_templates"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="industryoperatingtemplateversionmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "ordering": ["template_code", "template_version"],
            },
        ),
        migrations.AlterModelOptions(
            name="industrytemplaterunevidencemodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "ordering": ["run_key", "run_version"],
            },
        ),
    ]
