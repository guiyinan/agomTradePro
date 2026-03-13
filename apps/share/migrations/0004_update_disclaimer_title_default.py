from django.db import migrations, models


def migrate_default_title(apps, schema_editor):
    ShareDisclaimerConfigModel = apps.get_model("share", "ShareDisclaimerConfigModel")
    ShareDisclaimerConfigModel.objects.filter(modal_title="风险提示").update(modal_title="重要声明")


class Migration(migrations.Migration):

    dependencies = [
        ("share", "0003_sharedisclaimerconfigmodel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sharedisclaimerconfigmodel",
            name="modal_title",
            field=models.CharField(default="重要声明", max_length=120, verbose_name="提示标题"),
        ),
        migrations.RunPython(migrate_default_title, migrations.RunPython.noop),
    ]
