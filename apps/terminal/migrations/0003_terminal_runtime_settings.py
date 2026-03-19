from django.db import migrations, models


def create_terminal_runtime_settings(apps, schema_editor):
    SettingsModel = apps.get_model('terminal', 'TerminalRuntimeSettingsORM')
    SettingsModel.objects.get_or_create(
        singleton_key='default',
        defaults={'answer_chain_enabled': True},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('terminal', '0002_add_governance_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='TerminalRuntimeSettingsORM',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_key', models.CharField(default='default', editable=False, max_length=32, unique=True)),
                ('answer_chain_enabled', models.BooleanField(default=True, help_text='是否允许在 Terminal 回答中展开查看答案链条')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'terminal_runtime_settings',
                'verbose_name': 'Terminal 运行设置',
                'verbose_name_plural': 'Terminal 运行设置',
            },
        ),
        migrations.RunPython(create_terminal_runtime_settings, migrations.RunPython.noop),
    ]
