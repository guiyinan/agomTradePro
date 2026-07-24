"""
DRF Serializers for Account API.
"""

import math
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypeAlias

from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework import serializers

from apps.account.application.interface_services import (
    TOKEN_ACCESS_LEVEL_CHOICES,
    TOKEN_ACCESS_LEVEL_READ_ONLY,
    count_owned_active_observer_grants,
    create_observer_grant_record,
    find_user_by_id,
    find_user_by_username,
    get_active_observer_grant,
)

SerializerField: TypeAlias = serializers.Field[Any, Any, Any, Any]

AccountProfileModel = django_apps.get_model("account", "AccountProfileModel")
AssetCategoryModel = django_apps.get_model("account", "AssetCategoryModel")
AssetMetadataModel = django_apps.get_model("account", "AssetMetadataModel")
CapitalFlowModel = django_apps.get_model("account", "CapitalFlowModel")
CurrencyModel = django_apps.get_model("account", "CurrencyModel")
PortfolioModel = django_apps.get_model("account", "PortfolioModel")
PortfolioObserverGrantModel = django_apps.get_model("account", "PortfolioObserverGrantModel")
PositionModel = django_apps.get_model("account", "PositionModel")
TradingCostConfigModel = django_apps.get_model("account", "TradingCostConfigModel")
TransactionModel = django_apps.get_model("account", "TransactionModel")

# ==================== Account Profile ====================


class AccountProfileSerializer(serializers.ModelSerializer[Any]):
    """账户配置序列化器"""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AccountProfileModel
        fields = [
            "id",
            "user_id",
            "username",
            "display_name",
            "initial_capital",
            "risk_tolerance",
            "rbac_role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["rbac_role", "created_at", "updated_at"]


class AccountProfileUpdateSerializer(serializers.ModelSerializer[Any]):
    """账户配置更新序列化器"""

    class Meta:
        model = AccountProfileModel
        fields = ["display_name", "risk_tolerance"]


# ==================== Portfolio ====================


class PortfolioSerializer(serializers.ModelSerializer[Any]):
    """投资组合序列化器"""

    username = serializers.CharField(source="user.username", read_only=True)
    base_currency_code = serializers.CharField(
        source="base_currency.code", read_only=True, allow_null=True
    )
    base_currency_name = serializers.CharField(
        source="base_currency.name", read_only=True, allow_null=True
    )
    total_value = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_pnl = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    total_pnl_pct = serializers.FloatField(read_only=True)
    position_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PortfolioModel
        fields = [
            "id",
            "name",
            "is_active",
            "base_currency",
            "base_currency_code",
            "base_currency_name",
            "total_value",
            "total_cost",
            "total_pnl",
            "total_pnl_pct",
            "position_count",
            "username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class PortfolioCreateSerializer(serializers.ModelSerializer[Any]):
    """投资组合创建序列化器"""

    class Meta:
        model = PortfolioModel
        fields = ["name", "is_active", "base_currency"]


# ==================== Position ====================


class PositionSerializer(serializers.Serializer[Any]):
    """统一账本持仓输出序列化器。"""

    id = serializers.IntegerField(read_only=True)
    portfolio = serializers.IntegerField(read_only=True)
    portfolio_name = serializers.CharField(read_only=True)
    asset_code = serializers.CharField(read_only=True)
    asset_name = serializers.CharField(read_only=True)
    category = serializers.IntegerField(read_only=True, allow_null=True)
    category_code = serializers.CharField(read_only=True, allow_null=True)
    category_name = serializers.CharField(read_only=True, allow_null=True)
    category_path = serializers.CharField(read_only=True, allow_null=True)
    currency = serializers.IntegerField(read_only=True, allow_null=True)
    currency_code = serializers.CharField(read_only=True, allow_null=True)
    currency_name = serializers.CharField(read_only=True, allow_null=True)
    currency_symbol = serializers.CharField(read_only=True, allow_null=True)
    asset_class = serializers.CharField(read_only=True, allow_null=True)
    region = serializers.CharField(read_only=True, allow_null=True)
    cross_border = serializers.CharField(read_only=True, allow_null=True)
    shares = serializers.FloatField(read_only=True)
    avg_cost = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)
    current_price = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)
    market_value = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    unrealized_pnl = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    unrealized_pnl_pct = serializers.FloatField(read_only=True)
    source_id = serializers.IntegerField(read_only=True, allow_null=True)
    is_closed = serializers.BooleanField(read_only=True)
    opened_at = serializers.DateTimeField(read_only=True, allow_null=True)
    closed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    def get_fields(self) -> dict[str, SerializerField]:
        """Register the public source field without overriding DRF state."""

        fields = super().get_fields()
        fields["source"] = serializers.CharField(read_only=True, allow_blank=True)
        return fields


class PositionCreateSerializer(serializers.ModelSerializer[Any]):
    """持仓创建序列化器"""

    class Meta:
        model = PositionModel
        fields = [
            "asset_code",
            "category",
            "currency",
            "asset_class",
            "region",
            "cross_border",
            "shares",
            "avg_cost",
            "current_price",
            "source",
            "source_id",
        ]

    def validate_shares(self, value: Any) -> Any:
        if value <= 0:
            raise serializers.ValidationError("持仓数量必须大于0")
        return value

    def validate_avg_cost(self, value: Any) -> Any:
        if value <= 0:
            raise serializers.ValidationError("平均成本价必须大于0")
        return value


class PositionUpdateSerializer(serializers.ModelSerializer[Any]):
    """持仓更新序列化器 — 平仓状态只能通过 close 接口变更，不能通过 PATCH/PUT 直接修改"""

    class Meta:
        model = PositionModel
        fields = ["shares", "avg_cost", "current_price"]


# ==================== Transaction ====================


class TransactionSerializer(serializers.ModelSerializer[Any]):
    """交易记录序列化器"""

    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)
    asset_code = serializers.CharField(read_only=True)

    class Meta:
        model = TransactionModel
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "position",
            "asset_code",
            "action",
            "shares",
            "price",
            "notional",
            "commission",
            "stamp_duty",
            "transfer_fee",
            "broker_name",
            "external_trade_id",
            "broker_trade_key",
            "import_batch",
            "notes",
            "traded_at",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class TransactionCreateSerializer(serializers.ModelSerializer[Any]):
    """交易记录创建序列化器"""

    class Meta:
        model = TransactionModel
        fields = [
            "portfolio",
            "position",
            "action",
            "asset_code",
            "shares",
            "price",
            "commission",
            "notes",
            "traded_at",
        ]

    def validate_shares(self, value: Any) -> Any:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise serializers.ValidationError("交易数量格式无效")
        if not math.isfinite(float(value)) or value <= 0:
            raise serializers.ValidationError("交易数量必须大于0")
        if value > 1_000_000_000_000:
            raise serializers.ValidationError("交易数量超出允许范围")
        return value

    def validate_price(self, value: Any) -> Any:
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise serializers.ValidationError("交易价格必须大于0")
        return value

    def validate_commission(self, value: Any) -> Any:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise serializers.ValidationError("手续费必须为非负有限金额")
        return value

    def validate_traded_at(self, value: Any) -> Any:
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("交易时间不能晚于当前时间")
        return value


# ==================== Capital Flow ====================


class CapitalFlowSerializer(serializers.ModelSerializer[Any]):
    """资金流水序列化器"""

    portfolio_name = serializers.CharField(source="portfolio.name", read_only=True)

    class Meta:
        model = CapitalFlowModel
        fields = [
            "id",
            "portfolio",
            "portfolio_name",
            "flow_type",
            "amount",
            "flow_date",
            "notes",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class CapitalFlowCreateSerializer(serializers.ModelSerializer[Any]):
    """资金流水创建序列化器"""

    portfolio = serializers.IntegerField(min_value=1, write_only=True)

    class Meta:
        model = CapitalFlowModel
        fields = ["portfolio", "flow_type", "amount", "flow_date", "notes"]

    def validate_amount(self, value: Any) -> Any:
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise serializers.ValidationError("金额必须大于0")
        return value


# ==================== Asset Metadata ====================


class AssetMetadataSerializer(serializers.ModelSerializer[Any]):
    """资产元数据序列化器"""

    class Meta:
        model = AssetMetadataModel
        fields = [
            "id",
            "asset_code",
            "name",
            "description",
            "asset_class",
            "region",
            "cross_border",
            "style",
            "sector",
            "sub_class",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


# ==================== Statistics ====================


class PortfolioStatisticsSerializer(serializers.Serializer[dict[str, Any]]):
    """投资组合统计序列化器"""

    total_value = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_pnl = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_pnl_pct = serializers.FloatField()
    position_count = serializers.IntegerField()
    asset_class_breakdown = serializers.DictField(child=serializers.FloatField())
    region_breakdown = serializers.DictField(child=serializers.FloatField())
    total_capital_inflow = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_capital_outflow = serializers.DecimalField(max_digits=20, decimal_places=2)
    net_capital_flow = serializers.DecimalField(max_digits=20, decimal_places=2)


# ==================== Observer Grant ====================


class ObserverGrantSerializer(serializers.ModelSerializer[Any]):
    """观察员授权序列化器"""

    owner_username = serializers.CharField(source="owner_user_id.username", read_only=True)
    observer_username = serializers.CharField(source="observer_user_id.username", read_only=True)
    scope_display = serializers.CharField(source="get_scope_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PortfolioObserverGrantModel
        fields = [
            "id",
            "owner_user_id",
            "observer_user_id",
            "owner_username",
            "observer_username",
            "scope",
            "scope_display",
            "status",
            "status_display",
            "expires_at",
            "is_valid",
            "created_at",
            "revoked_at",
            "revoked_by",
        ]
        read_only_fields = ["id", "created_at", "revoked_at", "revoked_by"]

    def get_fields(self) -> dict[str, SerializerField]:
        """Register validity output without overriding serializer validation state."""

        fields = super().get_fields()
        fields["is_valid"] = serializers.BooleanField(read_only=True)
        return fields


class ObserverGrantCreateSerializer(serializers.ModelSerializer[Any]):
    """观察员授权创建序列化器"""

    # 支持通过 observer_user_id 或 username 指定观察员
    observer_user_id = serializers.IntegerField(
        required=False, write_only=True, help_text="观察员用户ID（与 username 二选一）"
    )
    username = serializers.CharField(
        write_only=True, required=False, help_text="观察员用户名（与 observer_user_id 二选一）"
    )

    class Meta:
        model = PortfolioObserverGrantModel
        fields = ["observer_user_id", "username", "expires_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """验证创建授权请求"""
        request = self.context.get("request")
        if not request or not request.user:
            raise serializers.ValidationError("用户未登录")

        # 获取观察员用户
        observer_user_id = attrs.get("observer_user_id")
        username = attrs.get("username")

        if not observer_user_id and not username:
            raise serializers.ValidationError(
                {"observer_user_id": "请提供 observer_user_id 或 username"}
            )

        if username:
            observer = find_user_by_username(username)
            if observer is None:
                raise serializers.ValidationError({"username": f"用户 '{username}' 不存在"})
        elif observer_user_id:
            observer = find_user_by_id(int(observer_user_id))
            if observer is None:
                raise serializers.ValidationError({"observer_user_id": "观察员用户不存在"})
        else:
            raise serializers.ValidationError({"observer_user_id": "请提供观察员用户"})

        attrs["observer_user_id"] = observer.id

        # 不能授权给自己
        if observer.id == request.user.id:
            raise serializers.ValidationError({"observer_user_id": "不能授权给自己"})

        # 检查是否已存在 active 授权
        existing = get_active_observer_grant(
            owner_user_id=request.user.id,
            observer_user_id=observer.id,
        )
        if existing:
            raise serializers.ValidationError(
                {"observer_user_id": f"该用户已被授权为观察员，授权 ID: {existing.id}"}
            )

        # 检查观察员数量限制（每账户最多 10 个）
        active_count = count_owned_active_observer_grants(request.user.id)
        if active_count >= 10:
            raise serializers.ValidationError(
                {"__all__": "已达到观察员数量上限（10个），请先撤销部分授权"}
            )

        # 验证过期时间
        expires_at = attrs.get("expires_at")
        if expires_at:
            from django.utils import timezone

            if expires_at <= timezone.now():
                raise serializers.ValidationError({"expires_at": "过期时间必须大于当前时间"})

        return attrs

    def create(self, validated_data: dict[str, Any]) -> Any:
        """创建授权记录"""
        validated_data.pop("username", None)  # 移除临时字段
        owner = validated_data.pop("owner_user_id")
        grant = create_observer_grant_record(
            owner_user_id=getattr(owner, "id", owner),
            observer_user_id=int(validated_data.pop("observer_user_id")),
            created_by_user_id=self.context["request"].user.id,
            expires_at=validated_data.get("expires_at"),
        )
        return grant


class ObserverGrantUpdateSerializer(serializers.ModelSerializer[Any]):
    """观察员授权更新序列化器（仅支持更新过期时间）"""

    class Meta:
        model = PortfolioObserverGrantModel
        fields = ["expires_at"]

    def validate_expires_at(self, value: Any) -> Any:
        """验证过期时间"""
        if value:
            from django.utils import timezone

            if value <= timezone.now():
                raise serializers.ValidationError("过期时间必须大于当前时间")
        return value


# ==================== Trading Cost Config ====================


class TradingCostConfigSerializer(serializers.ModelSerializer[Any]):
    """交易费率配置序列化器"""

    # 只读计算字段：以万为单位的佣金率（方便展示）
    commission_rate_wan = serializers.SerializerMethodField()
    stamp_duty_rate_qian = serializers.SerializerMethodField()

    class Meta:
        model = TradingCostConfigModel
        fields = [
            "id",
            "portfolio",
            "commission_rate",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "is_active",
            "commission_rate_wan",
            "stamp_duty_rate_qian",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_commission_rate_wan(self, obj: Any) -> float:
        """佣金率（万）"""
        return float(round(obj.commission_rate * 10000, 2))

    def get_stamp_duty_rate_qian(self, obj: Any) -> float:
        """印花税率（千）"""
        return float(round(obj.stamp_duty_rate * 1000, 2))


class TradingCostConfigCreateSerializer(serializers.ModelSerializer[Any]):
    """交易费率配置创建/更新序列化器"""

    class Meta:
        model = TradingCostConfigModel
        fields = [
            "portfolio",
            "commission_rate",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "is_active",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        portfolio = attrs.get("portfolio")
        if (
            self.instance is not None
            and portfolio is not None
            and portfolio != self.instance.portfolio
        ):
            raise serializers.ValidationError({"portfolio": "更新时不允许修改所属投资组合"})
        return attrs

    def validate_commission_rate(self, value: float) -> float:
        if value < 0 or value > 0.01:
            raise serializers.ValidationError("佣金率应在 0 ~ 0.01（万0 ~ 万10）之间")
        return value

    def validate_min_commission(self, value: float) -> float:
        if value < 0:
            raise serializers.ValidationError("最低佣金不能为负数")
        return value

    def validate_stamp_duty_rate(self, value: float) -> float:
        if value < 0 or value > 0.01:
            raise serializers.ValidationError("印花税率应在 0 ~ 0.01 之间")
        return value

    def validate_transfer_fee_rate(self, value: float) -> float:
        if value < 0 or value > 0.001:
            raise serializers.ValidationError("过户费率应在 0 ~ 0.001 之间")
        return value


class TradingCostCalculationSerializer(serializers.Serializer[dict[str, Any]]):
    """交易费率试算参数校验"""

    ACTION_CHOICES = ("buy", "sell")

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    amount = serializers.FloatField(min_value=0.01)
    is_shanghai = serializers.BooleanField(required=False, default=False)


class MacroSizingConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """宏观仓位系数配置输出序列化器。"""

    id = serializers.IntegerField(allow_null=True, required=False)
    version = serializers.IntegerField()
    is_active = serializers.BooleanField()
    description = serializers.CharField(allow_blank=True)
    warning_factor = serializers.FloatField()
    regime_tiers_json = serializers.JSONField()
    pulse_tiers_json = serializers.JSONField()
    drawdown_tiers_json = serializers.JSONField()
    market_temperature_cold_factor = serializers.FloatField()
    market_temperature_warm_factor = serializers.FloatField()
    market_temperature_hot_factor = serializers.FloatField()
    market_temperature_overheat_factor = serializers.FloatField()
    market_temperature_extreme_factor = serializers.FloatField()
    block_new_position_on_extreme = serializers.BooleanField()
    created_at = serializers.DateTimeField(allow_null=True, required=False)
    updated_at = serializers.DateTimeField(allow_null=True, required=False)


class MacroSizingConfigUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """宏观仓位系数配置更新序列化器。"""

    description = serializers.CharField(required=False, allow_blank=True)
    warning_factor = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)
    regime_tiers_json = serializers.JSONField(required=False)
    pulse_tiers_json = serializers.JSONField(required=False)
    drawdown_tiers_json = serializers.JSONField(required=False)
    market_temperature_cold_factor = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )
    market_temperature_warm_factor = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )
    market_temperature_hot_factor = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )
    market_temperature_overheat_factor = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )
    market_temperature_extreme_factor = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
    )
    block_new_position_on_extreme = serializers.BooleanField(required=False)

    def validate_regime_tiers_json(self, value: Any) -> Any:
        self._validate_tiers(
            value,
            required_keys=("min_confidence", "factor"),
            field_name="regime_tiers_json",
        )
        return value

    def validate_pulse_tiers_json(self, value: Any) -> Any:
        self._validate_tiers(
            value,
            required_keys=("min_composite", "factor"),
            field_name="pulse_tiers_json",
        )
        return value

    def validate_drawdown_tiers_json(self, value: Any) -> Any:
        self._validate_tiers(
            value,
            required_keys=("min_drawdown", "factor"),
            field_name="drawdown_tiers_json",
        )
        return value

    @staticmethod
    def _validate_tiers(
        value: Any,
        *,
        required_keys: tuple[str, ...],
        field_name: str,
    ) -> None:
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError(f"{field_name} 必须是非空数组")
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError(f"{field_name} 每一项都必须是对象")
            missing = [key for key in required_keys if key not in item]
            if missing:
                raise serializers.ValidationError(f"{field_name} 缺少字段: {', '.join(missing)}")


class MCPTokenAccessLevelChoiceSerializer(serializers.Serializer[dict[str, Any]]):
    """MCP Token access-level choice payload."""

    value = serializers.CharField(read_only=True)

    def get_fields(self) -> dict[str, SerializerField]:
        """Register the public label without overriding DRF field metadata."""

        fields = super().get_fields()
        fields["label"] = serializers.CharField(read_only=True)
        return fields


class MCPAccessTokenSerializer(serializers.Serializer[dict[str, Any]]):
    """MCP access token summary payload."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    preview = serializers.CharField(read_only=True)
    display_token = serializers.CharField(read_only=True, allow_blank=True, required=False)
    access_level = serializers.CharField(read_only=True)
    access_level_label = serializers.CharField(read_only=True)
    plaintext = serializers.CharField(read_only=True, allow_blank=True, required=False)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_used_at = serializers.DateTimeField(read_only=True, allow_null=True)
    is_recommended = serializers.BooleanField(read_only=True, required=False)


class MCPAccessPackageSerializer(serializers.Serializer[dict[str, Any]]):
    """Canonical copy-ready MCP access package."""

    token = serializers.CharField(read_only=True, allow_blank=True)
    token_preview = serializers.CharField(read_only=True, allow_blank=True)
    route_endpoint = serializers.CharField(read_only=True)
    capability_catalog_endpoint = serializers.CharField(read_only=True)
    agent_prompt = serializers.CharField(read_only=True)
    base_url = serializers.CharField(read_only=True)
    same_machine_only = serializers.BooleanField(read_only=True)
    environment_statement = serializers.CharField(read_only=True)


class MCPAgentPromptSerializer(serializers.Serializer[dict[str, Any]]):
    """Copy-ready agent bootstrap prompt payload."""

    agent_bootstrap_prompt = serializers.CharField(read_only=True)
    agent_bootstrap_token_ready = serializers.BooleanField(read_only=True)
    agent_bootstrap_token_name = serializers.CharField(read_only=True, allow_blank=True)
    agent_bootstrap_access_level = serializers.CharField(read_only=True, allow_blank=True)
    agent_bootstrap_access_level_label = serializers.CharField(read_only=True, allow_blank=True)


class MCPSelfServicePayloadSerializer(MCPAgentPromptSerializer):
    """Current-user MCP self-service payload."""

    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    mcp_enabled = serializers.BooleanField(read_only=True)
    rbac_role = serializers.CharField(read_only=True, allow_blank=True)
    token_plaintext_allowed = serializers.BooleanField(read_only=True)
    active_token_count = serializers.IntegerField(read_only=True)
    self_service_state = serializers.ChoiceField(
        choices=("disabled", "no_token", "ready", "unavailable"),
        read_only=True,
    )
    self_service_blocking_reason = serializers.ChoiceField(
        choices=(
            "",
            "mcp_disabled",
            "no_token",
            "routing_unavailable",
            "catalog_unavailable",
            "token_plaintext_disabled",
            "token_decryption_failed",
            "token_plaintext_unavailable",
        ),
        read_only=True,
    )
    recommended_token_id = serializers.IntegerField(read_only=True, allow_null=True)
    account_count = serializers.IntegerField(read_only=True)
    default_account_id = serializers.IntegerField(read_only=True, allow_null=True)
    default_account_name = serializers.CharField(read_only=True, allow_blank=True)
    base_url = serializers.CharField(read_only=True)
    api_root_endpoint = serializers.CharField(read_only=True, allow_blank=True)
    route_endpoint = serializers.CharField(read_only=True, allow_blank=True)
    web_endpoint = serializers.CharField(read_only=True, allow_blank=True)
    capability_endpoint = serializers.CharField(read_only=True, allow_blank=True)
    current_token_value = serializers.CharField(read_only=True, allow_blank=True)
    current_token_display = serializers.CharField(read_only=True, allow_blank=True)
    preferred_token = MCPAccessTokenSerializer(read_only=True, allow_null=True)
    access_tokens = MCPAccessTokenSerializer(many=True, read_only=True)
    access_package = MCPAccessPackageSerializer(read_only=True)
    token_access_level_choices = MCPTokenAccessLevelChoiceSerializer(many=True, read_only=True)


class MCPAdminUserRowSerializer(serializers.Serializer[dict[str, Any]]):
    """Admin-facing MCP governance row for one user."""

    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True, allow_blank=True)
    approval_status = serializers.CharField(read_only=True, allow_blank=True)
    rbac_role = serializers.CharField(read_only=True, allow_blank=True)
    mcp_enabled = serializers.BooleanField(read_only=True)
    has_token = serializers.BooleanField(read_only=True)
    token_count = serializers.IntegerField(read_only=True)
    read_only_token_count = serializers.IntegerField(read_only=True)
    tokens = MCPAccessTokenSerializer(many=True, read_only=True)


class MCPAdminUsersPayloadSerializer(serializers.Serializer[dict[str, Any]]):
    """Admin-facing MCP user governance payload."""

    search_query = serializers.CharField(read_only=True, allow_blank=True)
    only_without_token = serializers.BooleanField(read_only=True)
    total_users = serializers.IntegerField(read_only=True)
    with_token_count = serializers.IntegerField(read_only=True)
    without_token_count = serializers.IntegerField(read_only=True)
    total_token_count = serializers.IntegerField(read_only=True)
    system_default_mcp_enabled = serializers.BooleanField(read_only=True)
    allow_token_plaintext_view = serializers.BooleanField(read_only=True)
    rows = MCPAdminUserRowSerializer(many=True, read_only=True)


class MCPAdminUserDetailSerializer(MCPSelfServicePayloadSerializer):
    """Admin-facing MCP detail payload for one target user."""

    email = serializers.CharField(read_only=True, allow_blank=True)


class MCPTokenCreateRequestSerializer(serializers.Serializer[dict[str, Any]]):
    """Create-token request payload for self/admin MCP flows."""

    token_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    access_level = serializers.ChoiceField(
        choices=TOKEN_ACCESS_LEVEL_CHOICES,
        required=False,
        default=TOKEN_ACCESS_LEVEL_READ_ONLY,
    )


class MCPAdminUsersQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Admin MCP user list query params."""

    q = serializers.CharField(required=False, allow_blank=True, default="")
    without_token = serializers.BooleanField(required=False, default=False)


class MCPTokenPayloadSerializer(serializers.Serializer[dict[str, Any]]):
    """Newly created MCP token payload."""

    username = serializers.CharField(read_only=True)
    token_name = serializers.CharField(read_only=True)
    token = serializers.CharField(read_only=True)
    access_level = serializers.CharField(read_only=True)
    access_level_label = serializers.CharField(read_only=True)
    generated_at = serializers.CharField(read_only=True)


class MCPMutationResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Generic mutation response payload for MCP governance flows."""

    success = serializers.BooleanField(read_only=True)
    message = serializers.CharField(read_only=True)
    token_id = serializers.IntegerField(read_only=True, required=False)
    token_payload = MCPTokenPayloadSerializer(read_only=True, allow_null=True, required=False)
    created_agent_prompt = MCPAgentPromptSerializer(read_only=True, required=False)
    self_service = MCPSelfServicePayloadSerializer(read_only=True, required=False)
    user_detail = MCPAdminUserDetailSerializer(read_only=True, required=False)
