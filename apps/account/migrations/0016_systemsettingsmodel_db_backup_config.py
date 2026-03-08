from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0015_systemsettingsmodel_runtime_market_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_email",
            field=models.EmailField(
                blank=True,
                help_text="启用后按周期发送数据库全量备份下载链接到该邮箱",
                max_length=254,
                verbose_name="数据库备份接收邮箱",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_enabled",
            field=models.BooleanField(
                default=False,
                help_text="开启后系统会按设定周期发送备份下载链接",
                verbose_name="启用数据库备份邮件",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_interval_days",
            field=models.PositiveIntegerField(
                default=7,
                help_text="每隔多少天发送一次数据库备份下载链接",
                verbose_name="备份周期（天）",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_last_sent_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="上次备份邮件发送时间",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_link_ttl_days",
            field=models.PositiveIntegerField(
                default=3,
                help_text="邮件中的备份下载链接有效天数",
                verbose_name="下载链接有效期（天）",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_password_encrypted",
            field=models.TextField(
                blank=True,
                help_text="系统内部加密存储，用于生成加密备份文件",
                verbose_name="备份压缩密码（密文）",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_password_hint",
            field=models.CharField(
                blank=True,
                help_text="可选，用于管理员识别当前使用的备份密码",
                max_length=255,
                verbose_name="备份密码提示",
            ),
        ),
    ]
