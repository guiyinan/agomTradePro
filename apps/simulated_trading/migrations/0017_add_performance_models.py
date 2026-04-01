"""Migration: add account performance and valuation models.

Models added:
  - AccountBenchmarkComponentModel
  - UnifiedAccountCashFlowModel
  - AccountPositionValuationSnapshotModel
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simulated_trading", "0016_quantity_to_decimal"),
    ]

    operations = [
        # ---------------------------------------------------------------
        # AccountBenchmarkComponentModel
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AccountBenchmarkComponentModel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="benchmark_components",
                        to="simulated_trading.simulatedaccountmodel",
                        verbose_name="所属账户",
                        db_index=True,
                    ),
                ),
                ("benchmark_code", models.CharField(max_length=30, verbose_name="基准代码", help_text="如 000300.SH")),
                ("weight", models.FloatField(verbose_name="权重（归一化后）", help_text="归一化后总和为 1.0")),
                ("display_name", models.CharField(blank=True, max_length=100, verbose_name="显示名称", help_text="如 沪深300")),
                ("sort_order", models.IntegerField(default=0, verbose_name="排序")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="是否启用")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "账户基准成分",
                "verbose_name_plural": "账户基准成分",
                "db_table": "account_benchmark_component",
                "ordering": ["account", "sort_order"],
            },
        ),
        migrations.AddIndex(
            model_name="accountbenchmarkcomponentmodel",
            index=models.Index(fields=["account", "is_active"], name="acct_bm_account_active_idx"),
        ),
        migrations.AddIndex(
            model_name="accountbenchmarkcomponentmodel",
            index=models.Index(fields=["account", "sort_order"], name="acct_bm_account_sort_idx"),
        ),
        # ---------------------------------------------------------------
        # UnifiedAccountCashFlowModel
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="UnifiedAccountCashFlowModel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cash_flows",
                        to="simulated_trading.simulatedaccountmodel",
                        verbose_name="所属账户",
                        db_index=True,
                    ),
                ),
                (
                    "flow_type",
                    models.CharField(
                        choices=[
                            ("initial_capital", "初始入金"),
                            ("deposit", "追加入金"),
                            ("withdrawal", "取款出金"),
                            ("dividend", "股息/分红"),
                            ("interest", "利息"),
                            ("adjustment", "手工调整"),
                        ],
                        db_index=True,
                        max_length=20,
                        verbose_name="现金流类型",
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15, verbose_name="金额（元）", help_text="正数=入金，负数=出金")),
                ("flow_date", models.DateField(db_index=True, verbose_name="发生日期")),
                ("source_app", models.CharField(max_length=50, verbose_name="来源应用", help_text="account 或 simulated_trading")),
                ("source_id", models.CharField(blank=True, default="", max_length=50, verbose_name="来源记录ID")),
                ("notes", models.CharField(blank=True, default="", max_length=500, verbose_name="备注")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "统一账户现金流",
                "verbose_name_plural": "统一账户现金流",
                "db_table": "unified_account_cash_flow",
                "ordering": ["account", "flow_date"],
            },
        ),
        migrations.AddIndex(
            model_name="unifiedaccountcashflowmodel",
            index=models.Index(fields=["account", "flow_date"], name="ucf_account_date_idx"),
        ),
        migrations.AddIndex(
            model_name="unifiedaccountcashflowmodel",
            index=models.Index(fields=["account", "flow_type"], name="ucf_account_type_idx"),
        ),
        migrations.AddIndex(
            model_name="unifiedaccountcashflowmodel",
            index=models.Index(fields=["source_app", "source_id"], name="ucf_source_idx"),
        ),
        # ---------------------------------------------------------------
        # AccountPositionValuationSnapshotModel
        # ---------------------------------------------------------------
        migrations.CreateModel(
            name="AccountPositionValuationSnapshotModel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="position_valuation_snapshots",
                        to="simulated_trading.simulatedaccountmodel",
                        verbose_name="所属账户",
                        db_index=True,
                    ),
                ),
                ("record_date", models.DateField(db_index=True, verbose_name="记录日期")),
                ("asset_code", models.CharField(max_length=20, verbose_name="资产代码")),
                ("asset_name", models.CharField(blank=True, default="", max_length=100, verbose_name="资产名称")),
                (
                    "asset_type",
                    models.CharField(
                        choices=[
                            ("equity", "股票"),
                            ("fund", "基金"),
                            ("bond", "债券"),
                            ("cash", "现金"),
                            ("other", "其他"),
                        ],
                        max_length=20,
                        verbose_name="资产类型",
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=6, max_digits=20, verbose_name="持仓数量")),
                ("avg_cost", models.DecimalField(decimal_places=4, default=0, max_digits=10, verbose_name="平均成本（元）")),
                ("close_price", models.DecimalField(decimal_places=4, default=0, max_digits=10, verbose_name="收盘价（元）")),
                ("market_value", models.DecimalField(decimal_places=2, max_digits=15, verbose_name="市值（元）")),
                ("weight", models.FloatField(default=0.0, verbose_name="仓位占比（市值/总市值）")),
                ("unrealized_pnl", models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name="浮动盈亏（元）")),
                ("unrealized_pnl_pct", models.FloatField(default=0.0, verbose_name="浮动盈亏率（%）")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
            ],
            options={
                "verbose_name": "持仓时点估值快照",
                "verbose_name_plural": "持仓时点估值快照",
                "db_table": "account_position_valuation_snapshot",
                "ordering": ["account", "-record_date", "asset_code"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="accountpositionvaluationsnapshotmodel",
            unique_together={("account", "record_date", "asset_code")},
        ),
        migrations.AddIndex(
            model_name="accountpositionvaluationsnapshotmodel",
            index=models.Index(fields=["account", "-record_date"], name="apvs_account_date_idx"),
        ),
        migrations.AddIndex(
            model_name="accountpositionvaluationsnapshotmodel",
            index=models.Index(fields=["account", "record_date", "asset_code"], name="apvs_account_date_code_idx"),
        ),
        migrations.AddIndex(
            model_name="accountpositionvaluationsnapshotmodel",
            index=models.Index(fields=["asset_code", "-record_date"], name="apvs_code_date_idx"),
        ),
    ]
