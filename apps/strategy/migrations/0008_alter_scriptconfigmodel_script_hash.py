from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('strategy', '0007_rename_order_inten_portfol_aeab65_idx_order_inten_portfol_c5915a_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scriptconfigmodel',
            name='script_hash',
            field=models.CharField(
                db_index=True,
                help_text='SHA256哈希，用于检测脚本变更',
                max_length=64,
                verbose_name='脚本哈希',
            ),
        ),
    ]
