from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("share", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharelinkmodel",
            name="theme",
            field=models.CharField(
                choices=[
                    ("bloomberg", "彭博终端风格"),
                    ("monopoly", "大富翁游戏风格"),
                ],
                default="bloomberg",
                help_text="公开分享页的展示风格",
                max_length=20,
                verbose_name="页面风格",
            ),
        ),
    ]
