from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0028_move_system_settings_to_config_center"),
    ]

    operations = [
        migrations.AddField(
            model_name="useraccesstokenmodel",
            name="access_level",
            field=models.CharField(
                choices=[("read_only", "只读"), ("read_write", "读写")],
                default="read_write",
                help_text="只读 Token 仅允许 GET/HEAD/OPTIONS；读写 Token 仍需通过账号角色鉴权。",
                max_length=20,
                verbose_name="访问级别",
            ),
        ),
    ]
