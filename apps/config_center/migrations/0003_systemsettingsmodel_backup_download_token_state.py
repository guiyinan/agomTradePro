from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0002_alphauniverseconfigmodel_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_download_consumed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="当前备份下载令牌消费时间",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_download_token_digest",
            field=models.CharField(
                blank=True,
                default="",
                help_text="只存储不可逆指纹，用于撤销旧链接和单次消费校验",
                max_length=64,
                verbose_name="当前备份下载令牌指纹",
            ),
        ),
        migrations.AddField(
            model_name="systemsettingsmodel",
            name="backup_download_token_expires_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="当前备份下载令牌到期时间",
            ),
        ),
    ]
