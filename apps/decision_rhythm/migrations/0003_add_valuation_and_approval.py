# Generated migration for valuation pricing engine

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    """
    添加估值定价引擎相关表

    新增表：
    - decision_valuation_snapshot: 估值快照
    - decision_investment_recommendation: 投资建议
    - decision_execution_approval_request: 执行审批请求
    """

    dependencies = [
        ("decision_rhythm", "0002_add_execution_fields"),
    ]

    operations = [
        # 1. 创建估值快照表
        migrations.CreateModel(
            name="ValuationSnapshotModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "snapshot_id",
                    models.CharField(
                        db_index=True,
                        help_text="快照唯一标识符",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "security_code",
                    models.CharField(
                        db_index=True,
                        help_text="证券代码",
                        max_length=32,
                    ),
                ),
                (
                    "valuation_method",
                    models.CharField(
                        choices=[
                            ("DCF", "现金流折现法"),
                            ("PE_BAND", "PE 通道法"),
                            ("PB_BAND", "PB 通道法"),
                            ("PEG", "PEG 估值法"),
                            ("DIVIDEND", "股息折现法"),
                            ("COMPOSITE", "综合估值法"),
                            ("LEGACY", "历史数据"),
                            ("CONSOLIDATED", "聚合估值"),
                        ],
                        help_text="估值方法",
                        max_length=16,
                    ),
                ),
                (
                    "fair_value",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="公允价值",
                        max_digits=12,
                    ),
                ),
                (
                    "entry_price_low",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="入场价格下限",
                        max_digits=12,
                    ),
                ),
                (
                    "entry_price_high",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="入场价格上限",
                        max_digits=12,
                    ),
                ),
                (
                    "target_price_low",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="目标价格下限",
                        max_digits=12,
                    ),
                ),
                (
                    "target_price_high",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="目标价格上限",
                        max_digits=12,
                    ),
                ),
                (
                    "stop_loss_price",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="止损价格",
                        max_digits=12,
                    ),
                ),
                (
                    "calculated_at",
                    models.DateTimeField(
                        db_index=True,
                        help_text="计算时间",
                    ),
                ),
                (
                    "input_parameters",
                    models.JSONField(
                        default=dict,
                        help_text="输入参数",
                    ),
                ),
                (
                    "version",
                    models.IntegerField(
                        default=1,
                        help_text="版本号",
                    ),
                ),
                (
                    "is_legacy",
                    models.BooleanField(
                        default=False,
                        help_text="是否为历史数据迁移",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="创建时间",
                    ),
                ),
            ],
            options={
                "verbose_name": "估值快照",
                "verbose_name_plural": "估值快照",
                "db_table": "decision_valuation_snapshot",
                "ordering": ["-calculated_at"],
                "indexes": [
                    models.Index(fields=["security_code", "-calculated_at"], name="idx_val_sec_calc"),
                    models.Index(fields=["valuation_method"], name="idx_val_method"),
                ],
            },
        ),

        # 2. 创建投资建议表
        migrations.CreateModel(
            name="InvestmentRecommendationModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "recommendation_id",
                    models.CharField(
                        db_index=True,
                        help_text="建议唯一标识符",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "security_code",
                    models.CharField(
                        db_index=True,
                        help_text="证券代码",
                        max_length=32,
                    ),
                ),
                (
                    "account_id",
                    models.CharField(
                        db_index=True,
                        default="default",
                        help_text="账户 ID",
                        max_length=64,
                    ),
                ),
                (
                    "side",
                    models.CharField(
                        choices=[
                            ("BUY", "买入"),
                            ("SELL", "卖出"),
                            ("HOLD", "持有"),
                        ],
                        help_text="方向",
                        max_length=8,
                    ),
                ),
                (
                    "confidence",
                    models.FloatField(
                        default=0.0,
                        help_text="置信度 (0-1)",
                    ),
                ),
                (
                    "valuation_method",
                    models.CharField(
                        help_text="估值方法",
                        max_length=16,
                    ),
                ),
                (
                    "fair_value",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="公允价值",
                        max_digits=12,
                    ),
                ),
                (
                    "entry_price_low",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="入场价格下限",
                        max_digits=12,
                    ),
                ),
                (
                    "entry_price_high",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="入场价格上限",
                        max_digits=12,
                    ),
                ),
                (
                    "target_price_low",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="目标价格下限",
                        max_digits=12,
                    ),
                ),
                (
                    "target_price_high",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="目标价格上限",
                        max_digits=12,
                    ),
                ),
                (
                    "stop_loss_price",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="止损价格",
                        max_digits=12,
                    ),
                ),
                (
                    "position_size_pct",
                    models.FloatField(
                        default=5.0,
                        help_text="建议仓位比例",
                    ),
                ),
                (
                    "max_capital",
                    models.DecimalField(
                        decimal_places=2,
                        default=50000,
                        help_text="最大资金量",
                        max_digits=15,
                    ),
                ),
                (
                    "reason_codes",
                    models.JSONField(
                        default=list,
                        help_text="原因代码列表",
                    ),
                ),
                (
                    "human_readable_rationale",
                    models.TextField(
                        blank=True,
                        help_text="人类可读的理由",
                    ),
                ),
                (
                    "source_recommendation_ids",
                    models.JSONField(
                        default=list,
                        help_text="来源建议 ID 列表",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "活跃"),
                            ("CONSOLIDATED", "已聚合"),
                            ("EXECUTED", "已执行"),
                            ("EXPIRED", "已过期"),
                            ("CANCELLED", "已取消"),
                        ],
                        db_index=True,
                        default="ACTIVE",
                        help_text="建议状态",
                        max_length=16,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        help_text="创建时间",
                    ),
                ),
                (
                    "valuation_snapshot",
                    models.ForeignKey(
                        blank=True,
                        help_text="关联的估值快照",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="recommendations",
                        to="decision_rhythm.valuationsnapshotmodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "投资建议",
                "verbose_name_plural": "投资建议",
                "db_table": "decision_investment_recommendation",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["account_id", "security_code", "side", "-created_at"], name="idx_rec_acc_sec_side_created"),
                    models.Index(fields=["status", "-created_at"], name="idx_rec_status_created"),
                ],
            },
        ),

        # 3. 创建执行审批请求表
        migrations.CreateModel(
            name="ExecutionApprovalRequestModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "request_id",
                    models.CharField(
                        db_index=True,
                        help_text="请求唯一标识符",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "account_id",
                    models.CharField(
                        db_index=True,
                        help_text="账户 ID",
                        max_length=64,
                    ),
                ),
                (
                    "security_code",
                    models.CharField(
                        db_index=True,
                        help_text="证券代码",
                        max_length=32,
                    ),
                ),
                (
                    "side",
                    models.CharField(
                        choices=[
                            ("BUY", "买入"),
                            ("SELL", "卖出"),
                            ("HOLD", "持有"),
                        ],
                        help_text="方向",
                        max_length=8,
                    ),
                ),
                (
                    "approval_status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "草稿"),
                            ("PENDING", "待审批"),
                            ("APPROVED", "已批准"),
                            ("REJECTED", "已拒绝"),
                            ("EXECUTED", "已执行"),
                            ("FAILED", "执行失败"),
                        ],
                        db_index=True,
                        default="PENDING",
                        help_text="审批状态",
                        max_length=16,
                    ),
                ),
                (
                    "suggested_quantity",
                    models.IntegerField(
                        help_text="建议数量",
                    ),
                ),
                (
                    "market_price_at_review",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        help_text="审批时的市场价格",
                        max_digits=12,
                        null=True,
                    ),
                ),
                (
                    "price_range_low",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="价格区间下限",
                        max_digits=12,
                    ),
                ),
                (
                    "price_range_high",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="价格区间上限",
                        max_digits=12,
                    ),
                ),
                (
                    "stop_loss_price",
                    models.DecimalField(
                        decimal_places=4,
                        help_text="止损价格",
                        max_digits=12,
                    ),
                ),
                (
                    "risk_check_results",
                    models.JSONField(
                        default=dict,
                        help_text="风控检查结果",
                    ),
                ),
                (
                    "reviewer_comments",
                    models.TextField(
                        blank=True,
                        help_text="审批评论",
                    ),
                ),
                (
                    "regime_source",
                    models.CharField(
                        default="UNKNOWN",
                        help_text="Regime 来源标识",
                        max_length=64,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        help_text="创建时间",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="审批时间",
                        null=True,
                    ),
                ),
                (
                    "executed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="执行时间",
                        null=True,
                    ),
                ),
                (
                    "recommendation",
                    models.ForeignKey(
                        help_text="关联的投资建议",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_requests",
                        to="decision_rhythm.investmentrecommendationmodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "执行审批请求",
                "verbose_name_plural": "执行审批请求",
                "db_table": "decision_execution_approval_request",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["account_id", "security_code", "side", "-created_at"], name="idx_apr_acc_sec_side_created"),
                    models.Index(fields=["approval_status", "-created_at"], name="idx_apr_status_created"),
                    models.Index(fields=["regime_source"], name="idx_apr_regime_source"),
                ],
            },
        ),

        # 4. 添加唯一约束：同账户同证券同方向只能有一个 PENDING
        migrations.AddIndex(
            model_name="executionapprovalrequestmodel",
            index=models.Index(
                fields=["account_id", "security_code", "side"],
                name="idx_unique_pending_approval",
                condition=models.Q(approval_status="PENDING"),
            ),
        ),
    ]
