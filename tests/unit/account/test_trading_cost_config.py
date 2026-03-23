"""
交易费率配置 - 单元测试

测试 Domain 层 TradingCostConfig 实体的费用计算逻辑。
"""
import pytest

from apps.account.domain.entities import TradingCostConfig


@pytest.fixture
def default_config():
    """默认费率配置（万2.5佣金、千1印花税）"""
    return TradingCostConfig(id=1, portfolio_id=1)


@pytest.fixture
def vip_config():
    """VIP费率配置（万1佣金）"""
    return TradingCostConfig(
        id=2,
        portfolio_id=2,
        commission_rate=0.0001,
        min_commission=5.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
    )


class TestTradingCostConfigBuyCost:
    """买入费用计算"""

    def test_buy_cost_basic(self, default_config: TradingCostConfig):
        """10万元深市买入，佣金=25元"""
        cost = default_config.calculate_buy_cost(100000, is_shanghai=False)
        assert cost["commission"] == 25.0
        assert cost["stamp_duty"] == 0.0
        assert cost["transfer_fee"] == 0.0
        assert cost["total"] == 25.0

    def test_buy_cost_shanghai(self, default_config: TradingCostConfig):
        """10万元沪市买入，佣金+过户费"""
        cost = default_config.calculate_buy_cost(100000, is_shanghai=True)
        assert cost["commission"] == 25.0
        assert cost["transfer_fee"] == 2.0
        assert cost["total"] == 27.0

    def test_buy_cost_min_commission(self, default_config: TradingCostConfig):
        """小额交易触发最低佣金（5元）"""
        cost = default_config.calculate_buy_cost(1000, is_shanghai=False)
        # 1000 * 0.00025 = 0.25 < 5，按最低佣金收取
        assert cost["commission"] == 5.0
        assert cost["total"] == 5.0

    def test_buy_no_stamp_duty(self, default_config: TradingCostConfig):
        """买入无印花税"""
        cost = default_config.calculate_buy_cost(1000000, is_shanghai=True)
        assert cost["stamp_duty"] == 0.0


class TestTradingCostConfigSellCost:
    """卖出费用计算"""

    def test_sell_cost_basic(self, default_config: TradingCostConfig):
        """10万元深市卖出，佣金+印花税"""
        cost = default_config.calculate_sell_cost(100000, is_shanghai=False)
        assert cost["commission"] == 25.0
        assert cost["stamp_duty"] == 100.0
        assert cost["transfer_fee"] == 0.0
        assert cost["total"] == 125.0

    def test_sell_cost_shanghai(self, default_config: TradingCostConfig):
        """10万元沪市卖出，佣金+印花税+过户费"""
        cost = default_config.calculate_sell_cost(100000, is_shanghai=True)
        assert cost["commission"] == 25.0
        assert cost["stamp_duty"] == 100.0
        assert cost["transfer_fee"] == 2.0
        assert cost["total"] == 127.0

    def test_sell_cost_min_commission(self, default_config: TradingCostConfig):
        """小额卖出触发最低佣金"""
        cost = default_config.calculate_sell_cost(1000, is_shanghai=False)
        assert cost["commission"] == 5.0
        assert cost["stamp_duty"] == 1.0
        assert cost["total"] == 6.0


class TestTradingCostConfigRoundTrip:
    """完整买卖一轮的费用"""

    def test_round_trip_100k_shenzhen(self, default_config: TradingCostConfig):
        """10万元深市一买一卖"""
        buy = default_config.calculate_buy_cost(100000, is_shanghai=False)
        sell = default_config.calculate_sell_cost(100000, is_shanghai=False)
        total = buy["total"] + sell["total"]
        assert total == 150.0  # 25 + 125
        ratio = total / 100000 * 100
        assert ratio == 0.15  # 0.15%

    def test_round_trip_100k_shanghai(self, default_config: TradingCostConfig):
        """10万元沪市一买一卖"""
        buy = default_config.calculate_buy_cost(100000, is_shanghai=True)
        sell = default_config.calculate_sell_cost(100000, is_shanghai=True)
        total = buy["total"] + sell["total"]
        assert total == 154.0  # 27 + 127


class TestVIPConfig:
    """VIP费率（万1）"""

    def test_vip_lower_commission(self, vip_config: TradingCostConfig):
        """VIP佣金更低"""
        cost = vip_config.calculate_buy_cost(100000, is_shanghai=False)
        assert cost["commission"] == 10.0  # 100000 * 0.0001 = 10


class TestTradingCostConfigImmutability:
    """实体不可变性"""

    def test_frozen(self, default_config: TradingCostConfig):
        with pytest.raises(AttributeError):
            default_config.commission_rate = 0.0001
