"""
Config center infrastructure models.

Owns global runtime settings and Qlib training center persistence.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def _build_app_fernet() -> Fernet:
    secret = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or getattr(
        settings, "SECRET_KEY", ""
    )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


class SystemSettingsModel(models.Model):
    """
    Global singleton system settings.

    Database table name stays unchanged to avoid data migration.
    """

    require_user_approval = models.BooleanField(
        default=True, verbose_name="需要管理员审批新用户", help_text="关闭后新用户注册将自动批准"
    )
    auto_approve_first_admin = models.BooleanField(
        default=True,
        verbose_name="自动批准首个管理员用户",
        help_text="系统无管理员时，首个注册的用户自动成为管理员并获得批准",
    )
    default_mcp_enabled = models.BooleanField(
        default=True,
        verbose_name="新用户默认开启 MCP/SDK",
        help_text="新注册或新批准用户默认是否允许 MCP/SDK 访问，由管理员决定",
    )

    MARKET_COLOR_CONVENTION_CHOICES = [
        ("cn_a_share", "A股红涨绿跌"),
        ("us_market", "美股绿涨红跌"),
    ]
    market_color_convention = models.CharField(
        max_length=32,
        default="cn_a_share",
        choices=MARKET_COLOR_CONVENTION_CHOICES,
        verbose_name="市场颜色约定",
        help_text="统一控制涨跌、资金流入流出的语义颜色映射。",
    )
    allow_token_plaintext_view = models.BooleanField(
        default=True,
        verbose_name="允许查看 Token 明文",
        help_text="关闭后，生成后不再显示完整 Token，历史 Token 也不可明文查看",
    )

    user_agreement_content = models.TextField(
        blank=True, verbose_name="用户协议内容", help_text="用户注册时需要同意的协议内容，支持HTML"
    )
    risk_warning_content = models.TextField(
        blank=True,
        verbose_name="风险提示内容",
        help_text="用户注册时需要确认的风险提示内容，支持HTML",
    )
    notes = models.TextField(blank=True, verbose_name="备注")

    benchmark_code_map = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="基准代码映射",
        help_text="系统运行时使用的基准/默认指数代码映射",
    )
    asset_proxy_code_map = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="资产代理代码映射",
        help_text="资产类别到实际交易/价格代理代码的映射",
    )

    backup_email = models.EmailField(
        blank=True,
        verbose_name="数据库备份接收邮箱",
        help_text="启用后按周期发送数据库全量备份下载链接到该邮箱",
    )
    backup_app_base_url = models.URLField(
        blank=True,
        verbose_name="备份下载站点地址",
        help_text="用于生成邮件中的绝对下载链接，如 https://example.com",
    )
    backup_mail_from_email = models.EmailField(
        blank=True, verbose_name="备份邮件发件人", help_text="留空则回退到系统默认发件人"
    )
    backup_smtp_host = models.CharField(max_length=255, blank=True, verbose_name="SMTP 主机")
    backup_smtp_port = models.PositiveIntegerField(default=587, verbose_name="SMTP 端口")
    backup_smtp_username = models.CharField(max_length=255, blank=True, verbose_name="SMTP 用户名")
    backup_smtp_password_encrypted = models.TextField(
        blank=True, verbose_name="SMTP 密码（密文）", help_text="系统内部加密存储"
    )
    backup_smtp_use_tls = models.BooleanField(default=True, verbose_name="SMTP 使用 TLS")
    backup_smtp_use_ssl = models.BooleanField(default=False, verbose_name="SMTP 使用 SSL")
    backup_enabled = models.BooleanField(
        default=False,
        verbose_name="启用数据库备份邮件",
        help_text="开启后系统会按设定周期发送备份下载链接",
    )
    backup_interval_days = models.PositiveIntegerField(
        default=7, verbose_name="备份周期（天）", help_text="每隔多少天发送一次数据库备份下载链接"
    )
    backup_link_ttl_days = models.PositiveIntegerField(
        default=3, verbose_name="下载链接有效期（天）", help_text="邮件中的备份下载链接有效天数"
    )
    backup_password_encrypted = models.TextField(
        blank=True,
        verbose_name="备份压缩密码（密文）",
        help_text="系统内部加密存储，用于生成加密备份文件",
    )
    backup_password_hint = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="备份密码提示",
        help_text="可选，用于管理员识别当前使用的备份密码",
    )
    backup_last_sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name="上次备份邮件发送时间"
    )

    qlib_enabled = models.BooleanField(
        default=False, verbose_name="启用 Qlib", help_text="开启后系统将使用 Qlib 进行量化分析"
    )
    qlib_provider_uri = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Qlib 数据目录",
        help_text="Qlib 数据存储路径，如 D:/qlib_data/cn_data 或 /var/lib/qlib/cn_data",
    )
    qlib_region = models.CharField(
        max_length=10,
        default="CN",
        verbose_name="Qlib 区域",
        help_text="市场区域，如 CN（中国）、US（美国）",
    )
    qlib_model_path = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Qlib 模型目录",
        help_text="Qlib 模型存储路径，留空使用默认路径",
    )
    qlib_default_universe = models.CharField(
        max_length=50,
        default="csi300",
        verbose_name="Qlib 默认股票池",
    )
    qlib_default_feature_set_id = models.CharField(
        max_length=50,
        default="v1",
        verbose_name="Qlib 默认特征集标识",
    )
    qlib_default_label_id = models.CharField(
        max_length=50,
        default="return_5d",
        verbose_name="Qlib 默认标签标识",
    )
    qlib_train_queue_name = models.CharField(
        max_length=64,
        default="qlib_train",
        verbose_name="Qlib 训练队列名",
    )
    qlib_infer_queue_name = models.CharField(
        max_length=64,
        default="qlib_infer",
        verbose_name="Qlib 推理队列名",
    )
    qlib_allow_auto_activate = models.BooleanField(
        default=False,
        verbose_name="允许训练后自动激活",
        help_text="训练触发未显式指定时，使用该全局默认值控制是否自动切换 active model。",
    )

    ALPHA_PROVIDER_CHOICES = [
        ("", "自动降级（默认）"),
        ("qlib", "仅使用 Qlib"),
        ("cache", "仅使用缓存"),
        ("simple", "仅使用 Simple"),
        ("etf", "仅使用 ETF"),
    ]
    ALPHA_POOL_MODE_STRICT_VALUATION = "strict_valuation"
    ALPHA_POOL_MODE_MARKET = "market"
    ALPHA_POOL_MODE_PRICE_COVERED = "price_covered"
    ALPHA_POOL_MODE_CHOICES = [
        (ALPHA_POOL_MODE_STRICT_VALUATION, "严格估值覆盖池"),
        (ALPHA_POOL_MODE_MARKET, "市场可交易池"),
        (ALPHA_POOL_MODE_PRICE_COVERED, "价格覆盖池"),
    ]
    alpha_fixed_provider = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=ALPHA_PROVIDER_CHOICES,
        verbose_name="固定 Alpha Provider",
        help_text="强制使用指定的 Provider（禁用自动降级），留空则启用自动降级",
    )
    alpha_pool_mode = models.CharField(
        max_length=32,
        default=ALPHA_POOL_MODE_STRICT_VALUATION,
        choices=ALPHA_POOL_MODE_CHOICES,
        verbose_name="Alpha 默认股票池模式",
        help_text="控制首页 Alpha 和实时推理默认使用哪个候选股票集合",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "system_settings"
        verbose_name = "系统配置"
        verbose_name_plural = "系统配置"

    def __str__(self):
        return f"系统配置 (审批:{'开启' if self.require_user_approval else '关闭'})"

    def clean(self):
        super().clean()
        if self.backup_enabled:
            if not self.backup_email:
                raise ValidationError({"backup_email": "启用数据库备份邮件时必须配置接收邮箱。"})
            if not self.backup_password_encrypted:
                raise ValidationError(
                    {"backup_password_encrypted": "启用数据库备份邮件时必须设置备份密码。"}
                )
            if not self.backup_app_base_url:
                raise ValidationError(
                    {"backup_app_base_url": "启用数据库备份邮件时必须配置下载站点地址。"}
                )
            if not self.backup_smtp_host:
                raise ValidationError(
                    {"backup_smtp_host": "启用数据库备份邮件时必须配置 SMTP 主机。"}
                )
            if not self.backup_smtp_port:
                raise ValidationError(
                    {"backup_smtp_port": "启用数据库备份邮件时必须配置 SMTP 端口。"}
                )
            if not self.backup_mail_from_email:
                raise ValidationError(
                    {"backup_mail_from_email": "启用数据库备份邮件时必须配置发件人邮箱。"}
                )
            if not self.get_backup_smtp_password():
                raise ValidationError(
                    {"backup_smtp_password_encrypted": "启用数据库备份邮件时必须设置 SMTP 密码。"}
                )
        if self.backup_smtp_use_tls and self.backup_smtp_use_ssl:
            raise ValidationError("SMTP TLS 和 SSL 不能同时开启。")
        if self.backup_interval_days < 1:
            raise ValidationError({"backup_interval_days": "备份周期必须大于等于 1 天。"})
        if self.backup_link_ttl_days < 1:
            raise ValidationError({"backup_link_ttl_days": "下载链接有效期必须大于等于 1 天。"})

    @classmethod
    def get_settings(cls):
        settings_obj, _ = cls._default_manager.get_or_create(
            pk=1,
            defaults={
                "require_user_approval": True,
                "auto_approve_first_admin": True,
                "user_agreement_content": cls._get_default_agreement(),
                "risk_warning_content": cls._get_default_risk_warning(),
                "benchmark_code_map": cls._get_default_benchmark_code_map(),
                "asset_proxy_code_map": cls._get_default_asset_proxy_code_map(),
            },
        )
        update_fields = []
        if not settings_obj.benchmark_code_map:
            settings_obj.benchmark_code_map = cls._get_default_benchmark_code_map()
            update_fields.append("benchmark_code_map")
        if not settings_obj.asset_proxy_code_map:
            settings_obj.asset_proxy_code_map = cls._get_default_asset_proxy_code_map()
            update_fields.append("asset_proxy_code_map")
        if update_fields:
            update_fields.append("updated_at")
            settings_obj.save(update_fields=update_fields)
        return settings_obj

    @staticmethod
    def _get_secret_fernet() -> Fernet:
        return _build_app_fernet()

    def set_backup_password(self, raw_password: str):
        raw_password = (raw_password or "").strip()
        if not raw_password:
            self.backup_password_encrypted = ""
            return
        self.backup_password_encrypted = (
            self._get_secret_fernet().encrypt(raw_password.encode("utf-8")).decode("utf-8")
        )

    def get_backup_password(self) -> str:
        if not self.backup_password_encrypted:
            return ""
        try:
            return (
                self._get_secret_fernet()
                .decrypt(self.backup_password_encrypted.encode("utf-8"))
                .decode("utf-8")
            )
        except (InvalidToken, TypeError, ValueError):
            return ""

    def set_backup_smtp_password(self, raw_password: str):
        raw_password = (raw_password or "").strip()
        if not raw_password:
            self.backup_smtp_password_encrypted = ""
            return
        self.backup_smtp_password_encrypted = (
            self._get_secret_fernet().encrypt(raw_password.encode("utf-8")).decode("utf-8")
        )

    def get_backup_smtp_password(self) -> str:
        if not self.backup_smtp_password_encrypted:
            return ""
        try:
            return (
                self._get_secret_fernet()
                .decrypt(self.backup_smtp_password_encrypted.encode("utf-8"))
                .decode("utf-8")
            )
        except (InvalidToken, TypeError, ValueError):
            return ""

    def is_backup_due(self, now=None) -> bool:
        if not self.backup_enabled or not self.backup_email or not self.get_backup_password():
            return False
        now = now or datetime.now(UTC)
        if self.backup_last_sent_at is None:
            return True
        return (now - self.backup_last_sent_at).days >= self.backup_interval_days

    def get_benchmark_code(self, key: str, default: str = "") -> str:
        value = (self.benchmark_code_map or {}).get(key, default)
        return value if isinstance(value, str) else default

    def get_market_visual_tokens(self) -> dict[str, str]:
        palettes = {
            "cn_a_share": {
                "rise": "var(--color-error)",
                "fall": "var(--color-success)",
                "rise_soft": "var(--color-error-light)",
                "fall_soft": "var(--color-success-light)",
                "rise_strong": "var(--color-error-dark)",
                "fall_strong": "var(--color-success-dark)",
                "inflow": "var(--color-error)",
                "outflow": "var(--color-success)",
                "convention": "cn_a_share",
                "label": "A股红涨绿跌",
            },
            "us_market": {
                "rise": "var(--color-success)",
                "fall": "var(--color-error)",
                "rise_soft": "var(--color-success-light)",
                "fall_soft": "var(--color-error-light)",
                "rise_strong": "var(--color-success-dark)",
                "fall_strong": "var(--color-error-dark)",
                "inflow": "var(--color-success)",
                "outflow": "var(--color-error)",
                "convention": "us_market",
                "label": "美股绿涨红跌",
            },
        }
        return palettes.get(self.market_color_convention, palettes["cn_a_share"]).copy()

    def get_asset_proxy_code(self, asset_class: str, default: str = "") -> str:
        value = (self.asset_proxy_code_map or {}).get(asset_class, default)
        return value if isinstance(value, str) else default

    def get_qlib_provider_uri(self) -> str:
        default_uri = settings.QLIB_SETTINGS.get("provider_uri", "~/.qlib/qlib_data/cn_data")
        if self.qlib_provider_uri:
            configured_path = Path(self.qlib_provider_uri).expanduser()
            if configured_path.exists():
                return self.qlib_provider_uri
            default_path = Path(default_uri).expanduser()
            if default_path.exists():
                return str(default_path)
            return self.qlib_provider_uri
        return default_uri

    def get_qlib_region(self) -> str:
        if self.qlib_region:
            return self.qlib_region
        return settings.QLIB_SETTINGS.get("region", "CN")

    def get_qlib_model_path(self) -> str:
        default_path = settings.QLIB_SETTINGS.get("model_path", "/models/qlib")
        if self.qlib_model_path:
            configured_path = Path(self.qlib_model_path).expanduser()
            if configured_path.exists():
                return self.qlib_model_path
            fallback_path = Path(default_path).expanduser()
            if fallback_path.exists():
                return str(fallback_path)
            return self.qlib_model_path
        return default_path

    def is_qlib_configured(self) -> bool:
        if not self.qlib_enabled:
            return False
        provider_uri = self.get_qlib_provider_uri()
        if not provider_uri:
            return False
        return Path(provider_uri).expanduser().exists()

    def get_runtime_qlib_config_payload(self) -> dict[str, object]:
        return {
            "enabled": self.qlib_enabled,
            "provider_uri": self.get_qlib_provider_uri(),
            "region": self.get_qlib_region(),
            "model_path": self.get_qlib_model_path(),
            "default_universe": self.qlib_default_universe or "csi300",
            "default_feature_set_id": self.qlib_default_feature_set_id or "v1",
            "default_label_id": self.qlib_default_label_id or "return_5d",
            "train_queue_name": self.qlib_train_queue_name or "qlib_train",
            "infer_queue_name": self.qlib_infer_queue_name or "qlib_infer",
            "allow_auto_activate": bool(self.qlib_allow_auto_activate),
            "is_configured": self.is_qlib_configured(),
        }

    @classmethod
    def get_runtime_benchmark_code(cls, key: str, default: str = "") -> str:
        return cls.get_settings().get_benchmark_code(key, default)

    @classmethod
    def get_runtime_asset_proxy_code(cls, asset_class: str, default: str = "") -> str:
        return cls.get_settings().get_asset_proxy_code(asset_class, default)

    @classmethod
    def get_runtime_market_visual_tokens(cls) -> dict[str, str]:
        return cls.get_settings().get_market_visual_tokens()

    @classmethod
    def get_runtime_asset_proxy_map(cls) -> dict:
        return cls.get_settings().asset_proxy_code_map or {}

    @classmethod
    def get_runtime_qlib_config(cls) -> dict:
        return cls.get_settings().get_runtime_qlib_config_payload()

    @classmethod
    def get_runtime_alpha_fixed_provider(cls) -> str:
        return cls.get_settings().alpha_fixed_provider or ""

    @classmethod
    def get_runtime_alpha_pool_mode(cls) -> str:
        return cls.get_settings().alpha_pool_mode or cls.ALPHA_POOL_MODE_STRICT_VALUATION

    @staticmethod
    def _get_default_agreement():
        return """
<h2>AgomTradePro 用户服务协议</h2>
<p>欢迎使用 AgomTradePro（个人投研平台）！在使用本系统前，请仔细阅读以下条款：</p>

<h3>一、服务说明</h3>
<p>AgomTradePro 是一个辅助投资决策工具，通过宏观环境分析和策略回测帮助用户制定投资计划。本系统提供的所有信息仅供参考，不构成任何投资建议。</p>

<h3>二、用户责任</h3>
<ul>
    <li>用户应妥善保管账户和密码，对账户下的所有行为负责</li>
    <li>用户不得利用本系统进行任何违法或不当活动</li>
    <li>用户应确保提供的信息真实、准确、完整</li>
</ul>

<h3>三、免责声明</h3>
<ul>
    <li>本系统基于历史数据分析，历史业绩不代表未来表现</li>
    <li>投资有风险，决策需谨慎。本系统不对任何投资损失承担责任</li>
    <li>系统可能因技术故障、数据延迟等原因出现误差</li>
    <li>本系统保留随时修改或中断服务的权利</li>
</ul>

<h3>四、隐私保护</h3>
<p>我们将严格保护用户隐私，不会向第三方泄露用户个人信息（法律法规另有规定的除外）。</p>

<h3>五、协议修改</h3>
<p>本系统有权随时修改本协议，修改后的协议一经公布即生效。</p>
"""

    @staticmethod
    def _get_default_benchmark_code_map():
        return {
            "equity_default_index": "000300.SH",
            "equity_market_benchmark": "000300.SH",
            "factor_beta_benchmark": "000300.SH",
        }

    @staticmethod
    def _get_default_asset_proxy_code_map():
        return {
            "A_SHARE_GROWTH": "000300.SH",
            "A_SHARE_VALUE": "000905.SH",
            "CHINA_BOND": "TS01.CS",
            "GOLD": "AU9999.SGE",
            "COMMODITY": "NHCI.NH",
            "CASH": "CASH",
            "a_share_growth": "000300.SH",
            "a_share_value": "000905.SH",
            "china_bond": "TS01.CS",
            "gold": "AU9999.SGE",
            "commodity": "NHCI.NH",
            "cash": "CASH",
        }

    @staticmethod
    def _get_default_risk_warning():
        return """
<h2>投资风险提示书</h2>
<p>在使用 AgomTradePro 进行投资决策前，请充分了解以下风险：</p>

<h3>一、市场风险</h3>
<ul>
    <li><strong>价格波动风险：</strong>资产价格可能因市场变化而大幅波动，导致投资损失</li>
    <li><strong>流动性风险：</strong>某些资产可能在特定时期难以以合理价格买卖</li>
    <li><strong>系统性风险：</strong>宏观经济、政策变化等因素可能导致市场整体下跌</li>
</ul>

<h3>二、模型风险</h3>
<ul>
    <li><strong>历史局限性：</strong>本系统基于历史数据分析，历史规律未必在未来重复</li>
    <li><strong>模型偏差：</strong>任何模型都有其适用范围和局限性，可能产生错误信号</li>
    <li><strong>数据风险：</strong>数据来源、延迟、错误等因素可能影响分析结果</li>
</ul>

<h3>三、操作风险</h3>
<ul>
    <li><strong>执行偏差：</strong>实际交易可能与系统建议存在偏差</li>
    <li><strong>过度依赖：</strong>过度依赖系统信号而忽视基本面分析可能导致损失</li>
</ul>

<h3>四、特别提示</h3>
<ul>
    <li>模拟交易收益不代表实际交易收益</li>
    <li>回测结果是理想状态下的表现，实际交易存在滑点、手续费等成本</li>
    <li>投资决策应综合考虑个人风险承受能力、投资目标等因素</li>
    <li>建议在投资前咨询专业的投资顾问</li>
</ul>

<h3>五、风险自担</h3>
<p><strong>我已充分了解投资风险，理解本系统提供的所有信息仅供参考，将自行承担所有投资决策带来的风险和损失。</strong></p>
        """


class QlibTrainingProfileModel(models.Model):
    """Reusable Qlib training template."""

    profile_key = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="模板键")
    name = models.CharField(max_length=120, verbose_name="模板名称")
    model_name = models.CharField(max_length=100, verbose_name="模型名称")
    model_type = models.CharField(max_length=50, verbose_name="模型类型")
    universe = models.CharField(max_length=50, blank=True, default="", verbose_name="股票池")
    start_date = models.DateField(null=True, blank=True, verbose_name="训练开始日期")
    end_date = models.DateField(null=True, blank=True, verbose_name="训练结束日期")
    feature_set_id = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="特征集标识",
    )
    label_id = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="标签标识",
    )
    learning_rate = models.FloatField(null=True, blank=True, verbose_name="学习率")
    epochs = models.PositiveIntegerField(null=True, blank=True, verbose_name="训练轮数")
    model_params = models.JSONField(default=dict, blank=True, verbose_name="模型参数")
    extra_train_config = models.JSONField(default=dict, blank=True, verbose_name="附加训练配置")
    activate_after_train = models.BooleanField(default=False, verbose_name="训练完成后自动激活")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_qlib_training_profile"
        verbose_name = "Qlib 训练模板"
        verbose_name_plural = "Qlib 训练模板"
        ordering = ["name", "profile_key"]

    def __str__(self):
        return f"{self.name} ({self.profile_key})"


class QlibTrainingRunModel(models.Model):
    """Tracked Qlib training execution."""

    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_SUCCEEDED = "SUCCEEDED"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "等待中"),
        (STATUS_RUNNING, "运行中"),
        (STATUS_SUCCEEDED, "成功"),
        (STATUS_FAILED, "失败"),
        (STATUS_CANCELLED, "取消"),
    ]

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    profile = models.ForeignKey(
        "config_center.QlibTrainingProfileModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runs",
        verbose_name="训练模板",
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name="状态",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qlib_training_runs",
        verbose_name="发起人",
    )
    requested_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="发起时间")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    celery_task_id = models.CharField(max_length=100, blank=True, default="", verbose_name="Celery Task ID")
    model_name = models.CharField(max_length=100, verbose_name="模型名称")
    model_type = models.CharField(max_length=50, verbose_name="模型类型")
    resolved_train_config = models.JSONField(default=dict, blank=True, verbose_name="最终训练配置")
    result_model_name = models.CharField(max_length=100, blank=True, default="", verbose_name="结果模型名")
    result_artifact_hash = models.CharField(max_length=64, blank=True, default="", verbose_name="结果 Artifact Hash")
    result_metrics = models.JSONField(default=dict, blank=True, verbose_name="结果指标")
    registry_result = models.JSONField(default=dict, blank=True, verbose_name="注册结果")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_qlib_training_run"
        verbose_name = "Qlib 训练任务"
        verbose_name_plural = "Qlib 训练任务"
        ordering = ["-requested_at", "-id"]

    def __str__(self):
        return f"{self.model_name} [{self.status}]"

