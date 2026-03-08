from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0016_systemsettingsmodel_db_backup_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_app_base_url",
            field=models.URLField(
                blank=True,
                help_text="用于生成邮件中的绝对下载链接，如 https://example.com",
                verbose_name="备份下载站点地址",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_mail_from_email",
            field=models.EmailField(
                blank=True,
                help_text="留空则回退到系统默认发件人",
                max_length=254,
                verbose_name="备份邮件发件人",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_host",
            field=models.CharField(blank=True, max_length=255, verbose_name="SMTP 主机"),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_password_encrypted",
            field=models.TextField(blank=True, help_text="系统内部加密存储", verbose_name="SMTP 密码（密文）"),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_port",
            field=models.PositiveIntegerField(default=587, verbose_name="SMTP 端口"),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_use_ssl",
            field=models.BooleanField(default=False, verbose_name="SMTP 使用 SSL"),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_use_tls",
            field=models.BooleanField(default=True, verbose_name="SMTP 使用 TLS"),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_smtp_username",
            field=models.CharField(blank=True, max_length=255, verbose_name="SMTP 用户名"),
        ),
    ]
