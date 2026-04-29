from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0008_indicator_unit_rules"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="indicatorunitrulemodel",
            old_name="data_center_indicator_code_02db84_idx",
            new_name="data_center_indicat_8a9792_idx",
        ),
        migrations.RenameIndex(
            model_name="indicatorunitrulemodel",
            old_name="data_center_indicator_code_4fdd70_idx",
            new_name="data_center_indicat_a85428_idx",
        ),
    ]
