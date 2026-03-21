# Generated manually for AgomTradePro

from django.db import migrations, models


def migrate_existing_data(apps, schema_editor):
    """
    迁移现有数据：根据指标代码设置合理的 period_type
    """
    MacroIndicator = apps.get_model('macro', 'MacroIndicator')

    # 月度指标默认为 M
    monthly_indicators = ['CN_PMI', 'CN_CPI', 'CN_PPI', 'M2', 'INDUSTRIAL_VALUE_ADDED', 'RETAIL_SALES']

    for indicator in MacroIndicator.objects.all():
        if indicator.code in monthly_indicators:
            indicator.period_type = 'M'
        elif indicator.code.startswith('SHIBOR'):
            indicator.period_type = 'D'
        elif indicator.code.startswith('GDP'):
            indicator.period_type = 'Q'
        else:
            # 默认为日度数据
            indicator.period_type = 'D'
        indicator.save(update_fields=['period_type'])


class Migration(migrations.Migration):

    dependencies = [
        ("macro", "0002_rename_macro_in_code_obs_idx_macro_indic_code_108657_idx_and_more"),
    ]

    operations = [
        # 1. 添加 period_type 字段（默认为 'D'）
        migrations.AddField(
            model_name='macroindicator',
            name='period_type',
            field=models.CharField(
                max_length=1,
                choices=[('D', '日'), ('W', '周'), ('M', '月'), ('Q', '季'), ('Y', '年')],
                default='D',
                help_text='期间类型'
            ),
        ),
        # 2. 迁移现有数据设置合理的 period_type
        migrations.RunPython(migrate_existing_data, migrations.RunPython.noop),
        # 3. 重命名 observed_at 为 reporting_period
        migrations.RenameField(
            model_name='macroindicator',
            old_name='observed_at',
            new_name='reporting_period',
        ),
        # 4. 更新唯一约束
        migrations.AlterUniqueTogether(
            name='macroindicator',
            unique_together={('code', 'reporting_period', 'revision_number')},
        ),
        # 5. 删除旧索引
        migrations.RemoveIndex(
            model_name='macroindicator',
            name='macro_indic_code_108657_idx',
        ),
        # 6. 添加新索引
        migrations.AddIndex(
            model_name='macroindicator',
            index=models.Index(fields=['code', '-reporting_period'], name='macro_code_reporting_idx'),
        ),
        migrations.AddIndex(
            model_name='macroindicator',
            index=models.Index(fields=['period_type'], name='macro_period_type_idx'),
        ),
    ]
