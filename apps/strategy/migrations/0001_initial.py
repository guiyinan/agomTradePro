# Generated migration for Strategy System
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('account', '0001_initial'),
        ('simulated_trading', '0001_initial'),
        ('prompt', '0001_initial'),
        ('ai_provider', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StrategyModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='策略名称')),
                ('description', models.TextField(blank=True, verbose_name='策略描述')),
                ('strategy_type', models.CharField(
                    choices=[('rule_based', '规则驱动'), ('script_based', '脚本驱动'),
                           ('hybrid', '混合模式'), ('ai_driven', 'AI驱动')],
                    db_index=True, max_length=20, verbose_name='策略类型')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='版本号')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='是否激活')),
                ('max_position_pct', models.FloatField(
                    default=20.0,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(100.0)],
                    verbose_name='单资产最大持仓比例(%)')),
                ('max_total_position_pct', models.FloatField(
                    default=95.0,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(100.0)],
                    verbose_name='总持仓比例上限(%)')),
                ('stop_loss_pct', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(100.0)],
                    verbose_name='止损比例(%)')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(
                    db_index=True, on_delete=django.db.models.deletion.CASCADE,
                    to='account.accountprofilemodel', verbose_name='创建者')),
            ],
            options={
                'verbose_name': '投资策略',
                'verbose_name_plural': '投资策略',
                'db_table': 'strategy',
                'ordering': ['-created_at'],
                'unique_together': {('name', 'version', 'created_by')},
            },
        ),
        migrations.CreateModel(
            name='RuleConditionModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rule_name', models.CharField(max_length=200, verbose_name='规则名称')),
                ('rule_type', models.CharField(
                    choices=[('macro', '宏观指标'), ('regime', 'Regime判定'),
                           ('signal', '投资信号'), ('technical', '技术指标'),
                           ('composite', '组合条件')],
                    max_length=50, verbose_name='规则类型')),
                ('condition_json', models.JSONField(
                    help_text="JSON格式: 支持AND/OR/NOT、比较运算、趋势判断",
                    verbose_name="条件表达式")),
                ('action', models.CharField(
                    choices=[('buy', '买入'), ('sell', '卖出'), ('hold', '持有'), ('weight', '设置权重')],
                    max_length=50, verbose_name='动作')),
                ('weight', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(1.0)],
                    verbose_name='目标权重')),
                ('target_assets', models.JSONField(
                    blank=True, default=list, help_text="空列表表示所有可投资产")),
                ('priority', models.IntegerField(db_index=True, default=0, verbose_name='优先级')),
                ('is_enabled', models.BooleanField(default=True, verbose_name='是否启用')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('strategy', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='rules',
                    to='strategy.strategymodel', verbose_name='所属策略')),
            ],
            options={
                'verbose_name': '规则条件',
                'verbose_name_plural': '规则条件',
                'db_table': 'rule_condition',
                'ordering': ['-priority', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ScriptConfigModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('script_language', models.CharField(
                    choices=[('python', 'Python受限')], default='python',
                    max_length=20, verbose_name='脚本语言')),
                ('script_code', models.TextField(verbose_name='脚本代码')),
                ('script_hash', models.CharField(
                    help_text="SHA256哈希，用于检测脚本变更", max_length=64, unique=True,
                    verbose_name='脚本哈希')),
                ('sandbox_config', models.JSONField(
                    default=dict, help_text="沙箱安全策略配置")),
                ('allowed_modules', models.JSONField(
                    default=list, help_text="允许导入的模块白名单")),
                ('version', models.CharField(default="1.0", max_length=20, verbose_name='版本号')),
                ('is_active', models.BooleanField(default=True, verbose_name='是否激活')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('strategy', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name='script_config',
                    to='strategy.strategymodel', verbose_name='所属策略')),
            ],
            options={
                'verbose_name': '脚本配置',
                'verbose_name_plural': '脚本配置',
                'db_table': 'script_config',
            },
        ),
        migrations.CreateModel(
            name='AIStrategyConfigModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('temperature', models.FloatField(
                    default=0.7,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(2.0)],
                    verbose_name='温度参数')),
                ('max_tokens', models.IntegerField(
                    default=2000,
                    validators=[django.core.validators.MinValueValidator(1)],
                    verbose_name='最大Token数')),
                ('approval_mode', models.CharField(
                    choices=[('always', '必须人工审核'), ('conditional', '条件审核（基于置信度）'),
                           ('auto', '自动执行+监控')],
                    default='conditional', max_length=20, verbose_name='审核模式')),
                ('confidence_threshold', models.FloatField(
                    default=0.8,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(1.0)],
                    help_text="置信度高于此值时自动执行", verbose_name='自动执行置信度阈值')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('strategy', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name='ai_config',
                    to='strategy.strategymodel', verbose_name='所属策略')),
                ('prompt_template', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ai_strategies', to='prompt.prompttemplateorm',
                    verbose_name='Prompt模板')),
                ('chain_config', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ai_strategies', to='prompt.chainconfigorm',
                    verbose_name='链配置')),
                ('ai_provider', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ai_strategies', to='ai_provider.aiproviderconfig',
                    verbose_name='AI服务商')),
            ],
            options={
                'verbose_name': 'AI策略配置',
                'verbose_name_plural': 'AI策略配置',
                'db_table': 'ai_strategy_config',
            },
        ),
        migrations.CreateModel(
            name='PortfolioStrategyAssignmentModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='分配时间')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='是否激活')),
                ('override_max_position_pct', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(100.0)],
                    verbose_name='覆盖单资产最大持仓比例(%)')),
                ('override_stop_loss_pct', models.FloatField(
                    blank=True, null=True,
                    validators=[django.core.validators.MinValueValidator(0.0),
                              django.core.validators.MaxValueValidator(100.0)],
                    verbose_name='覆盖止损比例(%)')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('portfolio', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='strategy_assignments',
                    to='simulated_trading.simulatedaccountmodel', verbose_name='投资组合')),
                ('strategy', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='portfolio_assignments',
                    to='strategy.strategymodel', verbose_name='策略')),
                ('assigned_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='account.accountprofilemodel', verbose_name='分配者')),
            ],
            options={
                'verbose_name': '投资组合策略关联',
                'verbose_name_plural': '投资组合策略关联',
                'db_table': 'portfolio_strategy_assignment',
                'ordering': ['-created_at'],
                'unique_together': {('portfolio', 'strategy')},
            },
        ),
        migrations.CreateModel(
            name='StrategyExecutionLogModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('execution_time', models.DateTimeField(
                    auto_now_add=True, db_index=True, verbose_name='执行时间')),
                ('execution_duration_ms', models.IntegerField(verbose_name='执行时长(ms)')),
                ('execution_result', models.JSONField(help_text="详细执行信息")),
                ('signals_generated', models.JSONField(default=list, help_text="信号列表")),
                ('error_message', models.TextField(blank=True, verbose_name='错误信息')),
                ('error_traceback', models.TextField(blank=True, verbose_name='错误堆栈')),
                ('is_success', models.BooleanField(db_index=True, default=True, verbose_name='是否成功')),
                ('strategy', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='execution_logs',
                    to='strategy.strategymodel', verbose_name='策略')),
                ('portfolio', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='strategy_execution_logs',
                    to='simulated_trading.simulatedaccountmodel', verbose_name='投资组合')),
            ],
            options={
                'verbose_name': '策略执行日志',
                'verbose_name_plural': '策略执行日志',
                'db_table': 'strategy_execution_log',
                'ordering': ['-execution_time'],
            },
        ),
    ]
